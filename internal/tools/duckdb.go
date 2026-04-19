package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/luutuankiet/fs-mcp/internal/runtime"
)

// nanInfRe matches duckdb's bare NaN / Infinity / -Infinity JSON tokens
// (followed by a JSON delimiter so we don't rewrite quoted strings or
// column names that happen to spell those words).
var nanInfRe = regexp.MustCompile(`(-?Infinity|NaN)([,\]\}\s])`)

var duckdbOutputSchema = json.RawMessage(`{"type":"object","properties":{"results":{"type":"array","items":{}},"count":{"type":"integer"},"columns":{"type":"array","items":{"type":"string"}},"timed_out":{"type":"boolean"},"elapsed_ms":{"type":"integer"},"stderr":{"type":"string"}}}`)

type DuckDBInput struct {
	SQL        string `json:"sql" jsonschema:"SQL query. Supports read_csv_auto / read_parquet / read_json_auto for file-backed reads; COPY TO for export; DESCRIBE for schema. Multi-statement queries are allowed."`
	TimeoutSec int    `json:"timeout_sec,omitempty" jsonschema:"Timeout in seconds. Default 30."`
}

type DuckDBOutput struct {
	Results   []map[string]any `json:"results"`
	Count     int              `json:"count"`
	Columns   []string         `json:"columns,omitempty"`
	TimedOut  bool             `json:"timed_out"`
	ElapsedMs int64            `json:"elapsed_ms"`
	Stderr    string           `json:"stderr,omitempty"`
}

func duckdbTool(cfg Config) func(context.Context, *mcp.CallToolRequest, DuckDBInput) (*mcp.CallToolResult, DuckDBOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in DuckDBInput) (*mcp.CallToolResult, DuckDBOutput, error) {
		if strings.TrimSpace(in.SQL) == "" {
			return nil, DuckDBOutput{}, fmt.Errorf("sql is required")
		}
		timeout := time.Duration(in.TimeoutSec) * time.Second
		if timeout == 0 {
			timeout = 30 * time.Second
		}
		res := runtime.RunWithStdin(ctx, timeout, in.SQL, "duckdb", "-json")
		out := DuckDBOutput{
			Results:   []map[string]any{},
			TimedOut:  res.TimedOut,
			ElapsedMs: res.ElapsedMs,
			Stderr:    res.Stderr,
		}
		if res.TimedOut {
			return nil, out, nil
		}
		if res.ExitCode != 0 {
			return nil, out, fmt.Errorf("duckdb failed (%d): %s", res.ExitCode, strings.TrimSpace(res.Stderr))
		}
		body := strings.TrimSpace(res.Stdout)
		if body == "" {
			return nil, out, nil
		}
		// DuckDB CLI -json emits bare NaN/Infinity tokens which are not
		// valid JSON. Sub them to null before Unmarshal so downstream
		// clients don't choke.
		body = nanInfRe.ReplaceAllString(body, "null$2")
		if err := json.Unmarshal([]byte(body), &out.Results); err != nil {
			return nil, out, fmt.Errorf("duckdb json parse: %v — raw: %s", err, truncate(body, 400))
		}
		out.Count = len(out.Results)
		if len(out.Results) > 0 {
			for k := range out.Results[0] {
				out.Columns = append(out.Columns, k)
			}
		}
		return nil, out, nil
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

func RegisterDuckDB(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:         "query_duckdb",
		Description:  "Query tabular data via DuckDB SQL. Reads CSV / Parquet / JSON directly via read_csv_auto / read_parquet / read_json_auto — no import step. Supports GROUP BY, JOIN, window functions, CTE, DESCRIBE, COPY TO. Result size is agent-controlled via LIMIT.",
		OutputSchema: duckdbOutputSchema,
	}, duckdbTool(cfg))
}
