// Package api is the sandbox API's HTTP side: it takes requests, keeps the list of sandboxes,
// and asks the runtime (Docker) to do the real work.
package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"

	"github.com/RitikaxG/sandbox-lab/internal/runtime"
)

// Sandbox is the API's record of one sandbox.
type Sandbox struct {
	ID        string    `json:"id"`
	RuntimeID string    `json:"runtime_id"` // the container ID
	Image     string    `json:"image"`
	Cmd       []string  `json:"cmd"`
	State     string    `json:"state"` // creating, running, failed, deleting
	Error     string    `json:"error,omitempty"`
	CreatedAt time.Time `json:"created_at"`
	CreateMS  int64     `json:"create_ms"` // time spent in runtime.Create (create + start)

	basePIDs map[int]bool // the sandbox's own processes, seen right after create; never counted as leaks
}

// grace is decision 002 step 2: the time between SIGTERM and SIGKILL when a command is stopped.
const grace = 2 * time.Second

// Server holds the sandbox list in memory only (L0): if this process dies, the list is gone,
// but the containers in Docker are not. L2 replaces this map with Postgres.
type Server struct {
	rt runtime.Runtime

	mu        sync.Mutex
	sandboxes map[string]*Sandbox
}

func New(rt runtime.Runtime) *Server {
	return &Server{rt: rt, sandboxes: map[string]*Sandbox{}}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /sandboxes", s.create)
	mux.HandleFunc("GET /sandboxes", s.list)
	mux.HandleFunc("GET /sandboxes/{id}", s.get)
	mux.HandleFunc("POST /sandboxes/{id}/exec", s.exec)
	mux.HandleFunc("GET /sandboxes/{id}/terminal", s.terminal)
	mux.HandleFunc("DELETE /sandboxes/{id}", s.delete)
	return mux
}

type createReq struct {
	Image string   `json:"image"`
	Cmd   []string `json:"cmd"`
}

func (s *Server) create(w http.ResponseWriter, r *http.Request) {
	req := createReq{Image: "alpine", Cmd: []string{"sleep", "86400"}}
	if r.ContentLength != 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeErr(w, http.StatusBadRequest, "bad JSON: "+err.Error())
			return
		}
	}

	sb := &Sandbox{ID: newID(), Image: req.Image, Cmd: req.Cmd, State: "creating", CreatedAt: time.Now().UTC()}
	s.mu.Lock()
	s.sandboxes[sb.ID] = sb
	s.mu.Unlock()

	start := time.Now()
	rid, err := s.rt.Create(r.Context(), runtime.Spec{SandboxID: sb.ID, Image: req.Image, Cmd: req.Cmd})
	ms := time.Since(start).Milliseconds()

	s.mu.Lock()
	sb.RuntimeID, sb.CreateMS = rid, ms
	if err != nil {
		sb.State, sb.Error = "failed", err.Error()
	} else {
		sb.State = "running"
	}
	out := *sb
	s.mu.Unlock()

	if err != nil {
		// Half-made (created, not started): remove what exists, keep the record as failed.
		if rid != "" {
			_ = s.rt.Delete(context.Background(), rid)
		}
		log.Printf("api: create %s failed after %d ms: %v", sb.ID, ms, err)
		writeJSON(w, http.StatusInternalServerError, out)
		return
	}
	base := s.baseline(rid)
	s.mu.Lock()
	sb.basePIDs = base
	s.mu.Unlock()
	log.Printf("api: create %s -> %s in %d ms", sb.ID, short(rid), ms)
	writeJSON(w, http.StatusCreated, out)
}

func (s *Server) list(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	out := make([]Sandbox, 0, len(s.sandboxes))
	for _, sb := range s.sandboxes {
		out = append(out, *sb)
	}
	s.mu.Unlock()
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.Before(out[j].CreatedAt) })
	writeJSON(w, http.StatusOK, out)
}

func (s *Server) get(w http.ResponseWriter, r *http.Request) {
	sb, ok := s.lookup(r.PathValue("id"))
	if !ok {
		writeErr(w, http.StatusNotFound, "no such sandbox")
		return
	}
	writeJSON(w, http.StatusOK, sb)
}

