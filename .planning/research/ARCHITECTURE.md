# Ripgrep-Based Grep Tool Architecture

**Domain:** Filesystem MCP Server with Content Search
**Researched:** 2026-01-26
**Analysis Mode:** Architecture Patterns & Integration Design

---

## Executive Summary

The fs-mcp server is a modular MCP filesystem tool with a clear tool layer abstraction. Adding a ripgrep-based grep tool requires minimal architectural changes because the existing pattern (validate → execute → serialize) aligns perfectly with how ripgrep should integrate. The tool should replace the unused `grounding_search` placeholder and follow the established patterns for security and input/output handling.

**Key integration points:**
- Path validation through existing `validate_path()` security gate
- Subprocess execution pattern already established (VS Code in edit_tool, can reuse for ripgrep)
- Bounded output structure for agent context windows (following `read_files` precedent)
- Structured input via Pydantic model (like `FileReadRequest`)

---

## Recommended Architecture

### Conceptual Layers

```
┌─────────────────────────────────────────────────┐
│ CLI Orchestration Layer (__main__.py)           │
│ - Process spawning, argument parsing            │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ MCP Server Core (server.py)                     │
├──────────────────────────────────────────────────┤
│  Security Gate (validate_path)                  │
│  ├─ Path resolution & canonicalization         │
│  ├─ Symlink handling                           │
│  └─ Directory boundary enforcement             │
├──────────────────────────────────────────────────┤
│  Tool Layer (decorated @mcp.tool())            │
│  ├─ File Tools (read_files, write_file, etc.)  │
│  ├─ Directory Tools (list_directory, etc.)     │
│  ├─ Edit Tools (propose_and_review, etc.)      │
│  └─ [NEW] Search Tool (grep_content)           │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ Subprocess/System Layer                         │
│ - VS Code diff tool (existing)                  │
│ - Ripgrep executor (new)                        │
│ - Path operations (pathlib, os)                 │
└──────────────────────────────────────────────────┘
```

### Tool Layer Structure

**Current tools organized by function:**
- **Read Tools:** `read_files`, `read_media_file`, `get_file_info`
- **Write Tools:** `write_file`, `create_directory`, `move_file`, `append_text`
- **Discovery Tools:** `list_directory`, `list_directory_with_sizes`, `search_files` (glob-based)
- **Edit Tools:** `propose_and_review`, `commit_review`
- **Meta Tools:** `list_allowed_directories`

**Grep Tool Placement:**
The grep tool should be categorized as a **Discovery Tool** and placed in the same logical group as `search_files`. These two tools work together:
- `search_files(path, pattern)` - Finds files by name (glob)
- `grep_content(path, pattern, ...)` - Finds content within files (ripgrep)

---

## Component Boundaries & Integration Points

### Input Model Design

Following the existing `FileReadRequest` pattern for structured input:

```python
class GrepRequest(BaseModel):
    """Structured input for grep operations."""
    path: str                          # Directory root (validated)
    pattern: str                       # Regex pattern for ripgrep
    context_lines: int = 2             # Lines of context (default: 2)
    max_matches: int = 100             # Bounded output (prevent context overflow)
    max_files: int = None              # Optional: limit number of files searched
    file_pattern: Optional[str] = None # Optional: filter by glob pattern
    case_insensitive: bool = False     # ripgrep -i flag
```

**Design rationale:**
- Matches FastMCP's Pydantic model pattern (like `FileReadRequest`)
- Supports future expansion (e.g., `file_pattern` for targeted searches)
- Bounded outputs (`max_matches`, `max_files`) prevent agent context overflow
- Aligns with weak agent guidance in tool descriptions

### Security Integration

The grep tool **reuses existing security patterns**, no new architecture needed:

```python
@mcp.tool()
def grep_content(path: str, pattern: str, context_lines: int = 2,
                 max_matches: int = 100, max_files: Optional[int] = None,
                 file_pattern: Optional[str] = None, case_insensitive: bool = False) -> str:
    """Search file contents with ripgrep."""

    # 1. SECURITY: Validate root directory
    root = validate_path(path)  # Existing gate, reused

    # 2. EXECUTION: Shell out to ripgrep with safe arguments
    args = _build_ripgrep_args(pattern, context_lines, max_matches,
                               file_pattern, case_insensitive)

    # 3. SERIALIZATION: Format results as bounded text
    result = _execute_ripgrep_safe(root, args)
    return _format_grep_results(result, max_files)
```

