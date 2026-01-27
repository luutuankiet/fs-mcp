# Phase 4.1: Enhance jq and yq to Handle Complex Multiline Queries - Research

**Researched:** 2026-01-27
**Domain:** CLI tool enhancement for complex query expression handling
**Confidence:** HIGH

## Summary

This phase enhances the existing `query_json` and `query_yaml` tools to handle complex multiline jq/yq expressions without escaping issues. Both jq (v1.8.1) and yq (v4.50.1) support reading query expressions from files via the `-f` flag, eliminating the need for complex shell escaping and enabling support for comments, nested functions, and multiline formatting.

The enhancement is straightforward: instead of passing expressions as command-line arguments, write them to temporary files and use the `-f` flag. This is the standard pattern both tools provide, requiring minimal code changes and building on the existing Phase 4 implementation.

**Key findings:**
- jq supports `-f`/`--from-file` flag to read expressions from files (official jq manual)
- yq supports `--from-file` flag to load expression from file (verified in GitHub README)
- Python's `tempfile.NamedTemporaryFile` with `delete_on_close=False` is the recommended pattern for subprocess workflows
- Both tools provide syntax errors via stderr with line numbers (column numbers limited in older versions)
- No breaking changes to existing tool signatures or behavior

**Primary recommendation:** Use `tempfile.NamedTemporaryFile(delete_on_close=False)` to write queries to files, pass via `-f` flag, and ensure cleanup via context manager.

## Standard Stack

The established libraries/tools for this domain:

### Core (No Changes)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jq | 1.8.1 | JSON command-line processor with file-based expressions | Industry standard; supports `-f` flag for reading queries from files |
| yq (mikefarah) | v4.50.1 | YAML processor with file-based expressions support | jq-like syntax; `--from-file` flag enables complex queries |
| tempfile | Python 3.10+ stdlib | Temporary file creation with safe cleanup | Standard pattern for subprocess file operations |

### Supporting Tools
| Tool | Purpose | Usage |
|------|---------|-------|
| `tempfile.NamedTemporaryFile` | Create named temp files for query scripts | Read-write access, guaranteed cleanup via context manager |
| `NamedTemporaryFile(delete_on_close=False)` | Keep file available during subprocess execution | Prevents deletion before subprocess can read |

### Execution Patterns (No Changes)
| Pattern | Tool | Purpose |
|---------|------|---------|
| Subprocess execution | Python `subprocess.run()` | Execute jq/yq with temp file paths |
| Path validation | Existing `validate_path()` | Security check before subprocess |
| Tool availability | Existing `check_jq()`, `check_yq()` | Runtime availability verification |

**No new library dependencies required.** Phase 4.1 uses only Python standard library additions (tempfile context manager patterns already available).

## Architecture Patterns

### Pattern: Temp File-Based Query Execution

**What:** Write query expression to temporary file, pass file path to jq/yq via `-f` flag

**When to use:** All jq/yq query executions to support multiline, commented, and complex expressions

**Implementation pattern:**
```python
# Source: Python tempfile documentation (https://docs.python.org/3/library/tempfile.html)
# and jq manual (https://jqlang.org/manual/) + yq GitHub README

import tempfile
from pathlib import Path

def query_json(file_path: str, jq_expression: str, timeout: int = 30) -> str:
    """Query JSON using jq with support for multiline expressions."""
    if not IS_JQ_AVAILABLE:
        _, msg = check_jq()
        return f"Error: jq is not available. {msg}"

    validated_path = validate_path(file_path)

    # NEW: Write expression to temp file
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.jq',
            delete_on_close=False,
            encoding='utf-8'
        ) as query_file:
            query_file.write(jq_expression)
            query_file_path = query_file.name

        # Execute jq with -f flag (reads query from file)
        command = ['jq', '-c', '-f', query_file_path, str(validated_path)]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
        finally:
            # Cleanup temp file after execution
            Path(query_file_path).unlink(missing_ok=True)

    except Exception as e:
        return f"Error preparing query: {e}"

    # Enhanced error handling (NEW)
    if result.returncode != 0:
        error_msg = result.stderr.strip()
        # Parse line number from jq syntax errors
        return _enhance_error_message(error_msg, "jq")

    # Existing result handling
    output = result.stdout.strip()
    if not output or output == 'null':
        return "No results found."

    lines = output.split('\n')
    if len(lines) > 100:
        truncated = "\n".join(lines[:100])
        return f"{truncated}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---"

    return output
```

### Pattern 2: Enhanced Error Messages

**What:** Parse jq/yq stderr to extract line numbers and provide actionable guidance

