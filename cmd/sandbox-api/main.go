// sandbox-api is the lab's sandbox control plane (L0: Docker runtime, state in memory).
//
//	go run ./cmd/sandbox-api            # listens on localhost:8080
//	go run ./cmd/sandbox-api -runtime docker-cli   # option A: shell out to the docker program
//	curl -X POST localhost:8080/sandboxes
package main

import (
	"flag"
	"log"
	"net/http"

	"github.com/RitikaxG/sandbox-lab/internal/api"
	"github.com/RitikaxG/sandbox-lab/internal/runtime"
)

func main() {
	addr := flag.String("addr", "localhost:8080", "address to listen on")
	which := flag.String("runtime", "docker", "docker (Engine SDK, decision 001) or docker-cli (option A, for the flip)")
	flag.Parse()
	log.SetFlags(log.LstdFlags | log.Lmicroseconds) // L1 break 2 times the API's reaction to the millisecond

	var rt runtime.Runtime
	var err error
	switch *which {
	case "docker":
		rt, err = runtime.NewDocker()
	case "docker-cli":
		rt, err = runtime.NewDockerCLI()
	default:
		log.Fatalf("unknown -runtime %q", *which)
	}
	if err != nil {
		log.Fatalf("%s: %v", *which, err)
	}
	log.Printf("sandbox-api (%s) listening on %s", *which, *addr)
	log.Fatal(http.ListenAndServe(*addr, api.New(rt).Routes()))
}