**Why this works:**
- `validate_path()` ensures ripgrep operates only within allowed directories
- Ripgrep subprocess runs in restricted context (working directory = validated root)
- No symlink issues (ripgrep follows symlinks by default, which is safe post-validation)

---

## Data Flow for Grep Tool

### Request Path

```
1. Agent calls grep_content(path="/src", pattern="TODO", context_lines=3)
   │
2. MCP server routes to @mcp.tool() decorated function
   │
3. grep_content() function:
   a. Validates path with validate_path("/src")
      → Returns validated Path object (security gate passes)
   b. Builds ripgrep command: ["rg", "TODO", "--context=3", "--max-count=100", ...]
   c. Runs subprocess: subprocess.run(args, cwd=validated_root, capture_output=True)
   d. Parses output: Splits matches into bounded list
   e. Formats result: "File: src/main.py\n  42: TODO: Fix this\n    ..."
   │
4. FastMCP serializes result as MCP content block
   │
5. Agent receives grep results with line numbers and context
   │
6. Agent can use grep → targeted read pattern:
   "Found TODO at line 42, now read lines 40-50"
```

### Error Handling Path

```
Agent input: grep_content(path="/etc/shadow", pattern=".*")
   │
validate_path("/etc/shadow")
   └─ Raises: ValueError("Access denied: /etc/shadow is outside allowed directories")
   │
FastMCP catches exception
   │
Agent receives: Error content block with validation error message
```

### Performance Considerations

Ripgrep subprocess output is bounded by three mechanisms:

1. **ripgrep flags** (explicit limits):
   - `--max-count=100` per file (configurable via `max_matches`)
   - Prevents processing massive match lists

2. **Python post-processing** (safety bound):
   - Splits ripgrep output into list
   - Truncates at `max_files` results if specified
   - Discards tail output with "... {N} more matches"

3. **Output format** (context window guard):
   - Format includes file path, line number, and context lines
   - Total output typically 5-20 KB even with 100 matches × 5 context lines
   - Agents can calculate needed reads from grep output

---

## Patterns to Follow

### Pattern 1: Path Validation Gate

**What:** All file operations must pass through `validate_path()` before touching the filesystem.

**When:** Every tool that accepts a path parameter.

**Example:**
```python
@mcp.tool()
def grep_content(path: str, pattern: str) -> str:
    root = validate_path(path)  # Security first
    # Then execute on validated path
    subprocess.run(["rg", pattern], cwd=root, ...)
```

**Why it works for grep:**
- Ripgrep respects working directory isolation
- Subprocess runs with validated `cwd`, cannot escape
- Even if pattern is malicious (e.g., `--path-separator /` tricks), only affects within validated dir

### Pattern 2: Subprocess Safety

**What:** Subprocess calls must avoid shell=True and use argument lists.

**When:** Any tool that executes system commands (edit_tool.py uses this for VS Code).

**Example:**
```python
# DON'T: subprocess.run(f"rg {pattern}", shell=True, ...)
# DO:
args = ["rg", "--color=never", pattern, "--max-count=100"]
result = subprocess.run(args, cwd=root, capture_output=True, text=True)
```

