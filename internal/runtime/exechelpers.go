package runtime

import (
	"bytes"
	"strconv"
	"strings"
)

// writerFunc turns a function into an io.Writer.
type writerFunc func(p []byte)

func (f writerFunc) Write(p []byte) (int, error) {
	f(p)
	return len(p), nil
}

// pidReader takes the exec wrapper's first stderr line (pidMarker + PID), sends the PID on pid, and passes
// everything after it on to next, so the caller sees only the command's own stderr.
type pidReader struct {
	pid  chan<- int
	next func(p []byte)
	buf  []byte
	seen bool
}

func (r *pidReader) Write(p []byte) (int, error) {
	if r.seen {
		r.next(p)
		return len(p), nil
	}
	r.buf = append(r.buf, p...)
	nl := bytes.IndexByte(r.buf, '\n')
	if nl < 0 {
		return len(p), nil // the line isn't complete yet
	}
	r.seen = true
	// A terminal turns "\n" into "\r\n", so the line may end in "\r".
	line, rest := strings.TrimSuffix(string(r.buf[:nl]), "\r"), r.buf[nl+1:]
	if pid, err := strconv.Atoi(strings.TrimPrefix(line, pidMarker)); err == nil && strings.HasPrefix(line, pidMarker) {
		r.pid <- pid
	} else {
		rest = r.buf // not our line (the wrapper itself failed): pass it all on
	}
	if len(rest) > 0 {
		r.next(rest)
	}
	r.buf = nil
	return len(p), nil
}

// parsePS reads `ps -o pid,ppid,pgid,sid,stat,args` output.
func parsePS(out string) []Proc {
	var procs []Proc
	for i, line := range strings.Split(strings.TrimSpace(out), "\n") {
		f := strings.Fields(line)
		if i == 0 || len(f) < 6 {
			continue // header or a line we can't read
		}
		n := func(s string) int { v, _ := strconv.Atoi(s); return v }
		procs = append(procs, Proc{PID: n(f[0]), PPID: n(f[1]), PGID: n(f[2]), SID: n(f[3]), Stat: f[4], Args: strings.Join(f[5:], " ")})
	}
	return procs
}
