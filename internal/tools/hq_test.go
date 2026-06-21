package tools

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const hqFixture = `<!DOCTYPE html>
<html>
<head><title>T</title><style>.x{color:red}</style></head>
<body>
<!-- a comment node -->
<h1>Hello   World</h1>
<div id="main" class="container box">
  <script>var z = 1;</script>
  <ul>
    <li>one</li>
    <li>two</li>
    <li>three</li>
  </ul>
  <a href="https://example.com" data-id="42">link</a>
</div>
<table>
  <tr><th>Name</th><th>Age</th></tr>
  <tr><td>Alice</td><td>30</td></tr>
  <tr><td>Bob</td><td>25</td></tr>
</table>
</body>
</html>`

func hqWriteFixture(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "f.html"), []byte(hqFixture), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func hqRun(t *testing.T, root string, in HqInput) HqOutput {
	t.Helper()
	_, out, err := hqTool(Config{Root: root})(context.Background(), nil, in)
	if err != nil {
		t.Fatalf("hqTool(%+v) error: %v", in, err)
	}
	return out
}

func intPtr(i int) *int { return &i }

func TestHqText(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "h1", Mode: "text"})
	if out.Count != 1 || out.Results[0] != "Hello World" {
		t.Fatalf("text: got %#v", out.Results)
	}
}

func TestHqCount(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "li", Mode: "count"})
	if out.Results[0] != 3 {
		t.Fatalf("count: got %#v", out.Results)
	}
}

func TestHqAttrSingle(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "a", Mode: "attr", Attr: "href"})
	if out.Results[0] != "https://example.com" {
		t.Fatalf("attr: got %#v", out.Results)
	}
}

func TestHqAttrAll(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "a", Mode: "attr", Attr: "*"})
	m, ok := out.Results[0].(map[string]string)
	if !ok || m["href"] != "https://example.com" || m["data-id"] != "42" {
		t.Fatalf("attr*: got %#v", out.Results[0])
	}
}

func TestHqAttrList(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "a", Mode: "attr", Attr: "href,data-id"})
	m, ok := out.Results[0].(map[string]string)
	if !ok || len(m) != 2 || m["data-id"] != "42" {
		t.Fatalf("attrList: got %#v", out.Results[0])
	}
}

func TestHqJSON(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "#main", Mode: "json"})
	m, ok := out.Results[0].(map[string]any)
	if !ok || m["tag"] != "div" {
		t.Fatalf("json: got %#v", out.Results[0])
	}
	cls, _ := m["classes"].([]string)
	if len(cls) != 2 || cls[0] != "container" {
		t.Fatalf("json classes: got %#v", m["classes"])
	}
}

func TestHqTable(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "table", Mode: "table"})
	m := out.Results[0].(map[string]any)
	headers := m["headers"].([]string)
	rows := m["rows"].([][]string)
	if len(headers) != 2 || headers[0] != "Name" {
		t.Fatalf("table headers: got %#v", headers)
	}
	if len(rows) != 2 || rows[0][0] != "Alice" || rows[1][1] != "25" {
		t.Fatalf("table rows: got %#v", rows)
	}
}

func TestHqOutlineDefault(t *testing.T) {
	dir := hqWriteFixture(t)
	// No selector + no mode => outline of <body>.
	out := hqRun(t, dir, HqInput{File: "f.html"})
	if out.Mode != "outline" {
		t.Fatalf("expected outline mode, got %q", out.Mode)
	}
	foundMain := false
	for _, r := range out.Results {
		m := r.(map[string]any)
		if m["tag"] == "script" {
			t.Fatalf("outline leaked stripped <script>: %#v", m)
		}
		if m["id"] == "main" {
			foundMain = true
		}
	}
	if !foundMain {
		t.Fatalf("outline missing div#main: %#v", out.Results)
	}
}

func TestHqRawBypassesStrip(t *testing.T) {
	dir := hqWriteFixture(t)
	// raw must NOT strip the inner <script>.
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "#main", Mode: "raw"})
	if !strings.Contains(out.Results[0].(string), "var z = 1") {
		t.Fatalf("raw should preserve script, got %#v", out.Results[0])
	}
}

func TestHqDefaultStripsScript(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "#main", Mode: "text"})
	if strings.Contains(out.Results[0].(string), "var z") {
		t.Fatalf("default strip should remove script text, got %#v", out.Results[0])
	}
}

func TestHqStripDisabled(t *testing.T) {
	dir := hqWriteFixture(t)
	// strip:[] (non-nil empty) disables noise removal => script text survives.
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "#main", Mode: "text", Strip: []string{}})
	if !strings.Contains(out.Results[0].(string), "var z") {
		t.Fatalf("strip:[] should keep script text, got %#v", out.Results[0])
	}
}

func TestHqLimitTruncates(t *testing.T) {
	dir := hqWriteFixture(t)
	out := hqRun(t, dir, HqInput{File: "f.html", Selector: "li", Mode: "text", Limit: intPtr(2)})
	if out.Count != 2 || !out.Truncated {
		t.Fatalf("limit: count=%d truncated=%v", out.Count, out.Truncated)
	}
}

// TestHqRealPageSmoke runs every mode against a real noisy page when
// HQ_SMOKE_FILE points at one (curl a page to disk, then set the env var).
// Skipped otherwise so it never breaks offline/CI runs.
func TestHqRealPageSmoke(t *testing.T) {
	path := os.Getenv("HQ_SMOKE_FILE")
	if path == "" {
		t.Skip("set HQ_SMOKE_FILE to a real HTML file to run the smoke test")
	}
	dir := filepath.Dir(path)
	file := filepath.Base(path)
	for _, mode := range []string{"outline", "text", "json", "count", "table"} {
		sel := ""
		if mode != "outline" {
			sel = "a"
		}
		if mode == "table" {
			sel = "table"
		}
		out := hqRun(t, dir, HqInput{File: file, Selector: sel, Mode: mode})
		t.Logf("mode=%-8s count=%-4d truncated=%v elapsed_ms=%d", mode, out.Count, out.Truncated, out.ElapsedMs)
	}
}

func TestHqInvalidMode(t *testing.T) {
	dir := hqWriteFixture(t)
	_, _, err := hqTool(Config{Root: dir})(context.Background(), nil, HqInput{File: "f.html", Selector: "a", Mode: "bogus"})
	if err == nil {
		t.Fatal("expected error for invalid mode")
	}
}