// baseline records the sandbox's own processes (tini as PID 1 and the main program it starts), so a later
// stop can tell them from leftovers. tini may not have started the main program the instant Create returns,
// so it waits briefly for a child of PID 1.
func (s *Server) baseline(rid string) map[int]bool {
	base := map[int]bool{}
	for deadline := time.Now().Add(time.Second); ; {
		procs, err := s.rt.Processes(context.Background(), rid)
		if err != nil {
			log.Printf("api: baseline %s: %v", short(rid), err)
			return base
		}
		hasMain := false
		for _, p := range procs {
			if !strings.HasPrefix(p.Args, "ps ") {
				base[p.PID] = true
				hasMain = hasMain || p.PPID == 1
			}
		}
		if hasMain || time.Now().After(deadline) {
			return base
		}
		time.Sleep(20 * time.Millisecond)
	}
}

type execReq struct {
	Cmd      []string `json:"cmd"`
	TimeoutS float64  `json:"timeout_s"` // 0 or absent = no time limit (a client disconnect still stops it)
	Stream   bool     `json:"stream"`    // true = output as it arrives, one JSON object per line, result last
	Sweep    bool     `json:"sweep"`     // decision 002 option D, for the flip: SIGKILL everything but PID 1 after
}

func (s *Server) exec(w http.ResponseWriter, r *http.Request) {
	sb, ok := s.lookup(r.PathValue("id"))
	if !ok {
		writeErr(w, http.StatusNotFound, "no such sandbox")
		return
	}
	if sb.State != "running" {
		writeErr(w, http.StatusConflict, "sandbox is "+sb.State)
		return
	}
	var req execReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.Cmd) == 0 {
		writeErr(w, http.StatusBadRequest, `body must be {"cmd": ["ls", "/"]}, optional "timeout_s": 5, "stream": true`)
		return
	}
	opts := runtime.ExecOpts{
		Timeout:  time.Duration(req.TimeoutS * float64(time.Second)),
		Grace:    grace,
		Baseline: sb.basePIDs,
		Sweep:    req.Sweep,
	}

	// r.Context() ends when the client goes away: the runtime then stops the command (stopped_by "disconnect").
	if !req.Stream {
		res, err := s.rt.Exec(r.Context(), sb.RuntimeID, req.Cmd, opts)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		s.logExec(sb.ID, req.Cmd, res)
		writeJSON(w, http.StatusOK, res)
		return
	}

	// Streaming: one JSON object per line, sent as soon as the output arrives; the result is the last line.
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.WriteHeader(http.StatusOK)
	flusher, _ := w.(http.Flusher)
	enc := json.NewEncoder(w)
	send := func(v any) {
		enc.Encode(v) // fails once the client is gone; the runtime finds out through r.Context()
		if flusher != nil {
			flusher.Flush()
		}
	}
	opts.Output = func(stream string, p []byte) { send(map[string]string{"stream": stream, "data": string(p)}) }
	res, err := s.rt.Exec(r.Context(), sb.RuntimeID, req.Cmd, opts)
	if err != nil {
		send(map[string]string{"error": err.Error()})
		return
	}
	s.logExec(sb.ID, req.Cmd, res)
	send(map[string]any{"result": res})
}

// termStart is the first message on a terminal connection.
type termStart struct {
	Cmd      []string `json:"cmd"`
	TimeoutS float64  `json:"timeout_s"` // 0 = no time limit (closing the connection still stops it)
	Rows     uint     `json:"rows"`      // first window size; 0 = Docker's default
	Cols     uint     `json:"cols"`
}

