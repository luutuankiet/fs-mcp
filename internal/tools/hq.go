package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"golang.org/x/net/html"
)

const hqMaxBytes = 50 << 20 // 50MB guard, mirrors grep --max-filesize

var hqDefaultStrip = []string{"script", "style", "svg", "noscript", "iframe", "head", "#comment"}

var hqAllowedModes = map[string]bool{
	"text": true, "attr": true, "html": true, "outer": true, "raw": true,
	"count": true, "json": true, "outline": true, "table": true,
}

var hqOutputSchema = json.RawMessage(`{"type":"object","properties":{"results":{"type":"array","items":{}},"count":{"type":"integer"},"mode":{"type":"string"},"truncated":{"type":"boolean"},"elapsed_ms":{"type":"integer"}}}`)

type HqInput struct {
	File     string   `json:"file" jsonschema:"Path to the HTML file."`
	Selector string   `json:"selector,omitempty" jsonschema:"CSS selector (cascadia syntax). Empty selector returns an outline of <body>."`
	Mode     string   `json:"mode,omitempty" jsonschema:"text|attr|html|outer|raw|count|json|outline|table. Default text (outline when selector empty). raw = matched outer HTML with no strip and no whitespace-normalize (escape hatch)."`
	Attr     string   `json:"attr,omitempty" jsonschema:"Attribute name for mode=attr. Use '*' for all attributes, or a comma-separated list for several."`
	Strip    []string `json:"strip,omitempty" jsonschema:"Selectors removed before extraction. Omit for default (script,style,svg,noscript,iframe,head,#comment); pass [] to disable stripping entirely."`
	Limit    *int     `json:"limit,omitempty" jsonschema:"Max matches returned. Omit for default 50; 0 or negative = unlimited. Sets truncated=true when exceeded."`
	MaxDepth int      `json:"max_depth,omitempty" jsonschema:"Outline recursion depth (default 3)."`
}

type HqOutput struct {
	Results   []any  `json:"results"`
	Count     int    `json:"count"`
	Mode      string `json:"mode"`
	Truncated bool   `json:"truncated,omitempty"`
	ElapsedMs int64  `json:"elapsed_ms"`
}

func hqTool(cfg Config) func(context.Context, *mcp.CallToolRequest, HqInput) (*mcp.CallToolResult, HqOutput, error) {
	return func(ctx context.Context, req *mcp.CallToolRequest, in HqInput) (*mcp.CallToolResult, HqOutput, error) {
		start := time.Now()
		p, err := cfg.ResolvePath(in.File)
		if err != nil {
			return nil, HqOutput{}, err
		}
		fi, err := os.Stat(p)
		if err != nil {
			return nil, HqOutput{}, err
		}
		if fi.Size() > hqMaxBytes {
			return nil, HqOutput{}, fmt.Errorf("file too large: %d bytes (max %d)", fi.Size(), hqMaxBytes)
		}
		f, err := os.Open(p)
		if err != nil {
			return nil, HqOutput{}, err
		}
		defer f.Close()
		doc, err := goquery.NewDocumentFromReader(f)
		if err != nil {
			return nil, HqOutput{}, err
		}

		mode := in.Mode
		if mode == "" {
			if in.Selector == "" {
				mode = "outline"
			} else {
				mode = "text"
			}
		}
		if !hqAllowedModes[mode] {
			return nil, HqOutput{}, fmt.Errorf("invalid mode %q (allowed: text,attr,html,outer,raw,count,json,outline,table)", mode)
		}

		// Noise removal. Skipped entirely for raw mode (escape hatch). strip:[] disables it too.
		if mode != "raw" {
			strip := in.Strip
			if strip == nil {
				strip = hqDefaultStrip
			}
			for _, s := range strip {
				if s == "#comment" {
					hqRemoveComments(doc.Selection)
					continue
				}
				doc.Find(s).Remove()
			}
		}

		var sel *goquery.Selection
		if in.Selector == "" {
			sel = doc.Find("body")
			if sel.Length() == 0 {
				sel = doc.Selection
			}
		} else {
			sel = doc.Find(in.Selector)
		}

		unlimited := false
		max := 50
		if in.Limit != nil {
			if *in.Limit <= 0 {
				unlimited = true
			} else {
				max = *in.Limit
			}
		}

		out := HqOutput{Mode: mode, Results: []any{}}

		switch mode {
		case "count":
			out.Results = []any{sel.Length()}
		case "outline":
			depth := in.MaxDepth
			if depth == 0 {
				depth = 3
			}
			var nodes []any
			sel.Each(func(i int, s *goquery.Selection) {
				for _, n := range s.Nodes {
					hqWalkOutline(n, 0, depth, &nodes)
				}
			})
			if !unlimited && len(nodes) > max {
				nodes = nodes[:max]
				out.Truncated = true
			}
			out.Results = nodes
		case "table":
			sel.EachWithBreak(func(i int, s *goquery.Selection) bool {
				if !unlimited && len(out.Results) >= max {
					out.Truncated = true
					return false
				}
				out.Results = append(out.Results, hqTableToMap(s))
				return true
			})
		default:
			sel.EachWithBreak(func(i int, s *goquery.Selection) bool {
				if !unlimited && len(out.Results) >= max {
					out.Truncated = true
					return false
				}
				if v, ok := hqExtract(s, mode, in.Attr); ok {
					out.Results = append(out.Results, v)
				}
				return true
			})
		}

		out.Count = len(out.Results)
		out.ElapsedMs = time.Since(start).Milliseconds()
		return nil, out, nil
	}
}

