# Architecture

*Mapped: 2026-01-29 | Updated: 2026-02-16*

## Project Structure Overview

| Directory | Purpose |
|-----------|---------|
| `src/fs_mcp/` | Core package: CLI, MCP Server, Tools, Schema Compatibility, UI |
| `scripts/schema_compat/` | CLI tooling for schema inspection and Gemini compatibility testing |
| `tests/` | Pytest suite (server, edit tool, schema compatibility) |
| `gsd-lite/` | Task tracking logs (WORK.md) and templates |
| `docs/` | User documentation and maintenance guides |
| `.planning/` | Historic docs and planning artifacts |

*Key Files:*
- `src/fs_mcp/server.py`: **Core Logic.** Defines all MCP tools, path validation, and dependency checks.
- `src/fs_mcp/gemini_compat.py`: **Schema Compatibility.** Transforms Pydantic schemas to Gemini-compatible format (dereferences `$ref`, removes forbidden keys).
- `src/fs_mcp/edit_tool.py`: **Editing Logic.** Implements `propose_and_review` workflow.
- `src/fs_mcp/web_ui.py`: **Interactive UI.** Streamlit dashboard for testing tools.
- `src/fs_mcp/gsd_lite_analyzer.py`: **Analysis Logic.** Parses GSD logs for signals.

## Tech Stack

- **Runtime:** Python 3.10+ (managed via `uv`)
- **Core Framework:** `fastmcp` (MCP protocol), `pydantic` (validation)
- **Schema Compatibility:** `jsonref` (dereference `$ref`), `google-genai` (Gemini transforms)
- **Interactive UI:** `streamlit`, `streamlit-js-eval`
- **Critical Binaries:**
  - `ripgrep` (`rg`): **Essential.** Powers `grep_content` for fast regex search.
  - `jq` / `yq`: **Optional.** Powers `query_json` / `query_yaml` for structured data exploration.
  - `code` (VS Code): **Optional.** Powers diff view in `propose_and_review`.

## Data Flow

**1. Discovery & Reading (The "Grep -> Hint -> Read" Pattern)**
Designed to minimize token usage for agents:
1. Agent calls `grep_content(pattern)` -> Server runs `rg` -> Returns matches + **Section Hints** (e.g., "function ends at L42").
2. Agent calls `read_files(start_line, read_to_next_pattern)` -> Server reads specific block -> Returns focused context.

**2. Structured Querying**
For large data files (>2000 tokens):
1. Agent calls `query_json(query)` -> Server writes query to temp file -> Runs `jq -f temp_file` -> Returns bounded results (max 100).
*Prevents shell injection and context overflow.*

**3. Safe Editing (Human-in-the-Loop)**
1. Agent calls `propose_and_review(edits)` -> Server creates `future_file` -> Launches VS Code Diff (if available).
2. Human reviews/modifies -> Server waits for approval signal -> Commits changes to original file.

**4. Schema Compatibility Layer (New)**

All tool schemas are transformed at registration time to ensure Gemini compatibility:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SCHEMA TRANSFORMATION PIPELINE                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Pydantic Model                                                              │
│       │                                                                      │
│       ▼                                                                      │
│  Raw JSON Schema (contains $ref, $defs, anyOf, title, default, etc.)        │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  gemini_compat.make_gemini_compatible()                             │    │
│  │  1. Dereference $ref using jsonref                                  │    │
│  │  2. Remove $defs, $id, $schema                                      │    │
│  │  3. Convert anyOf[T, null] → {type: T, nullable: true}              │    │
│  │  4. Remove forbidden keys: title, default, propertyOrdering         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│       │                                                                      │
│       ▼                                                                      │
│  Gemini-Compatible Schema (works with Claude, Gemini, GPT)                  │
│       │                                                                      │
│       ▼                                                                      │
│  FastMCP Tool Registry                                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why unconditional transformation:** Gemini is the "lowest common denominator" — if a schema works with Gemini, it works everywhere. This eliminates provider-specific bugs without requiring user configuration.

**Reference:** LOG-001 (root cause), LOG-002 (22 transformation patterns), LOG-003 (implementation plan)

## Entry Points

Start reading here:

- `src/fs_mcp/__main__.py` - **CLI Entry Point.** Handles args, spawns HTTP server or UI.
- `src/fs_mcp/server.py` - **Tool Definitions.** The registry of all available MCP tools (`@mcp.tool`).
- `src/fs_mcp/gemini_compat.py` - **Schema Compatibility.** Transform logic for Gemini-compatible schemas.
- `src/fs_mcp/web_ui.py` - **UI Entry Point.** How the Streamlit dashboard initializes the server.
- `scripts/schema_compat/cli.py` - **Compatibility CLI.** Run `python -m scripts.schema_compat check` to validate schemas.
- `README.md` - Setup instructions and usage examples.

## Testing

| Test File | Purpose |
|-----------|---------|
| `tests/test_server.py` | Core tool functionality |
| `tests/test_edit_tool.py` | Edit/review workflow |
| `tests/test_tool_arg_descriptions.py` | Schema description completeness |
| `tests/test_gemini_schema_compat.py` | **CI guard:** Fails if any tool emits Gemini-incompatible schema |