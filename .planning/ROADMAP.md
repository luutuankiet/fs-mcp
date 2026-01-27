# Roadmap: fs-mcp Ripgrep Integration

**Project:** fs-mcp remote agent access
**Version:** v1 (Ripgrep Integration)
**Created:** 2026-01-26
**Depth:** quick (3 phases)

## Overview

Add ripgrep-based content search to fs-mcp with automatic dependency detection, bounded results, and agent workflow guidance. Completes the grep → read pattern for efficient remote codebase exploration, reducing agent context consumption by ~80%.

---

## Phase Structure

### Phase 1: Ripgrep Integration & Core Grep Tool

**Goal:** Agent can search file contents with ripgrep; server detects ripgrep availability and provides helpful install instructions if missing.

**Dependencies:** None (foundation phase)

**Requirements Mapped:**
- INIT-01: Server checks for ripgrep availability at startup
- INIT-02: Platform-specific install command displayed if missing
- INIT-03: Graceful degradation (warning logged, grep tool disabled if unavailable)
- GREP-01: Agent can search via regex patterns
- GREP-02: Search results include file paths (relative to allowed directory)
- GREP-03: Results include line numbers for each match
- GREP-04: Configurable context lines (default 2 before/after)
- GREP-05: Bounded results (max 100 matches to prevent context overflow)
- GREP-06: Respects .gitignore and excludes build artifacts
- GREP-07: Case-insensitive search via optional parameter
- GREP-08: Helpful error if ripgrep not found (with install instructions)
- GREP-09: Graceful no-matches handling (exit code 1 returns "No matches found")
- GREP-10: 10-second timeout prevents runaway searches

**Success Criteria:**

**Plans:** 1 plan
- [x] 01-01-PLAN.md — Implement Ripgrep dependency check and core `grep_content` tool.

1. Server starts with ripgrep availability check; displays platform-specific install command (brew/apt/dnf/choco) if missing, logs warning, continues serving with grep tool disabled.

2. Agent can call grep_content(pattern, search_path, case_insensitive=False, context_lines=2) and receives bounded results with file paths, line numbers, matched text, and context.

3. Search results are hard-capped at 100 matches; output is truncated with message indicating additional matches exist.

4. Search respects .gitignore and excludes node_modules, __pycache__, .venv and similar build artifacts by default.

5. Error cases handled gracefully: missing ripgrep returns install instructions; no matches returns "No matches found" (not error); timeout returns "Search exceeded 10s limit, refine pattern".

---

### Phase 2: Agent Workflow Optimization

**Goal:** Weak agents discover and efficiently use the grep → read pattern; tool descriptions guide toward optimal token usage.

**Dependencies:** Requires Phase 1 (grep tool exists)

**Requirements Mapped:**
- GUID-01: Grep tool description explicitly recommends grep → read workflow pattern
- GUID-02: read_files tool description references grep as discovery step for large codebases
- GUID-03: search_files tool description clarifies file name search vs. grep content search

**Success Criteria:**

1. Grep tool docstring clearly states the recommended workflow: "Use this to find relevant code patterns, then use read_files() to examine matches in detail" with an example pattern.

2. read_files tool docstring references grep for discovery on large codebases, suggesting "For codebases with many files, use grep_content() first to locate relevant files, then read specific matches."

3. search_files tool docstring clarifies distinction: "Searches file names by glob pattern. For content inside files, use grep_content() instead."

4. Weak agent testing validates agents (Claude 3.5 Sonnet, GPT-3.5 compatible) naturally discover and use grep → read pattern without explicit prompting.

---

### Phase 3: Production Polish & Cleanup

**Goal:** Grep tool is production-ready with documentation, observability, and legacy cleanup complete.

**Dependencies:** Requires Phase 2 (workflow optimization complete)

**Requirements Mapped:**
- CLEN-01: Remove grounding_search placeholder tool

**Success Criteria:**

1. grounding_search() placeholder is removed from server.py; all references cleaned up.

2. README.md documents ripgrep as optional system dependency with platform-specific install instructions and explains graceful degradation when missing.

3. Server logs grep operations with searchable patterns: pattern searched, result count, timeout events, ripgrep availability status.

4. Integration test suite covers: path validation, symlink handling, injection prevention, grep → read_files chaining, no-matches handling, timeout behavior.

---

### Phase 4: Add jq and yq for querying large json and yaml files

**Goal:** Agents can efficiently query large JSON and YAML files without context overflow, completing the grep → read → query pattern.