**Why it works for grep:**
- Prevents command injection through pattern parameter
- Ripgrep argument parsing is safe (it's not a shell)

### Pattern 3: Bounded Output

**What:** Search and discovery tools must limit result size to prevent context overflow.

**When:** Any tool that returns variable-length results.

**Example (from read_files):**
```python
# Tool description guides agent:
"""
**LARGE FILE HANDLING:**
If you encounter errors like "response too large":
1. Call `get_file_info(path)` to understand dimensions
2. Use `head` or `tail` parameters to read in chunks
"""

# Then grep_content should similarly bound and guide:
def grep_content(path: str, pattern: str, max_matches: int = 100) -> str:
    """
    **LARGE RESULT HANDLING:**
    If you find too many matches (>100):
    1. Refine your pattern to be more specific
    2. Use `file_pattern` to target specific files
    3. Use grep output with line numbers to call read_files on specific regions
    """
```

**Why it works for grep:**
- Agents can refine searches based on initial results
- `grep → read` pattern naturally chains tools
- Line numbers in grep output guide targeted reads

### Pattern 4: Structured Input Models

**What:** Complex tools use Pydantic BaseModel for input validation.

**When:** Tools with 3+ parameters or complex parameter relationships.

**Example (existing - FileReadRequest):**
```python
class FileReadRequest(BaseModel):
    path: str
    head: Optional[int] = None
    tail: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
```

**For grep, optional approach:**
```python
# SIMPLE APPROACH (current tools):
@mcp.tool()
def grep_content(path: str, pattern: str, context_lines: int = 2,
                 max_matches: int = 100, case_insensitive: bool = False) -> str:
    ...

# FUTURE APPROACH (if complexity grows):
class GrepRequest(BaseModel):
    path: str
    pattern: str
    context_lines: int = 2
    max_matches: int = 100

@mcp.tool()
def grep_content(request: GrepRequest) -> str:
    ...
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Unbounded Output

**What:** Returning all matches without limits.

**Why bad:** Exhausts agent context windows, fails silently in truncation, wastes tokens.

**Instead:**
```python
# DON'T:
result = subprocess.run(["rg", pattern, root], capture_output=True)
return result.stdout  # Could be 100 MB if pattern matches everything

# DO:
result = subprocess.run(["rg", pattern, "--max-count=100", root], ...)
return _truncate_results(result.stdout, max_lines=500)  # Bound at format time too
```

### Anti-Pattern 2: Ripgrep-Specific Output Parsing Without Standardization

**What:** Returning raw ripgrep --json output without standardization.

**Why bad:** Ripgrep flags/output format varies by version, breaks agent handling.

**Instead:**
```python
# DON'T:
result = subprocess.run(["rg", "--json", pattern], ...)
return result.stdout  # JSON format internal to ripgrep, fragile

# DO:
result = subprocess.run(["rg", "--color=never", "--with-filename", "--line-number", ...], ...)
# Parse ripgrep text output, return standardized format:
# "File: src/main.py\n  42:  TODO fix this\n  43:  more context\n\n---\n\nFile: test.py..."
```

### Anti-Pattern 3: Shell Injection

**What:** Building ripgrep commands with f-strings or shell=True.

**Why bad:** Pattern parameter can escape quotes, inject flags, break security.

**Instead:**
```python
# DON'T:
os.system(f"rg '{pattern}' {path}")
subprocess.run(f"rg {pattern}", shell=True, cwd=path)

# DO:
args = ["rg"]
if case_insensitive: args.append("-i")
args.extend([pattern, str(root)])
subprocess.run(args, cwd=root, capture_output=True, text=True)
```

### Anti-Pattern 4: No Graceful Fallback for Missing Ripgrep

**What:** Crashing when ripgrep isn't installed.

**Why bad:** Violates zero-setup promise if ripgrep must be pre-installed.

**Instead:**
```python
def _ensure_ripgrep_available() -> bool:
    """Check for ripgrep, return helpful install message if missing."""
    if shutil.which("rg") is None:
        raise RuntimeError(
            "ripgrep not found. Install with:\n"
            "  macOS: brew install ripgrep\n"
            "  Linux: apt install ripgrep  OR  yum install ripgrep\n"
            "  Windows: choco install ripgrep"
        )
    return True

@mcp.tool()
def grep_content(path: str, pattern: str) -> str:
    try:
        _ensure_ripgrep_available()
    except RuntimeError as e:
        return f"Error: {e}"
```

---

## Integration Points & Build Order

### Existing Touch Points (No Changes Required)

1. **validate_path() in server.py (lines 72-124)**
   - Reused as-is for path security
   - No modifications needed

2. **Imports in server.py**
   - Add `import subprocess` (already present for VS Code)
   - Add `import shutil` for ripgrep availability check (already present)

3. **FastMCP tool registration**
   - Decorate new function with `@mcp.tool()`
   - Already set up for auto-discovery

### Minimal Changes Required

1. **Replace `grounding_search()` placeholder (line 593-597)**
   - Remove stub implementation
   - Add real `grep_content()` implementation

2. **Add helper functions**
   - `_build_ripgrep_args()` - construct safe ripgrep command
   - `_execute_ripgrep_safe()` - run subprocess, handle errors
   - `_format_grep_results()` - standardize output format
   - `_ensure_ripgrep_available()` - helpful error message

3. **Update tool descriptions (optional but recommended)**
   - Add hint to `read_files()` docstring: suggest `grep_content()` first
   - Add hint to grep docstring: suggest `read_files()` for exploration
   - Example: "For best results, use grep_content to find matches, then read_files for targeted reads"

### Testing & Validation Points

1. **Unit tests in tests/test_server.py**
   - Test grep with valid pattern + allowed directory
   - Test grep with out-of-bounds path (security)
   - Test grep with malicious pattern (no injection)
   - Test grep with missing ripgrep (error handling)
   - Test bounded output (max_matches respected)

2. **Integration test scenarios**
   - Agent calls grep → reads specific lines
   - Multiple tools chain: grep → read → edit → review → commit

---

## Data Structure Design

### Input Parameters vs Model

**Current approach (most tools):** Individual parameters
```python
def grep_content(
    path: str,
    pattern: str,
    context_lines: int = 2,
    max_matches: int = 100,
    file_pattern: Optional[str] = None,
    case_insensitive: bool = False
) -> str:
```

**Advantages:**
- Simple for weak agents (each parameter is explicit)
- Matches existing tool convention (`read_files`, `write_file`, etc.)
- No model parsing overhead

**Alternative (not recommended for MVP):** Pydantic model
```python
class GrepRequest(BaseModel):
    path: str
    pattern: str
    context_lines: int = 2
    max_matches: int = 100
    file_pattern: Optional[str] = None
    case_insensitive: bool = False

@mcp.tool()
def grep_content(request: GrepRequest) -> str:
```

**When to switch:** If parameters grow beyond 6 or require interdependent validation.

---

## Output Format Specification

### Result Format

```
File: src/main.py
  42: def process_data():
  43:    # TODO: optimize this loop
  44:    for item in items:

---

File: src/utils.py
  156: # TODO: add error handling
  157: def validate_input(x):
  158:    return x > 0

---

(Showing 2 of 5 matching files. Use file_pattern or refine your pattern to narrow results.)
```

### Format Rules

1. File path relative to search root (matches `search_files` convention)
2. Line numbers with colon prefix (matches VS Code convention)
3. Context lines indented (improves readability)
4. File groups separated by "---" (matches `read_files` multi-result pattern)
5. Truncation message if max_files exceeded (guides agents to refine)

### Structured Alternative (JSON, if needed for future)

```json
{
  "query": "TODO",
  "root": "/src",
  "matches": [
    {
      "file": "main.py",
      "line": 42,
      "before": ["def process_data():"],
      "match": "# TODO: optimize this loop",
      "after": ["for item in items:"]
    }
  ],
  "total_matches": 150,
  "truncated": true,
  "message": "Showing 100 of 150 matches. Refine pattern to narrow results."
}
```

**Decision:** Start with text format (simple, agent-friendly). Can add JSON variant later if needed.

---

## Ripgrep Integration Specifics

### Why Ripgrep

**Ripgrep is the right choice because:**
1. **Ubiquitous on dev machines** - Most developers have `rg` installed already
2. **Extremely fast** - 10-100x faster than GNU grep (uses SIMD, parallelization)
3. **Safe by default** - No regex injection issues (processes pattern as literal/regex, not shell code)
4. **Agent-friendly output** - Clean text format, honors `--max-count`, respects working directories
5. **Minimal dependencies** - Single binary, no Python regex engine limitations

### Ripgrep Flags for Safety

```python
def _build_ripgrep_args(
    pattern: str,
    context_lines: int,
    max_matches: int,
    file_pattern: Optional[str],
    case_insensitive: bool
) -> List[str]:
    args = ["rg"]

    # Safety & Output Control
    args.append("--color=never")          # No ANSI codes (clean output)
    args.append(f"--context={context_lines}")
    args.append(f"--max-count={max_matches}")

    # Optional Filters
    if case_insensitive:
        args.append("-i")
    if file_pattern:
        args.append(f"--glob={file_pattern}")  # ripgrep's glob filtering

    # Search Pattern (always last)
    args.append(pattern)

    return args
```

**Why these flags:**
- `--color=never` - Strips ANSI codes that break text parsing
- `--max-count` - Ripgrep-level bound, enforced before output even starts
- `--context` - Reduces post-processing (ripgrep does context natively)
- `--glob` - Ripgrep's built-in file filtering (safer than post-processing)

### Error Cases

**Ripgrep exit codes:**
- `0` - Success, found matches
- `1` - Success, no matches
- `2` - Error (invalid pattern, permission denied, etc.)

**Handling:**
```python
result = subprocess.run(args, cwd=root, capture_output=True, text=True)
if result.returncode == 2:
    # Error from ripgrep
    return f"Error: {result.stderr}"
elif result.returncode == 1:
    # No matches found
    return f"No matches found for pattern: {pattern}"
else:
    # Matches found (returncode == 0)
    return _format_grep_results(result.stdout)
```

---

## Scalability & Performance Notes

### At Different Scales

| Scenario | Approach | Notes |
|----------|----------|-------|
| Small codebase (< 100K lines) | No special handling | Ripgrep handles instantly |
| Medium codebase (100K - 1M lines) | Bound with --max-count=100 | Prevents large matches list |
| Large codebase (> 1M lines) | Add --glob filtering | Use file_pattern param to target |
| Searching in node_modules | Risk high | Recommend agent refines to exclude |

### Token Efficiency

Grep results are token-efficient because:
1. **No full file reads** - Only lines with matches (+ context)
2. **Bounded output** - Max 100 matches × 5 lines = 500 lines max
3. **Line numbers provided** - Agents can calculate exact read ranges
4. **Context lines included** - Agents get immediate context without extra reads

**Example token cost:**
- Glob search for 1000 files: ~50 tokens (file list)
- Grep for pattern in same 1000 files: ~200 tokens (matches + context)
- Read 5 files from grep results: ~5000 tokens (actual file content)
- Total: Grep "costs" 200 tokens but saves thousands by avoiding blind reads

---

## Deployment & Operational Considerations

### Ripgrep Availability

**Problem:** ripgrep must be pre-installed (system dependency).

**Solution:** Helpful error message with install commands:
```
Error: ripgrep not found. Install with:
  macOS:   brew install ripgrep
  Ubuntu:  apt-get install ripgrep
  Fedora:  dnf install ripgrep
  Windows: choco install ripgrep
  Or download: https://github.com/BurntSushi/ripgrep/releases
```

**Why this is acceptable:**
- ripgrep is ubiquitous in dev environments
- Installation is one command
- Error message makes it self-help
- Alternatives (Python re module) would be 100x slower, not acceptable for grep

### Documentation Updates Needed

1. **README.md:** Add ripgrep to "Requirements" or "Installation"
2. **Tool docstring:** Include ripgrep install hint in grep_content description
3. **PROJECT.md:** Document ripgrep as a system dependency (like Python, VS Code)

---

## Summary: How Grep Fits Into Existing Architecture

### Minimal Changes Required

1. **Location:** `src/fs_mcp/server.py`, replace lines 593-597
2. **Pattern:** Follow existing tool structure (validate path → execute → format output)
3. **Security:** Reuse `validate_path()`, no new security logic
4. **I/O:** Subprocess (already pattern in codebase via VS Code tool)
5. **Testing:** Add tests to `tests/test_server.py`

### Integration Strength

- **✓ Zero architectural changes** - Fits perfectly into existing tool layer
- **✓ Reuses security patterns** - No new validation logic needed
- **✓ Reuses subprocess patterns** - Already used for VS Code diff tool
- **✓ Follows output conventions** - Matches read_files + search_files patterns
- **✓ Supports tool chaining** - `grep_content()` → `read_files()` workflow naturally flows

### Build Order Implications

1. **Phase 1 (Implementation):** Add grep_content() function, helpers, tests
2. **Phase 2 (Integration):** Update tool descriptions with grep/read guidance
3. **Phase 3 (Polish):** Remove grounding_search placeholder, documentation

No dependencies on other features. Grep can be implemented independently.

---

*Architecture Research: 2026-01-26*