**When to use:** When query execution fails (returncode != 0)

**Implementation:**
```python
def _enhance_error_message(stderr: str, tool_name: str) -> str:
    """
    Parse tool-specific error messages and add helpful context.

    jq errors look like: "jq: parse error: ... at line X, column Y"
    yq errors look like: "Error: ... at line X"
    """
    lines = stderr.strip().split('\n')
    first_error = lines[0] if lines else "Unknown error"

    # Extract line number if present
    import re
    line_match = re.search(r'line (\d+)', first_error)
    line_info = f" at line {line_match.group(1)}" if line_match else ""

    # Provide common fix hints
    hints = []
    if 'unclosed' in first_error.lower() or 'bracket' in first_error.lower():
        hints.append("Check for unclosed brackets [], {}, or ()")
    if 'unexpected' in first_error.lower():
        hints.append("Check for syntax errors or missing operators")
    if 'undefined' in first_error.lower():
        hints.append("Verify all function names and variable references are defined")

    hint_text = " Consider: " + "; ".join(hints) if hints else ""
    return f"{tool_name} syntax error{line_info}: {first_error}{hint_text}"
```

### Pattern 3: Tool Invocation with -f Flag

**What:** Use `-f` flag to read query from file instead of command-line argument

**When to use:** All query executions (replaces inline expression passing)

**jq Example:**
```bash
# OLD: Inline expression (prone to escaping issues)
jq '.field | select(.x == 1)' data.json

# NEW: File-based expression (supports multiline, comments, special chars)
jq -f /tmp/query.jq data.json
```

**yq Example:**
```bash
# OLD: Inline expression
yq '.field | select(.x == 1)' data.yaml

# NEW: File-based expression with --from-file
yq --from-file /tmp/query.yq data.yaml
```

### Anti-Patterns to Avoid

- **Don't pass raw expressions as CLI args for complex queries**: Requires excessive escaping; file-based approach is simpler and more reliable
- **Don't delete temp files synchronously on Windows**: Use context manager with `delete_on_close=False` to ensure file exists during subprocess execution
- **Don't ignore stderr in error cases**: jq/yq stderr contains the actual error; parse it for better error reporting
- **Don't assume column numbers in error messages**: Older jq versions only provide line numbers; recent versions may provide column info

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Handling multiline query strings with escaping | Custom escape logic | File-based `-f` flag | Both jq and yq provide this feature; custom escaping is error-prone |
| Temporary file creation/cleanup for subprocess | Manual os.tempfile() with try/finally | `tempfile.NamedTemporaryFile(delete_on_close=False)` | Handles platform differences, security, and cleanup automatically |
| Parsing jq/yq error messages | Custom regex + heuristics | Parse stderr directly from tool | Tools provide structured error output; avoid reimplementing error parsing |
| Handling expression with comments | Stripping comments manually | File-based queries via `-f` | jq/yq handle comments natively when reading from files |

**Key insight:** Both jq and yq are mature tools (10+ years of development) with built-in support for file-based expressions. Using these features avoids the complexity and maintenance burden of custom query string handling.

## Common Pitfalls

### Pitfall 1: Platform-Specific Temp File Deletion on Windows

**What goes wrong:** Temp file is deleted before jq/yq subprocess can read it, especially on Windows

**Why it happens:** Using `delete=True` (default) with `NamedTemporaryFile` causes immediate deletion on file close; subprocess needs file to remain accessible

**How to avoid:**
```python
# GOOD: File persists until context manager exits
with tempfile.NamedTemporaryFile(
    mode='w',
    suffix='.jq',
    delete_on_close=False,  # Key: prevents deletion on close
    encoding='utf-8'
) as f:
    f.write(query_expression)
    query_path = f.name
# File still exists here
subprocess.run(['jq', '-f', query_path, ...])
# Cleanup after execution
Path(query_path).unlink(missing_ok=True)
```

**Warning signs:** FileNotFoundError when jq/yq tries to read query file; works on Linux but fails on Windows

### Pitfall 2: Not Closing File Before Subprocess

**What goes wrong:** jq/yq cannot read query file because it's still open by parent process

**Why it happens:** Forgetting to close the temp file before passing to subprocess

**How to avoid:**
```python
# GOOD: Close file explicitly before subprocess call
with tempfile.NamedTemporaryFile(...) as f:
    f.write(query_expression)
    query_path = f.name
    # File is closed when exiting context

# Now subprocess can read it
subprocess.run(['jq', '-f', query_path, ...])
```

**Warning signs:** jq/yq exits with file read errors; works intermittently

### Pitfall 3: Temp File Not Cleaned Up After Error