**Dependencies:** Phase 3

**Plans:** 2 plans

Plans:
- [x] 04-01-PLAN.md — Add jq/yq dependency detection with graceful degradation
- [x] 04-02-PLAN.md — Implement query_json, query_yaml tools and enhance read_files

**Success Criteria:**

1. Server detects jq and yq availability at startup; shows platform-specific install commands if missing; continues running with tools disabled (graceful degradation).

2. Agent can call query_json(file_path, jq_expression, timeout=30) to query JSON files with compact output, bounded to 100 results, timeout protection.

3. Agent can call query_yaml(file_path, yq_expression, timeout=30) to query YAML files with same bounded output and timeout protection.

4. read_files detects large JSON/YAML files (>100k tokens) and blocks by default, suggesting query tools; allows override with large_file_passthrough=True.

5. Tool docstrings include syntax examples and workflow guidance optimized for weak models (GPT-3.5, Gemini Flash).

---

### Phase 4.1: Enhance jq and yq to handle complex multiline queries request (INSERTED)

**Goal:** Handle complex multiline jq/yq expressions without escaping issues, improving agent experience with advanced queries.

**Dependencies:** Phase 4

**Plans:** 1 plan

Plans:
- [x] 04-1-01-PLAN.md — Enhance query_json and query_yaml to use temp file approach

**Success Criteria:**

1. query_json and query_yaml use temp file approach (jq -f, yq -f) eliminating command-line escaping issues.

2. Agents can send multiline queries with comments, nested functions, and special characters without errors.

3. Complex queries like the dbt lineage traversal example execute successfully.

4. Temp files are properly created, used, and cleaned up after execution.

5. Error messages include helpful context and line numbers for syntax errors.

**Details:**
This urgent insertion addresses limitations discovered during Phase 4 execution. Agents need to execute complex queries that span multiple lines or contain special characters that are difficult to escape in command-line arguments.


---

### Phase 5: enhance Section-Aware Reading

**Goal:** Enable agents to read logical sections of code without pre-calculating end lines.
**Depends on:** Phase 4.1
**Plans:** 2 plans

Plans:
- [x] 05-1-PLAN.md — Enhance read_files for section-aware reading.
- [x] 05-2-PLAN.md — Enhance grep_content with section end hints.

**Details:**
This phase enhances the `read_files` tool to read from a starting line to a regex pattern and enhances `grep_content` to provide hints for where sections might end, completing the "grep -> read section" workflow.

---

## Requirement Mapping

| Requirement | Phase | Category |
|-------------|-------|----------|
| INIT-01 | 1 | Startup & Dependencies |
| INIT-02 | 1 | Startup & Dependencies |
| INIT-03 | 1 | Startup & Dependencies |
| GREP-01 | 1 | Grep Tool (Core) |
| GREP-02 | 1 | Grep Tool (Core) |
| GREP-03 | 1 | Grep Tool (Core) |
| GREP-04 | 1 | Grep Tool (Core) |
| GREP-05 | 1 | Grep Tool (Core) |
| GREP-06 | 1 | Grep Tool (Core) |
| GREP-07 | 1 | Grep Tool (Core) |
| GREP-08 | 1 | Grep Tool (Error Handling) |
| GREP-09 | 1 | Grep Tool (Error Handling) |
| GREP-10 | 1 | Grep Tool (Error Handling) |
| GUID-01 | 2 | Tool Guidance |
| GUID-02 | 2 | Tool Guidance |
| GUID-03 | 2 | Tool Guidance |
| CLEN-01 | 3 | Cleanup |

**Coverage:** 17/17 requirements mapped (100%)

---

## Progress Tracking

| Phase | Status | Goal | Success Criteria Met | Notes |
|-------|--------|------|---------------------|-------|
| Phase 1 | Complete | Ripgrep integration, core grep tool | 5/5 | Foundation: startup detection, bounded search, error handling |
| Phase 2 | Complete | Workflow optimization | 4/4 | Agent guidance: improved tool descriptions, weak agent validation |
| Phase 3 | Pending | Production polish | 0/4 | Cleanup: remove placeholder, documentation, observability |
| Phase 4 | Complete | Add jq and yq for querying large json and yaml files | 5/5 | Structured data query tools with bounded output |
| Phase 4.1 | Complete | Enhance jq and yq to handle complex multiline queries request | 5/5 | INSERTED - Urgent: Handle complex multiline expressions |

---

**Last Updated:** 2026-01-27
**Roadmap Status:** Phase 4.1 complete
