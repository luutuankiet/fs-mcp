---
phase: 04-add-jq-and-yq-for-querying-large-json-and-yaml-files
plan: 1
subsystem: "dependency-check"
tags: ["jq", "yq", "cli-tools", "dependencies"]

# Dependency graph
requires:
  - phase: 01-add-ripgrep-for-efficient-content-search
    provides: "Pattern for checking external CLI tool availability at startup."
provides:
  - "Startup checks for jq and yq availability."
  - "Platform-specific installation guidance for jq and yq."
  - "Global availability flags (IS_JQ_AVAILABLE, IS_YQ_AVAILABLE) for graceful degradation."
affects: 
  - "04-02"

# Tech tracking
tech-stack:
  added: ["distro"]
  patterns: ["Graceful degradation for optional CLI dependencies."]

key-files:
  created: []
  modified:
    - "src/fs_mcp/utils.py"
    - "src/fs_mcp/server.py"
    - "pyproject.toml"
    - ".gitignore"

key-decisions:
  - "Followed the existing ripgrep pattern for checking jq and yq to maintain consistency."
  - "Created a Python virtual environment to manage project dependencies cleanly."

# Metrics
duration: null
completed: 2026-01-27
---

# Phase 4 Plan 1: Add jq/yq dependency detection Summary

**Implemented startup checks for `jq` and `yq` command-line tools, providing platform-specific installation guidance and enabling graceful degradation if the tools are missing.**

## Performance

- **Duration:** 15 min 
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments
- **`utils.py`:** Added `check_jq()` and `check_yq()` functions to detect the presence of `jq` and `yq`, respectively. These functions return platform-specific installation commands if the tools are not found.
- **`server.py`:** Integrated the new checks into the server's `initialize()` function. The server now sets `IS_JQ_AVAILABLE` and `IS_YQ_AVAILABLE` flags at startup and prints a warning if a tool is missing.
- **Dependency Management:** Added the `distro` package to `pyproject.toml` to support Linux distribution detection. A virtual environment was created to manage project dependencies.

## Task Commits

1. **Task 1: Add jq and yq availability checks to utils.py** - `0afae10` (feat)
2. **Task 2: Initialize jq/yq availability checks in server.py** - `887b8b1` (feat)

## Files Created/Modified
- `src/fs_mcp/utils.py`: Added `check_jq()` and `check_yq()` functions.
- `src/fs_mcp/server.py`: Imported and called the new check functions at startup.
- `pyproject.toml`: Added `distro` as a dependency.
- `.gitignore`: Added `venv/` to ignore the virtual environment directory.

## Decisions Made
- Chose to follow the exact pattern of the existing `check_ripgrep` function for consistency and maintainability.
- Established a project-specific virtual environment to resolve dependency issues and isolate the project, which is a standard best practice.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing `distro` dependency**
- **Found during:** Task 1 Verification
- **Issue:** The verification script failed with `ModuleNotFoundError: No module named 'distro'`, which is required for Linux platform detection in `utils.py`.
- **Fix:** 
    1. Added `"distro"` to the `dependencies` list in `pyproject.toml`.
    2. Created a virtual environment (`venv`) to manage project dependencies.
    3. Installed all project dependencies within the virtual environment using `pip install .`.
- **Files modified:** `pyproject.toml`, `.gitignore`
- **Verification:** The verification command for Task 1 passed successfully after the dependency was installed.
- **Committed in:** `0afae10`

---
*Phase: 04-add-jq-and-yq-for-querying-large-json-and-yaml-files*
*Completed: 2026-01-27*
