# Phase 4: Add jq and yq for querying large JSON and YAML files - Context

**Gathered:** 2026-01-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Add jq and yq command-line tools to enable agents to efficiently query large JSON and YAML files without reading entire content. This completes the pattern: grep for text search → jq/yq for structured data queries. Primary use case: exploring large structured files (dbt manifest.json, OpenAPI specs, package-lock.json) that would overflow agent context windows.

</domain>

<decisions>
## Implementation Decisions

### Dependency & Installation
- **Independent tools:** Check jq and yq separately at startup — jq missing only disables `query_json`, yq missing only disables `query_yaml`
- **Graceful degradation:** Server continues running if tools are missing (matches ripgrep pattern)
- **Platform-specific install:** Detect platform and show specific commands (brew/apt/dnf/choco) for both jq and yq
- **Error messages:** Match ripgrep pattern for consistency — return platform-specific install instructions when tool called but unavailable

### Query Interface Design
- **Two separate tools:** `query_json()` uses jq, `query_yaml()` uses yq — explicit and clear to agents
- **Parameters:** Path + query expression only — `query_json(file_path, jq_expression)`, `query_yaml(file_path, yq_expression)`
- **Single file queries:** One file per query call — simple and explicit, no glob patterns or multi-file support
- **Output format:** Compact JSON (one-line) for token efficiency — use jq `-c` flag, agents can parse it
- **Large file discovery:** Enhance `read_files` with `large_file_passthrough=False` (default) that blocks files >100k tokens and prompts agents to use query tools for JSON/YAML or set passthrough=True
- **Tool descriptions:** Combine syntax examples + workflow guidance optimized for weaker models (GPT-3.5, Gemini 2.0 Flash)

### Error Responses & Guidance
- **Invalid syntax:** Claude's discretion — determine clearest error messaging for agents
- **No results:** Explicit message 'Query returned no results' — distinguishes from errors
- **Timeout:** Configurable via parameter — `query_json(path, expr, timeout=30)` with reasonable default (Claude determines)

### Output Handling & Bounds
- **Result count limit:** 100 results max (matches grep pattern)
- **Truncation strategy:** Show first 100 results + message: 'Truncated. Showing 100 of N results. Refine query or use jq slicing: .items[100:200]'
- **Pagination approach:** Teach agents to use jq/yq slicing syntax (`.items[0:100]`, `.items[100:200]`) — tool description shows examples, truncation message suggests next slice
- **Token threshold for queries:** 50k tokens max (stricter than read_files' 100k) — prevents context rot for weaker models
- **Large result override:** Block by default if result >50k tokens, allow `large_result_passthrough=True` flag (matches read_files pattern)
- **Blocked result message:** Show warning prompting refinement or mention passthrough flag

### Claude's Discretion
- Exact tool description wording optimized for weak model comprehension
- Default timeout value (suggested 30s, but Claude determines based on typical file processing)
- Invalid syntax error translation (raw jq/yq errors vs simplified guidance)
- Large file warning message phrasing in `read_files` enhancement
- Query refinement suggestion examples in truncation messages

</decisions>

<specifics>
## Specific Ideas

- **Use case reference:** "I need agent to help me devise a jq query to extract OpenAPI swagger JSON endpoints for scripting — swagger might be really big, agent breaks it down with multiple targeted queries"
- **Weak model context awareness:** "Consider conversation history filling 50% of context window already, which degrades reasoning for weaker models"
- **Discovery mechanism:** Agents don't know file is huge until they try to read it — `read_files` enhancement becomes natural discovery point
- **Token efficiency priority:** Compact output saves tokens; agents can parse one-line JSON effectively
- **Iterative query pattern:** Large results prompt agents to refine queries and slice data, not fetch entire datasets

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-add-jq-and-yq-for-querying-large-json-and-yaml-files*
*Context gathered: 2026-01-26*
