---
phase: 04-1-enhance-jq-yq-multiline
plan: 01
subsystem: api
tags: [jq, yq, json, yaml, query, tempfile]

# Dependency graph
requires:
  - phase: 04-add-jq-and-yq
    provides: query_json and query_yaml tools with basic CLI integration
provides:
  - query_json tool with temp file approach for complex multiline expressions
  - query_yaml tool with temp file approach for complex multiline expressions
  - Enhanced error messages with syntax guidance for both tools
affects: [agents using query_json/query_yaml for complex dbt lineage queries]

# Tech tracking
tech-stack:
  added: []
  patterns: [temp file approach for CLI tool input, finally block cleanup pattern]

key-files:
  created: []
  modified: [src/fs_mcp/server.py]

key-decisions:
  - "Use tempfile.NamedTemporaryFile for query expressions to avoid shell escaping"
  - "Use jq -f flag for temp file execution"
  - "Use yq --from-file flag (not -f) for temp file execution"
  - "Enhance error messages with common syntax issue guidance"

patterns-established:
  - "Temp file pattern: write content, close, execute, finally cleanup with os.unlink"
  - "Enhanced error messages include actionable guidance for syntax issues"

# Metrics
duration: 3min
completed: 2026-01-27
---

# Phase 04-1 Plan 01: Enhance jq and yq Multiline Query Handling Summary

**query_json and query_yaml tools now use temp files with -f/--from-file flags, eliminating command-line escaping issues for complex multiline queries with comments and special characters**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-27T06:24:03Z
- **Completed:** 2026-01-27T06:26:45Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- query_json uses temp file approach with jq -f flag, enabling multiline queries with comments
- query_yaml uses temp file approach with yq --from-file flag, enabling multiline queries with comments
- Both tools properly cleanup temp files in finally blocks
- Enhanced error messages provide syntax guidance for common issues
- Verified complex queries with nested functions and special characters work correctly

## Task Commits

Each task was committed atomically:

1. **Task 1: Enhance query_json to use temp file approach** - `d3a69e1` (feat)
2. **Task 2: Enhance query_yaml to use temp file approach** - `c15d26c` (feat)

## Files Created/Modified
- `src/fs_mcp/server.py` - Modified query_json and query_yaml functions to use temp file approach

## Decisions Made

**1. Use tempfile.NamedTemporaryFile with delete=False**
- Rationale: Provides secure temp file creation with control over cleanup timing
- Pattern: Write content, close explicitly, execute subprocess, cleanup in finally block

**2. Different flag syntax for jq vs yq**
- jq uses: `-f <filepath>` (short form)
- yq uses: `--from-file <filepath>` (long form, -f conflicts with --front-matter)
- Rationale: Each tool has different CLI conventions, must respect them

**3. Enhanced error messages with actionable guidance**
- Format: "jq/yq syntax error: [original]. Check your query for common issues (unclosed brackets, missing semicolons, undefined functions)."
- Rationale: Helps agents debug syntax errors without multiple round trips

**4. Keep existing result limiting and timeout behavior**
- Rationale: Temp file approach is internal implementation detail, doesn't change tool behavior

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**1. yq CLI flag differences from jq**
- **Issue:** Initial implementation used `-c` (compact) flag which doesn't exist in yq
- **Resolution:** Used `-I 0` (indent=0) with `-o json` for compact JSON output
- **Issue:** Initial implementation used `-f` flag which conflicts with yq's `--front-matter` flag
- **Resolution:** Used `--from-file` long form instead
- **Impact:** Required adjustment during verification, but pattern still works correctly

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Complex multiline queries now work reliably for both JSON and YAML files
- Agents can use comments and nested functions in queries without escaping issues
- Error messages guide agents toward fixing syntax problems
- Pattern is established for any future CLI tool integrations that need complex input

**Ready for:** Agent workflows using complex dbt lineage traversal queries as described in 04-1-CONTEXT.md

---
*Phase: 04-1-enhance-jq-yq-multiline*
*Completed: 2026-01-27*
