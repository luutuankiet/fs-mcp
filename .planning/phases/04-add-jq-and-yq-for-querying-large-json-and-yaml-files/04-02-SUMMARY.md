---
phase: 04-add-jq-and-yq-for-querying-large-json-and-yaml-files
plan: 2
subsystem: "agent-tools"
tags: ["jq", "yq", "cli-tools", "file-io", "agent-guidance"]

# Dependency graph
requires:
  - phase: "04-01"
    provides: "Startup checks for jq and yq availability."
provides:
  - "query_json tool for querying JSON files via jq."
  - "query_yaml tool for querying YAML files via yq."
  - "Enhanced read_files tool that guides agents to use query tools for large files."
affects: 
  - "future agent development"
  - "large file processing"

# Tech tracking
tech-stack:
  added: []
  patterns: ["CLI tool wrapper", "Graceful degradation for optional tools", "Agent guidance in tool descriptions"]

key-files:
  created: []
  modified:
    - "src/fs_mcp/server.py"

key-decisions:
  - "Followed the existing ripgrep pattern for subprocess execution, error handling, and result limiting for consistency."
  - "Made the large file check in read_files an explicit opt-out to prevent accidental context overflows by agents."

# Metrics
duration: null # Will be filled in later
completed: 2026-01-27
---

# Phase 4 Plan 2: Implement jq/yq query tools and enhance read_files Summary

**Implemented `query_json` and `query_yaml` tools to enable efficient querying of large structured data files, and enhanced `read_files` to proactively guide agents towards these tools.**

## Performance

- **Duration:** 35 min 
- **Tasks:** 3/3
- **Files modified:** 1

## Accomplishments
- **`query_json` Tool:** A new tool that allows agents to query JSON files using `jq` expressions via a subprocess. It includes robust error handling, a 30-second timeout, and limits results to 100 lines to prevent context overflow.
- **`query_yaml` Tool:** A parallel implementation for YAML files using the `yq` command-line tool. It provides the same safety features as `query_json` and outputs results in a consistent, compact JSON format.
- **`read_files` Enhancement:** The `read_files` tool now detects attempts to read large JSON or YAML files (estimated >100k tokens). By default, it blocks the read and returns a helpful message guiding the agent to use the more efficient `query_json` or `query_yaml` tools, while allowing an override with a `large_file_passthrough` flag.

## Task Commits

1. **Task 1: Implement query_json tool** - `3b79ce8` (feat)
2. **Task 2: Implement query_yaml tool** - `14a2d60` (feat)
3. **Task 3: Enhance read_files with large file detection** - `a246278` (feat)

## Files Created/Modified
- `src/fs_mcp/server.py`: Added the `query_json` and `query_yaml` tools and modified the `read_files` tool.

## Decisions Made
- Followed the existing `grep_content` tool's implementation pattern for consistency in subprocess handling, error reporting, and result limiting. This ensures a predictable experience for agents using the tools.
- Decided to make the large file check in `read_files` block by default. This is a proactive measure to prevent agents from accidentally consuming their entire context window on a single large file, thus improving overall agent reliability.

## Deviations from Plan

None - plan executed exactly as written.
