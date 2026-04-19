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

// maxResultSizeChars is the Anthropic-specific hint that asks the client to
// allow up to ~500K characters of tool output before truncating. Without it,
// large reads/grep responses get clipped at the client's lower default.
const maxResultSizeChars = 500000

// resultDecorator runs after every tool call and tags _meta with two hints:
//
//   - anthropic/maxResultSizeChars: 500000 — asks the client to allow large
//     payloads before truncating (otherwise the default cap clips big reads).
//   - fs-mcp/portal_root: "<root>" — tells the agent what directory their
//     relative paths resolve against. Lives in _meta so it stays out of the
//     content[] / structuredContent body the agent reads as actual data.
func resultDecorator(portalRoot string) func(mcp.MethodHandler) mcp.MethodHandler {
	return func(next mcp.MethodHandler) mcp.MethodHandler {
		return func(ctx context.Context, method string, req mcp.Request) (mcp.Result, error) {
			res, err := next(ctx, method, req)
			if ctr, ok := res.(*mcp.CallToolResult); ok && ctr != nil {
				if ctr.Meta == nil {
					ctr.Meta = mcp.Meta{}
				}
				ctr.Meta["anthropic/maxResultSizeChars"] = maxResultSizeChars
				ctr.Meta["fs-mcp/portal_root"] = portalRoot
			}
			return res, err
		}
	}
}

func Build(opts Options) *mcp.Server {
	s := mcp.NewServer(&mcp.Implementation{
		Name:    opts.Name,
		Version: opts.Version,
	}, nil)
	s.AddReceivingMiddleware(resultDecorator(opts.Root))
	cfg := tools.Config{Root: opts.Root}
	tools.RegisterCreateDirectory(s, cfg)
	tools.RegisterReadFiles(s, cfg)
	tools.RegisterGrep(s, cfg)
	tools.RegisterJq(s, cfg)
	tools.RegisterYq(s, cfg)
	tools.RegisterRunCommand(s, cfg)
	tools.RegisterDirectoryTree(s, cfg)
	tools.RegisterEdit(s, cfg)
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