// terminal runs one command with a terminal over a WebSocket (Ritika, 2026-10-31: one connection for keys,
// output and resize). Client to API: the first message is termStart (JSON text); after that, binary messages are
// keys and text messages are {"resize": [rows, cols]}. API to client: binary messages are what the terminal shows;
// the last message is {"result": ...} or {"error": ...} (JSON text).
func (s *Server) terminal(w http.ResponseWriter, r *http.Request) {
	sb, ok := s.lookup(r.PathValue("id"))
	if !ok {
		writeErr(w, http.StatusNotFound, "no such sandbox")
		return
	}
	if sb.State != "running" {
		writeErr(w, http.StatusConflict, "sandbox is "+sb.State)
		return
	}
	c, err := websocket.Accept(w, r, nil)
	if err != nil {
		return // Accept has already answered the client
	}
	defer c.CloseNow()

	var start termStart
	readCtx, cancelRead := context.WithTimeout(r.Context(), 10*time.Second)
	err = wsjson.Read(readCtx, c, &start)
	cancelRead()
	if err != nil || len(start.Cmd) == 0 {
		c.Close(websocket.StatusPolicyViolation, `first message must be {"cmd": ["sh"], "timeout_s": 0, "rows": 24, "cols": 80}`)
		return
	}

	// After the upgrade, Go's HTTP server no longer watches the connection (P18): r.Context() won't end when
	// the client goes. The read loop below is what notices, and it ends ctx (stopped_by "disconnect").
	ctx, gone := context.WithCancel(context.Background())
	defer gone()
	keys, keysIn := io.Pipe()
	resize := make(chan [2]uint)
	go func() {
		defer gone()
		defer keysIn.Close()
		for {
			typ, data, err := c.Read(ctx)
			if err != nil {
				return
			}
			if typ == websocket.MessageBinary {
				keysIn.Write(data)
				continue
			}
			var msg struct {
				Resize [2]uint `json:"resize"`
			}
			if json.Unmarshal(data, &msg) == nil && msg.Resize[0] > 0 {
				select {
				case resize <- msg.Resize:
				case <-ctx.Done():
					return
				}
			}
		}
	}()

	opts := runtime.ExecOpts{
		Timeout:  time.Duration(start.TimeoutS * float64(time.Second)),
		Grace:    grace,
		Baseline: sb.basePIDs,
		Tty:      true,
		Input:    keys,
		Size:     [2]uint{start.Rows, start.Cols},
		Resize:   resize,
		Output: func(_ string, p []byte) {
			c.Write(context.Background(), websocket.MessageBinary, p) // fails once the client is gone
		},
	}
	res, err := s.rt.Exec(ctx, sb.RuntimeID, start.Cmd, opts)
	if err != nil {
		wsjson.Write(context.Background(), c, map[string]string{"error": err.Error()})
		c.Close(websocket.StatusInternalError, "exec failed")
		return
	}
	s.logExec(sb.ID, start.Cmd, res)
	wsjson.Write(context.Background(), c, map[string]any{"result": res})
	c.Close(websocket.StatusNormalClosure, "")
}

func (s *Server) logExec(id string, cmd []string, res runtime.ExecResult) {
	log.Printf("api: exec %s %q -> exit %d, stopped_by %s, stop %d ms, %d leaks",
		id, strings.Join(cmd, " "), res.ExitCode, res.StoppedBy, res.StopMS, len(res.Leaks))
}

func (s *Server) delete(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	s.mu.Lock()
	sb, ok := s.sandboxes[id]
	if ok {
		sb.State = "deleting"
	}
	s.mu.Unlock()
	if !ok {
		writeErr(w, http.StatusNotFound, "no such sandbox")
		return
	}
	if sb.RuntimeID != "" {
		if err := s.rt.Delete(r.Context(), sb.RuntimeID); err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
	}
	s.mu.Lock()
	delete(s.sandboxes, id)
	s.mu.Unlock()
	log.Printf("api: delete %s", id)
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) lookup(id string) (Sandbox, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	sb, ok := s.sandboxes[id]
	if !ok {
		return Sandbox{}, false
	}
	return *sb, true
}

func newID() string {
	b := make([]byte, 4)
	rand.Read(b)
	return hex.EncodeToString(b)
}

func short(id string) string {
	if len(id) > 12 {
		return id[:12]
	}
	return id
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	enc.Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
