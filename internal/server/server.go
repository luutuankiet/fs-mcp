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

// schemaDecorator amends tools/list responses so every declared output schema
// also advertises the "cwd" property that resultDecorator injects into every
// structured result. Advertisement and injection live in the same file on
// purpose — a client that validates structuredContent against the advertised
// schema would otherwise see an undeclared extra key on every single call.
func schemaDecorator() func(mcp.MethodHandler) mcp.MethodHandler {
	return func(next mcp.MethodHandler) mcp.MethodHandler {
		return func(ctx context.Context, method string, req mcp.Request) (mcp.Result, error) {
			res, err := next(ctx, method, req)
			if ltr, ok := res.(*mcp.ListToolsResult); ok && ltr != nil {
				for i, t := range ltr.Tools {
					if amended, changed := addCwdToSchema(t.OutputSchema); changed {
						// Shallow-copy so the server's internal Tool (used for
						// output validation) is never mutated.
						tc := *t
						tc.OutputSchema = amended
						ltr.Tools[i] = &tc
					}
				}
			}
			return res, err
		}
	}
}

// addCwdToSchema returns schema with properties.cwd added. Handles any
// representation (json.RawMessage, *jsonschema.Schema, map) by round-tripping
// through JSON. Returns changed=false when there is nothing to amend: nil
// schema, a non-object schema, or cwd already declared.
func addCwdToSchema(schema any) (json.RawMessage, bool) {
	if schema == nil {
		return nil, false
	}
	raw, err := json.Marshal(schema)
	if err != nil {
		return nil, false
	}
	var obj map[string]any
	if err := json.Unmarshal(raw, &obj); err != nil {
		return nil, false
	}
	if t, _ := obj["type"].(string); t != "" && t != "object" {
		return nil, false
	}
	props, _ := obj["properties"].(map[string]any)
	if props == nil {
		props = map[string]any{}
	}
	if _, exists := props["cwd"]; exists {
		return nil, false
	}
	props["cwd"] = map[string]any{
		"type":        "string",
		"description": "Portal root the server resolves relative paths against (injected into every structured result).",
	}
	obj["properties"] = props
	out, err := json.Marshal(obj)
	if err != nil {
		return nil, false
	}
	return json.RawMessage(out), true
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
	s.AddReceivingMiddleware(schemaDecorator())
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
	tools.RegisterHq(s, cfg)
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
