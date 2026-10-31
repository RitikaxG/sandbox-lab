// termclient plays the agent's side of a terminal (L1 day 2): it opens the API's WebSocket terminal, runs one
// command, then follows a script of steps and prints everything it sees with ms since the start.
//
//	go run ./modules/L1-commands-and-processes/termclient -sandbox ID -cmd '["sh","-c","read a; echo got $a"]' \
//	    -rows 24 -cols 80 -timeout 10  sleep:1 'keys:y\r' resize:40x120 ctrlc close
//
// Steps: sleep:S (seconds), keys:TEXT (Go escapes: \r is Enter, \x03 is Ctrl-C), ctrlc, resize:ROWSxCOLS, close
// (drop the connection without a goodbye, like a crashed agent). After the steps it waits up to -wait seconds for the
// result. The last line is RESULT {...}, ERROR {...}, or NO RESULT.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
)

func main() {
	api := flag.String("api", "ws://localhost:8080", "API address")
	sandbox := flag.String("sandbox", "", "sandbox ID")
	cmdJSON := flag.String("cmd", "", `command as JSON, e.g. ["sh","-c","stty size"]`)
	timeout := flag.Float64("timeout", 0, "timeout_s sent to the API (0 = none)")
	rows := flag.Uint("rows", 0, "first window rows (0 = Docker's default)")
	cols := flag.Uint("cols", 0, "first window columns")
	wait := flag.Float64("wait", 30, "seconds to wait for the result after the steps")
	flag.Parse()

	var cmd []string
	if err := json.Unmarshal([]byte(*cmdJSON), &cmd); err != nil || *sandbox == "" {
		fmt.Fprintln(os.Stderr, "need -sandbox and -cmd as a JSON list")
		os.Exit(2)
	}
	t0 := time.Now()
	say := func(format string, a ...any) {
		fmt.Printf("%+8.1f ms  %s\n", float64(time.Since(t0).Microseconds())/1000, fmt.Sprintf(format, a...))
	}

	ctx := context.Background()
	c, _, err := websocket.Dial(ctx, *api+"/sandboxes/"+*sandbox+"/terminal", nil)
	if err != nil {
		say("ERROR %q", err.Error())
		os.Exit(1)
	}
	wsjson.Write(ctx, c, map[string]any{"cmd": cmd, "timeout_s": *timeout, "rows": *rows, "cols": *cols})
	say("started %q, timeout_s %v, size %dx%d", cmd, *timeout, *rows, *cols)

	final := make(chan string, 1)
	go func() {
		for {
			typ, data, err := c.Read(ctx)
			if err != nil {
				final <- ""
				return
			}
			if typ == websocket.MessageBinary {
				say("out %q", data)
				continue
			}
			final <- string(data)
			return
		}
	}()

	for _, step := range flag.Args() {
		name, arg, _ := strings.Cut(step, ":")
		switch name {
		case "sleep":
			s, _ := strconv.ParseFloat(arg, 64)
			time.Sleep(time.Duration(s * float64(time.Second)))
		case "keys", "ctrlc":
			text := "\x03"
			if name == "keys" {
				text, err = strconv.Unquote(`"` + arg + `"`)
				if err != nil {
					say("bad keys %q", arg)
					os.Exit(2)
				}
			}
			c.Write(ctx, websocket.MessageBinary, []byte(text))
			say("sent keys %q", text)
		case "resize":
			r, cl, _ := strings.Cut(arg, "x")
			rn, _ := strconv.Atoi(r)
			cn, _ := strconv.Atoi(cl)
			wsjson.Write(ctx, c, map[string]any{"resize": []int{rn, cn}})
			say("sent resize %dx%d", rn, cn)
		case "close":
			c.CloseNow()
			say("closed the connection (no goodbye)")
			fmt.Println("NO RESULT (client left)")
			return
		default:
			say("unknown step %q", step)
			os.Exit(2)
		}
	}

	select {
	case msg := <-final:
		switch {
		case msg == "":
			say("connection ended")
			fmt.Println("NO RESULT")
		case strings.HasPrefix(msg, `{"error"`):
			fmt.Println("ERROR " + msg)
		default:
			var r struct {
				Result json.RawMessage `json:"result"`
			}
			json.Unmarshal([]byte(msg), &r)
			say("result")
			fmt.Println("RESULT " + string(r.Result))
		}
	case <-time.After(time.Duration(*wait * float64(time.Second))):
		say("no result after %v s", *wait)
		fmt.Println("NO RESULT")
	}
	c.Close(websocket.StatusNormalClosure, "")
}
