.PHONY: build run doctor test fmt clean

BIN := bin/fs-mcp

# Stamp version from `git describe`; auto-update treats anything ≠ "dev" as a
# real version, so a stamped local build participates in the upgrade ladder.
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS := -s -w -X main.version=$(VERSION)

build:
	go build -ldflags="$(LDFLAGS)" -o $(BIN) ./cmd/fs-mcp

run: build
	./$(BIN)

doctor: build
	./$(BIN) --doctor

test:
	go test ./...

fmt:
	go fmt ./...
	go vet ./...

clean:
	rm -rf bin/ dist/

release-snapshot:
	goreleaser release --snapshot --clean