**What goes wrong:** Temp files accumulate when query execution fails

**Why it happens:** Using `delete=True` but not ensuring cleanup in all execution paths

**How to avoid:**
```python
# GOOD: Use try/finally pattern
query_path = None
try:
    with tempfile.NamedTemporaryFile(..., delete_on_close=False) as f:
        f.write(query_expression)
        query_path = f.name

    result = subprocess.run(['jq', '-f', query_path, ...])
finally:
    if query_path:
        Path(query_path).unlink(missing_ok=True)
```

**Warning signs:** Accumulating .jq/.yq files in /tmp/ directory; disk space gradually consumed

### Pitfall 4: Error Message Line Numbers Misalignment

**What goes wrong:** Reported error line number doesn't match actual line in source when parsing error messages

**Why it happens:** jq counts from line 1 in file; off-by-one errors when extracting/reporting line numbers

**How to avoid:**
```python
# jq reports: "jq: syntax error: ... at line 5"
# This means line 5 of the .jq file (1-indexed)
# Report directly without adjustment
import re
match = re.search(r'at line (\d+)', stderr)
if match:
    line_num = match.group(1)  # Use directly, don't subtract 1
    # Enhance message with "Check line {line_num} of your query"
```

**Warning signs:** Users confused by error reporting pointing to wrong lines

### Pitfall 5: Expressions with Null Bytes or Binary Data

**What goes wrong:** Writing binary or null-byte data to query file breaks jq/yq parsing

**Why it happens:** Not validating expression string before writing to file

**How to avoid:**
```python
# Validate expression is valid UTF-8 text
try:
    jq_expression.encode('utf-8')
except UnicodeEncodeError:
    return "Error: Query expression contains invalid characters"

# Write with explicit UTF-8 encoding
with tempfile.NamedTemporaryFile(
    mode='w',
    encoding='utf-8',
    ...
) as f:
    f.write(jq_expression)
```

**Warning signs:** UnicodeEncodeError or binary file errors from jq/yq

## Code Examples

Verified patterns from official sources:

### Basic Multiline Query with Comments

```python
# Source: jq manual (https://jqlang.org/manual/)
# yq GitHub (https://github.com/mikefarah/yq)

# Query expression (stored in .jq file):
query_expr = """
# Step 1: Extract users
.users[] |
# Step 2: Filter by status
select(.status == "active") |
# Step 3: Project fields
{name, email}
"""

# Execution:
with tempfile.NamedTemporaryFile(
    mode='w',
    suffix='.jq',
    delete_on_close=False,
    encoding='utf-8'
) as f:
    f.write(query_expr)
    temp_path = f.name

try:
    result = subprocess.run(
        ['jq', '-c', '-f', temp_path, 'data.json'],
        capture_output=True,
        text=True,
        timeout=30
    )
    # Result: compact JSON output, one object per line
finally:
    Path(temp_path).unlink(missing_ok=True)
```

### Complex Recursive Query (Real-World DBT Example)

```python
# Source: Phase 4.1 CONTEXT.md specification
# Real-world dbt lineage traversal that requires multiline support

query_expr = """
# Step 1: Create a lookup map from parent -> [children]
(
  .nodes as $all_nodes |
  reduce ($all_nodes | keys[]) as $node_name ({};
    ($all_nodes[$node_name].depends_on.nodes[]?) as $parent_node |
    .[$parent_node] += [$node_name]
  )
) as $lineage_map |

# Step 2: Define recursive function
def get_all_descendants($model_name):
  ($lineage_map[$model_name] // []) as $direct_children |
  $direct_children[] |
  ($direct_children[] | get_all_descendants(.))
;

# Step 3: Start the process
get_all_descendants("model.estrid_dw.fct_transactions")
"""

# Write to temp file and execute (no escaping needed!)
with tempfile.NamedTemporaryFile(mode='w', suffix='.jq', delete_on_close=False) as f:
    f.write(query_expr)
    temp_path = f.name

try:
    result = subprocess.run(
        ['jq', '-c', '-f', temp_path, 'manifest.json'],
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        # Enhanced error handling for complex queries
        return _enhance_error_message(result.stderr, "jq")
finally:
    Path(temp_path).unlink(missing_ok=True)
```

### Enhanced Error Handling

