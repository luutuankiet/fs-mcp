.PHONY: build run doctor test fmt clean

BIN := bin/fs-mcp

build:
	go build -o $(BIN) ./cmd/fs-mcp

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
