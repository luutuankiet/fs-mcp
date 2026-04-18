package server

import (
	"context"
	"fmt"
	"log"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/tools"
)

type Options struct {
	Name    string
	Version string
	Root    string
	HTTPAddr string
}

func Build(opts Options) *mcp.Server {
	s := mcp.NewServer(&mcp.Implementation{
		Name:    opts.Name,
		Version: opts.Version,
	}, nil)
	cfg := tools.Config{Root: opts.Root}
	tools.RegisterCreateDirectory(s, cfg)
	tools.RegisterReadFiles(s, cfg)
	tools.RegisterGrep(s, cfg)
	tools.RegisterJq(s, cfg)
	tools.RegisterYq(s, cfg)
	tools.RegisterRunCommand(s, cfg)
	tools.RegisterDirectoryTree(s, cfg)
	tools.RegisterEdit(s, cfg)
	tools.RegisterWrite(s, cfg)
	tools.RegisterListGsdLiteDirs(s, cfg)
	tools.RegisterDuckDB(s, cfg)
	return s
}

func Run(ctx context.Context, opts Options) error {
	s := Build(opts)
	if opts.HTTPAddr != "" {
		handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return s }, nil)
		log.Printf("fs-mcp HTTP listening on %s (portal root=%s)", opts.HTTPAddr, opts.Root)
		return http.ListenAndServe(opts.HTTPAddr, handler)
	}
	if err := s.Run(ctx, &mcp.StdioTransport{}); err != nil {
		return fmt.Errorf("stdio server: %w", err)
	}
	return nil
}
