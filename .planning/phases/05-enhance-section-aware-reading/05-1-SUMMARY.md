---
phase: 05-enhance-section-aware-reading
plan: 1
subsystem: "api"
tags: ["python", "fastapi", "file-io", "regex"]

# Dependency graph
requires:
  - phase: 04.1-enhance-query-tools
    provides: "Enhanced query tools for structured data."
provides:
  - "Section-aware reading capability in the `read_files` tool."
  - "Robust parameter validation for file reading operations."
affects: ["agent-workflows"]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Memory-efficient file iteration with `itertools.islice`", "Structured error message formatting for agent self-correction"]

key-files:
  created: []
  modified: ["src/fs_mcp/server.py"]

key-decisions:
  - "Implemented section-aware reading using a combination of `start_line` and a regex pattern (`read_to_next_pattern`) to define dynamic read boundaries."
  - "Enforced mutual exclusivity between `end_line` and `read_to_next_pattern` to prevent ambiguous requests."
  - "If `read_to_next_pattern` is not found, the tool reads to the end of the file and provides an informational note, ensuring predictable behavior for agents."

# Metrics
duration: null
completed: 2026-01-27
---

# Phase 5 Plan 1: Enhance `read_files` for Section-Aware Reading Summary

**Enhanced the `read_files` tool to support efficient, section-aware reading from a start line to a dynamically found regex pattern, complete with robust validation and clear documentation.**

## Performance

- **Duration:** (Will be filled in by executor)
- **Tasks:** 3/3
- **Files modified:** 1

## Accomplishments
- **Section-Aware Reading:** Agents can now read logical blocks of code (e.g., functions, classes) by specifying a start line and a pattern for the next block, removing the need to know the exact end line.
- **Robust Error Handling:** The tool provides clear, structured error messages for invalid parameter combinations (like using both `end_line` and `read_to_next_pattern`), helping agents self-correct their requests.
- **Predictable EOF Behavior:** If the specified pattern isn't found, the tool reads to the end of the file and explicitly notes this, providing predictable and safe behavior.
- **Improved Documentation:** The `read_files` docstring was updated to clearly explain the new functionality with examples, making it discoverable and easy to use for agents.

## Task Commits

1. **Task 1 & 2: Implement Section-Aware Reading & Validation** - `3d770cd` (feat)
2. **Task 3: Update `read_files` Docstring** - `a2256a1` (docs)

## Files Created/Modified
- `src/fs_mcp/server.py` - Added `read_to_next_pattern` to the `FileReadRequest` model, implemented the core section-reading logic and parameter validation in the `read_files` function, and updated its docstring.

## Decisions Made
- Followed the plan as specified. Key implementation choices include:
  - Using `itertools.islice` for memory-efficient iteration, preventing issues with large files.
  - Adhering to the structured error message format defined in the phase context to improve agent self-correction.
  - Making the end-of-file fallback with an informational note a core behavior to prevent unexpected failures.

## Deviations from Plan
None - the plan was executed exactly as written.

## Next Phase Readiness
The core `read_files` tool is now enhanced. The project is ready for the next plan, which will focus on enhancing `grep_content` to provide section end hints, completing the "grep -> read section" workflow.
