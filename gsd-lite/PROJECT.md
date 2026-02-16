# fs-mcp

*Initialized: 2026-02-16*

## What This Is

A **universal, provider-agnostic** filesystem MCP server designed for AI agents (Claude, Gemini, GPT, etc.). It acts as a "smart driver" for remote codebases, providing efficient access patterns (grep → read), structured data querying, and safe, human-in-the-loop editing workflows with zero configuration.

**Key differentiator:** fs-mcp emits **Gemini-compatible schemas by default**, ensuring tools work correctly across all major AI providers without requiring provider-specific workarounds in user code.

## Core Value

**Agent-First Efficiency, Safety & Compatibility.**

1. **Efficiency:** Tools minimize token usage (90% reduction on errors) and maximize context quality
2. **Safety:** Human-in-the-loop editing prevents accidental overwrites
3. **Compatibility:** Schemas are transformed at runtime to work with the lowest common denominator (Gemini), ensuring universal provider support

## Success Criteria

Project succeeds when:

**Efficiency & Safety (Existing):**
- [x] **Smart Discovery:** `grep_content` provides section hints (e.g., "function ends at L42") to guide targeted reading.
- [x] **Logic-Aware Reading:** `read_files` supports `read_to_next_pattern` to extract complete code blocks without manual line counting.
- [x] **Token-Efficient Errors:** `propose_and_review` returns fuzzy match suggestions instead of full file dumps on error (saving ~90% tokens).
- [x] **Safe Editing:** Preventing accidental overwrites by requiring `OVERWRITE_FILE` sentinel for full replacements.
- [x] **Structured Exploration:** `query_json` and `query_yaml` allow deep inspection of data files without loading entire contents.
- [x] **GSD-Lite Integration:** `analyze_gsd_work_log` provides semantic analysis of project logs.
- [x] **Zero Setup:** Works immediately with `uvx fs-mcp`.

**Provider Compatibility (Complete — LOG-006):**
- [x] **Universal Schema Compatibility:** All tool schemas work with Claude, Gemini, and GPT without modification.
- [x] **Automatic $ref Dereferencing:** Nested Pydantic models are inlined at registration time (Gemini doesn't support `$ref`).
- [x] **Schema Validation CI:** Automated tests catch Gemini-incompatible patterns before release.
- [x] **Compatibility Tooling:** `scripts/schema_compat/` provides CLI for schema inspection and gap detection.

## Context

**Evolution:**
Originally conceived as a simple remote filesystem bridge, `fs-mcp` has evolved into a sophisticated "agent runtime" layer. It addresses key limitations of LLMs: limited context windows, hallucinated line numbers, and "blind" file overwriting.

**2026-02 Pivot: Provider Compatibility**
Discovery: Gemini silently corrupts tool schemas containing JSON Schema `$ref` references (see LOG-001). This causes nested objects like `FileReadRequest` to degrade to `STRING`, breaking tool calls. Rather than require users to handle this, fs-mcp now transforms all schemas to be Gemini-compatible at registration time — the "lowest common denominator" approach ensures universal compatibility.

**Key Technical Shifts:**
- **From Raw Access to Smart Layers:** Instead of just `read()`, we offer `read_to_next_pattern()`. Instead of `grep()`, we offer "grep with section hints".
- **From Dumps to Hints:** Error messages now use `difflib` to suggest corrections rather than dumping 5000 lines of context.
- **From Text to Structure:** Specialized tools for JSON/YAML and GSD-Lite logs treat files as structured data, not just text blobs.
- **From Provider-Specific to Universal:** Schemas are transformed at runtime using `jsonref` and Gemini SDK transforms to ensure compatibility with all providers.

**User Needs:**
- **Speed:** "One-command" access to any server.
- **Cost/Token Efficiency:** Don't waste 50k tokens reading a file just to fix one line.
- **Safety:** Don't let a hallucinating agent wipe `main.py`.
- **Just Works:** Same MCP server works with Claude, Gemini, GPT — no config needed.

## Constraints

- **Dependencies:** 
  - `ripgrep` — external binary for fast grep (required)
  - `jsonref` — Python library for `$ref` dereferencing (required)
  - `google-genai` — Python library for Gemini schema transforms (required)
- **Token Budget:** Tool outputs must be strictly bounded (e.g., max 100 grep matches, truncated error previews).
- **Safety Protocol:** Full file overwrites require explicit `OVERWRITE_FILE` sentinel; blank string replacements on non-empty files are blocked.
- **Transport:** Must work over standard HTTP/SSE for broad compatibility.
- **Schema Compatibility:** All schemas must pass Gemini compatibility validation (no `$ref`, `$defs`, `title`, `default`, etc.).

---
*Updated 2026-02-17 — Provider compatibility complete (LOG-006); all success criteria met*