func hqExtract(s *goquery.Selection, mode, attr string) (any, bool) {
	switch mode {
	case "attr":
		return hqAttr(s, attr), true
	case "html":
		h, err := s.Html()
		if err != nil {
			return nil, false
		}
		return h, true
	case "outer", "raw":
		h, err := goquery.OuterHtml(s)
		if err != nil {
			return nil, false
		}
		if mode == "raw" {
			return h, true
		}
		return h, true
	case "json":
		return hqNodeJSON(s), true
	default: // text
		return hqNormalizeWS(s.Text()), true
	}
}

// hqAttr supports a single name, '*' (all attributes), or a comma-separated list.
func hqAttr(s *goquery.Selection, attr string) any {
	if len(s.Nodes) == 0 || attr == "" {
		return nil
	}
	node := s.Nodes[0]
	if attr == "*" {
		m := map[string]string{}
		for _, a := range node.Attr {
			m[a.Key] = a.Val
		}
		return m
	}
	if strings.Contains(attr, ",") {
		m := map[string]string{}
		for _, name := range strings.Split(attr, ",") {
			name = strings.TrimSpace(name)
			if v, ok := s.Attr(name); ok {
				m[name] = v
			}
		}
		return m
	}
	v, _ := s.Attr(attr)
	return v
}

func hqNodeJSON(s *goquery.Selection) map[string]any {
	m := map[string]any{}
	if len(s.Nodes) == 0 {
		return m
	}
	n := s.Nodes[0]
	m["tag"] = n.Data
	if id, ok := s.Attr("id"); ok {
		m["id"] = id
	}
	if cls, ok := s.Attr("class"); ok {
		m["classes"] = strings.Fields(cls)
	}
	attrs := map[string]string{}
	for _, a := range n.Attr {
		attrs[a.Key] = a.Val
	}
	m["attrs"] = attrs
	m["text"] = hqNormalizeWS(s.Text())
	m["n_children"] = s.Children().Length()
	return m
}

func hqWalkOutline(n *html.Node, depth, maxDepth int, out *[]any) {
	if n.Type != html.ElementNode {
		return
	}
	var id string
	var classes []string
	for _, a := range n.Attr {
		switch a.Key {
		case "id":
			id = a.Val
		case "class":
			classes = strings.Fields(a.Val)
		}
	}
	nChildren := 0
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode {
			nChildren++
		}
	}
	entry := map[string]any{
		"depth":      depth,
		"path":       hqNodePath(n, id, classes),
		"tag":        n.Data,
		"n_children": nChildren,
		"text_len":   len(strings.TrimSpace(hqNodeText(n))),
	}
	if id != "" {
		entry["id"] = id
	}
	if len(classes) > 0 {
		entry["classes"] = classes
	}
	*out = append(*out, entry)
	if depth >= maxDepth {
		return
	}
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode {
			hqWalkOutline(c, depth+1, maxDepth, out)
		}
	}
}

func hqNodePath(n *html.Node, id string, classes []string) string {
	p := n.Data
	if id != "" {
		p += "#" + id
	}
	for _, c := range classes {
		p += "." + c
	}
	return p
}

func hqNodeText(n *html.Node) string {
	var sb strings.Builder
	var f func(*html.Node)
	f = func(nd *html.Node) {
		if nd.Type == html.TextNode {
			sb.WriteString(nd.Data)
		}
		for c := nd.FirstChild; c != nil; c = c.NextSibling {
			f(c)
		}
	}
	f(n)
	return sb.String()
}

func hqTableToMap(s *goquery.Selection) map[string]any {
	headers := []string{}
	s.Find("th").Each(func(i int, th *goquery.Selection) {
		headers = append(headers, hqNormalizeWS(th.Text()))
	})
	rows := [][]string{}
	s.Find("tr").Each(func(i int, tr *goquery.Selection) {
		cells := []string{}
		tr.Find("td").Each(func(j int, td *goquery.Selection) {
			cells = append(cells, hqNormalizeWS(td.Text()))
		})
		if len(cells) > 0 {
			rows = append(rows, cells)
		}
	})
	return map[string]any{"headers": headers, "rows": rows}
}

func hqNormalizeWS(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

// hqRemoveComments strips comment nodes from the tree (cascadia cannot select them).
func hqRemoveComments(sel *goquery.Selection) {
	for _, root := range sel.Nodes {
		var toRemove []*html.Node
		var walk func(*html.Node)
		walk = func(n *html.Node) {
			for c := n.FirstChild; c != nil; c = c.NextSibling {
				if c.Type == html.CommentNode {
					toRemove = append(toRemove, c)
				}
				walk(c)
			}
		}
		walk(root)
		for _, c := range toRemove {
			if c.Parent != nil {
				c.Parent.RemoveChild(c)
			}
		}
	}
}

func RegisterHq(s *mcp.Server, cfg Config) {
	mcp.AddTool(s, &mcp.Tool{
		Name:         "hq",
		Description:  "Query and slice an HTML file with CSS selectors (in-process goquery). Start with mode=outline (no selector) to map page structure without dumping HTML, then drill with selector + text/attr/html/outer/json/table. raw mode returns unmodified outer HTML (escape hatch); strip:[] disables noise removal. Sibling of jq/yq.",
		OutputSchema: hqOutputSchema,
	}, hqTool(cfg))
}
