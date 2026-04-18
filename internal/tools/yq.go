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

var yqOutputSchema = json.RawMessage(`{"type":"object","properties":{"results":{"type":"array","items":{}},"count":{"type":"integer"},"timed_out":{"type":"boolean"},"elapsed_ms":{"type":"integer"},"stderr":{"type":"string"}}}`)

type YqInput struct {
	File        string `json:"file" jsonschema:"Path to the structured data file."`
	Expression  string `json:"expression" jsonschema:"yq expression (jq-like syntax)."`
	InputFormat string `json:"input_format,omitempty" jsonschema:"Input format: yaml (default), json, xml, csv, tsv, toml, props, ini, hcl."`
	TimeoutSec  int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
}

type YqOutput struct {
	Results   []any  `json:"results"`
	Count     int    `json:"count"`
	TimedOut  bool   `json:"timed_out"`
	ElapsedMs int64  `json:"elapsed_ms"`
	Stderr    string `json:"stderr,omitempty"`
}

func yqTool(cfg Config) func(context.Context, *mcp.CallToolRequest, YqInput) (*mcp.CallToolResult, YqOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in YqInput) (*mcp.CallToolResult, YqOutput, error) {
		p, err := cfg.ResolvePath(in.File)
		if err != nil {
			return nil, YqOutput{}, err
		}
		tmp, err := os.CreateTemp("", "fs-mcp-yq-*.yq")
		if err != nil {
			return nil, YqOutput{}, err
		}
		defer os.Remove(tmp.Name())
		if _, err := tmp.WriteString(in.Expression); err != nil {
			return nil, YqOutput{}, err
		}
		tmp.Close()
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 30 * time.Second
		}
		args := []string{"-o", "json", "-I", "0"}
		if in.InputFormat != "" && in.InputFormat != "yaml" {
			args = append(args, "-p", in.InputFormat)
		}
		args = append(args, "--from-file", tmp.Name(), p)
		res := runtime.Run(ctx, timeout, "yq", args...)
		out := YqOutput{TimedOut: res.TimedOut, ElapsedMs: res.ElapsedMs, Stderr: res.Stderr}
		if res.TimedOut {
			return nil, out, nil
		}
		if res.ExitCode != 0 {
			return nil, out, fmt.Errorf("yq failed (%d): %s", res.ExitCode, strings.TrimSpace(res.Stderr))
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

func RegisterYq(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:         "yq",
		Description:  "Query a YAML/JSON/XML/CSV/TSV/TOML/INI/HCL file using mikefarah's yq. Returns all results (no 100-line cap).",
		OutputSchema: yqOutputSchema,
	}, yqTool(cfg))
}
