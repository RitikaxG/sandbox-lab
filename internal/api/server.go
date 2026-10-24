// Package api is the sandbox API's HTTP side: it takes requests, keeps the list of sandboxes,
// and asks the runtime (Docker) to do the real work.
package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"sort"
	"sync"
	"time"

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
}

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

type execReq struct {
	Cmd []string `json:"cmd"`
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
		writeErr(w, http.StatusBadRequest, `body must be {"cmd": ["ls", "/"]}`)
		return
	}
	res, err := s.rt.Exec(r.Context(), sb.RuntimeID, req.Cmd)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, res)
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
