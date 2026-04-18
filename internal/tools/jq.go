package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

var jqOutputSchema = json.RawMessage(`{"type":"object","properties":{"results":{"type":"array","items":{}},"count":{"type":"integer"},"timed_out":{"type":"boolean"},"elapsed_ms":{"type":"integer"},"stderr":{"type":"string"}}}`)

type JqInput struct {
	File       string `json:"file" jsonschema:"Path to JSON file."`
	Expression string `json:"expression" jsonschema:"jq expression (e.g. '.items[] | select(.active)')."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
}

type JqOutput struct {
	Results   []any  `json:"results"`
	Count     int    `json:"count"`
	TimedOut  bool   `json:"timed_out"`
	ElapsedMs int64  `json:"elapsed_ms"`
	Stderr    string `json:"stderr,omitempty"`
}

func jqTool(cfg Config) func(context.Context, *mcp.CallToolRequest, JqInput) (*mcp.CallToolResult, JqOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in JqInput) (*mcp.CallToolResult, JqOutput, error) {
		p, err := cfg.ResolvePath(in.File)
		if err != nil {
			return nil, JqOutput{}, err
		}
		tmp, err := os.CreateTemp("", "fs-mcp-jq-*.jq")
		if err != nil {
			return nil, JqOutput{}, err
		}
		defer os.Remove(tmp.Name())
		if _, err := tmp.WriteString(in.Expression); err != nil {
			return nil, JqOutput{}, err
		}
		tmp.Close()
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 30 * time.Second
		}
		res := runtime.Run(ctx, timeout, "jq", "-c", "-f", tmp.Name(), p)
		out := JqOutput{TimedOut: res.TimedOut, ElapsedMs: res.ElapsedMs, Stderr: res.Stderr}
		if res.TimedOut {
			return nil, out, nil
		}
		if res.ExitCode != 0 {
			return nil, out, fmt.Errorf("jq failed (%d): %s", res.ExitCode, strings.TrimSpace(res.Stderr))
		}
		for _, line := range strings.Split(res.Stdout, "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var v any
			if err := json.Unmarshal([]byte(line), &v); err == nil {
				out.Results = append(out.Results, v)
			}
		}
		out.Count = len(out.Results)
		return nil, out, nil
	}
}

func RegisterJq(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:         "jq",
		Description:  "Query a JSON file using jq. Returns all results as a JSON array (no 100-line cap).",
		OutputSchema: jqOutputSchema,
	}, jqTool(cfg))
}
