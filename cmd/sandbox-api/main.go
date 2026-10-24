// sandbox-api is the lab's sandbox control plane (L0: Docker runtime, state in memory).
//
//	go run ./cmd/sandbox-api            # listens on localhost:8080
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
	flag.Parse()

	rt, err := runtime.NewDocker()
	if err != nil {
		log.Fatalf("docker: %v", err)
	}
	log.Printf("sandbox-api listening on %s", *addr)
	log.Fatal(http.ListenAndServe(*addr, api.New(rt).Routes()))
}