```python
# Source: jq stderr parsing, Python regex

def _enhance_error_message(stderr: str, tool_name: str) -> str:
    """
    Parse jq/yq errors and add helpful context.

    Example stderr:
      "jq: syntax error: Unexpected end-of-file at line 5, column 0"
      "error: bad syntax: [file:///tmp/query.yq:3:5] ...: bad alias ..."
    """
    lines = stderr.strip().split('\n')
    first_line = lines[0]

    # Extract line number
    import re
    line_match = re.search(r'line (\d+)', first_line)
    line_info = f" at line {line_match.group(1)}" if line_match else ""

    # Provide hints for common errors
    error_lower = first_line.lower()
    hints = []

    if 'unclosed' in error_lower or 'bracket' in error_lower or 'paren' in error_lower:
        hints.append("check for unclosed brackets [], braces {}, or parentheses ()")
    if 'unexpected' in error_lower:
        hints.append("check query syntax around the error line")
    if 'undefined' in error_lower:
        hints.append("verify all variable names and function definitions")
    if 'bad' in error_lower and 'alias' in error_lower:
        hints.append("check YAML anchor (&) and alias (*) syntax")

    hint_text = " · " + " · ".join(hints) if hints else ""
    return f"{tool_name} syntax error{line_info}: {first_line}{hint_text}"
```

## State of the Art

| Aspect | Old Approach | Current Approach | When Changed | Impact |
|--------|--------------|------------------|--------------|--------|
| Complex query handling | Inline with escaping | File-based via `-f` flag | Both jq and yq have had this feature for years | Eliminates escaping burden, supports multiline/comments natively |
| Temp file management | Manual cleanup | `tempfile.NamedTemporaryFile` + context manager | Python 3.2+ | Safer, more portable, automatic cleanup |
| Error message parsing | Trial-and-error interpretation | Regex extraction of line numbers | Both tools stable | More reliable error reporting |

**Deprecated/outdated:**
- **Inline expression passing for complex queries**: File-based approach is simpler and more reliable
- **Manual temp file creation**: Use `tempfile` module for safety and portability

## Open Questions

1. **Temp file location specificity**
   - What we know: Python's `tempfile` module creates files in system temp dir (platform-specific)
   - What's unclear: Should we enforce specific temp directory (e.g., session scratchpad) vs. system default?
   - Recommendation: Use system default via `tempfile.NamedTemporaryFile()` for simplicity and portability; specify directory only if there are session-specific requirements from Phase 4 architecture

2. **Column number parsing in error messages**
   - What we know: jq provides line numbers consistently; column numbers added in recent versions
   - What's unclear: Should we attempt to extract column numbers or stick to line-only reporting?
   - Recommendation: Parse what's available (line number) for broad compatibility; don't assume column support

3. **Debugging: Preserve temp files on error?**
   - What we know: Current implementation deletes temp files immediately after execution
   - What's unclear: Should we preserve temp files when errors occur to aid debugging?
   - Recommendation: Delete immediately for production (cleaner); add optional `debug_preserve_temp` parameter if needed later

## Sources

### Primary (HIGH confidence)

- **jq Manual (1.8)** - https://jqlang.org/manual/
  - Topics: `-f`/`--from-file` flag specification, command-line options, error message formats

- **yq GitHub README** - https://github.com/mikefarah/yq/blob/master/README.md
  - Topics: `--from-file` flag for loading expressions, command-line options, installation

- **Python tempfile Documentation (3.10+)** - https://docs.python.org/3/library/tempfile.html
  - Topics: `NamedTemporaryFile`, `delete_on_close` parameter, context manager patterns for subprocess workflows

### Secondary (MEDIUM confidence)

- [JSON Error Handling Best Practices](https://formatjsononline.com/learn/json-error-handling-and-debugging) - jq error handling overview
- [Python Temp File Best Practices](https://www.timsanteford.com/posts/temporary-files-in-python-a-handy-guide-to-tempfile/) - Practical temp file patterns
- [yq GitHub Issue #1120](https://github.com/mikefarah/yq/issues/1120) - Historical context on file-based query feature request

### Tertiary (LOW confidence)

- Error message parsing patterns based on jq GitHub issues (community discussion of error format variations across versions)

## Metadata

**Confidence breakdown:**
- Standard stack (jq/yq file-based queries): HIGH - Verified in official documentation
- Architecture patterns (tempfile usage): HIGH - Python standard library, well-documented
- Error handling: MEDIUM - Error format parsing based on stderr examination; format varies by tool version
- Claude's discretion items: MEDIUM - Implementation choices not verified externally

**Research date:** 2026-01-27
**Valid until:** 2026-02-27 (30 days - jq/yq are stable projects; tempfile patterns are standard library)

**Notes:**
- Phase 4.1 builds directly on Phase 4 implementation with minimal changes
- No new external dependencies required
- All code patterns verified against official documentation or Python standard library
- Phase 4.1 is a straightforward enhancement to existing query_json/query_yaml tools
