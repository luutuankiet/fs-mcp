package server

import (
	"context"
	"encoding/json"
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

// resultDecorator runs after every tool call and adds two pieces of metadata:
//
//  1. _meta.anthropic/maxResultSizeChars=500000 — protocol-level hint for
//     Claude clients to allow large payloads before truncating. The model
//     never sees this; the client uses it to decide when to clip output.
//  2. structuredContent.cwd="<portal-root>" — model-visible hint so the
//     agent always knows what directory its relative paths resolve against.
//     Injected as a top-level key in the structured payload AND mirrored
//     into the auto-generated TextContent block, since most clients render
//     content[] for the model rather than structuredContent.
func resultDecorator(portalRoot string) func(mcp.MethodHandler) mcp.MethodHandler {
	return func(next mcp.MethodHandler) mcp.MethodHandler {
		return func(ctx context.Context, method string, req mcp.Request) (mcp.Result, error) {
			res, err := next(ctx, method, req)
			if ctr, ok := res.(*mcp.CallToolResult); ok && ctr != nil {
				if ctr.Meta == nil {
					ctr.Meta = mcp.Meta{}
				}
				ctr.Meta["anthropic/maxResultSizeChars"] = maxResultSizeChars
				injectCwd(ctr, portalRoot)
			}
			return res, err
		}
	}
}

// injectCwd adds {"cwd": portalRoot} as a top-level key in structuredContent
// and updates any matching TextContent mirror. No-ops cleanly if the result
// has no structured payload (error results that only carry text, etc.).
func injectCwd(ctr *mcp.CallToolResult, portalRoot string) {
	raw, ok := ctr.StructuredContent.(json.RawMessage)
	if !ok || len(raw) == 0 {
		return
	}
	var obj map[string]any
	if err := json.Unmarshal(raw, &obj); err != nil {
		return
	}
	obj["cwd"] = portalRoot
	newRaw, err := json.Marshal(obj)
	if err != nil {
		return
	}
	oldStr := string(raw)
	ctr.StructuredContent = json.RawMessage(newRaw)
	for i, c := range ctr.Content {
		if tc, ok := c.(*mcp.TextContent); ok && tc.Text == oldStr {
			ctr.Content[i] = &mcp.TextContent{Text: string(newRaw)}
			return
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
