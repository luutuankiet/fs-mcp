# fs-mcp Enhancement Spec: Section-Aware Reading

**Created:** 2026-01-27
**Author:** Discussion between user and Claude (Phase 1.7 context gathering)
**For:** fs-mcp server maintainer

## Vision

Enable AI agents to efficiently read **bounded sections** from structured markdown files without calculating end boundaries themselves.

### The Problem We're Solving

Current workflow requires agents to perform **multi-step inference**:

```python
# Step 1: Find what we want
grep_content(pattern=r"\[DECISION\]", search_path="WORK.md")
# Returns: Line 120

# Step 2: Find ALL boundaries to calculate end
grep_content(pattern=r"^\[LOG-", search_path="WORK.md")
# Returns: Lines 100, 120, 145, 170, 200

# Step 3: Agent must reason: "120 is my start, next is 145, so end = 144"

# Step 4: Finally read
read_files([{"path": "WORK.md", "start_line": 120, "end_line": 144}])
```

**Problems with this approach:**
1. **Weaker agents fail at Step 3** — inference "next match - 1" is error-prone
2. **4 API calls** when it should be 2
3. **Token waste** — grep returns ALL matches when we only need the next one
4. **Agents skip the calculation** and either read to EOF or read fixed chunks

### The Solution

Let the MCP server calculate "where does this section end?" so agents just say **what they want**, not **how to calculate it**.

```python
# New workflow (2 calls, no inference needed):
grep_content(pattern=r"\[DECISION\]", search_path="WORK.md")
# Returns: Line 120

read_files([{
    "path": "WORK.md",
    "start_line": 120,
    "read_to_next_pattern": r"^\[LOG-"
}])
# Server finds next [LOG- and stops there
```

---

## Spec: `read_files` Enhancement

### New Parameter: `read_to_next_pattern`

```python
class FileReadRequest(BaseModel):
    path: str
    head: Optional[int] = None
    tail: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    # NEW PARAMETER
    read_to_next_pattern: Optional[str] = None
```

### Behavior

When `read_to_next_pattern` is provided:

1. **Start reading** from `start_line` (required when using this parameter)
2. **Scan forward** line by line, looking for a line that matches the regex pattern
3. **Stop reading** at the line BEFORE the match (the matched line belongs to the NEXT section)
4. **If no match found** → read to end of file (last section case)

### Implementation Pseudocode

```python
def read_with_boundary(file_path, start_line, pattern):
    lines = file_path.read_text().splitlines()
    start_idx = start_line - 1  # Convert to 0-indexed

    # Default: read to end of file
    end_idx = len(lines)

    # Scan forward from start_line + 1 (don't match the starting line itself)
    regex = re.compile(pattern)
    for i in range(start_idx + 1, len(lines)):
        if regex.match(lines[i]):
            end_idx = i  # Stop BEFORE this line
            break

    return "\n".join(lines[start_idx:end_idx])
```

### Edge Cases

| Scenario | Behavior | Example |
|----------|----------|---------|
| Pattern found | Stop at line before match | Start: 120, Pattern matches line 145 → Read 120-144 |
| Pattern NOT found | Read to EOF | Start: 200, Pattern never matches → Read 200-end |
| Start line IS last section | Read to EOF | Same as above |
| Pattern on immediate next line | Read single line | Start: 120, Pattern matches line 121 → Read only line 120 |
| Invalid start_line | Error | start_line > total lines → Return error |

### Parameter Validation

```python
if read_to_next_pattern is not None:
    if start_line is None:
        raise ValueError("start_line is required when using read_to_next_pattern")
    if end_line is not None:
        raise ValueError("Cannot specify both end_line and read_to_next_pattern")
    if head is not None or tail is not None:
        raise ValueError("Cannot mix head/tail with read_to_next_pattern")
```

### Updated Docstring

```python
@mcp.tool()
def read_files(files: List[FileReadRequest], large_file_passthrough: bool = False) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    Prefer relative paths.

    **Workflow Synergy with `grep_content`:**
    This tool is the second step in the efficient "grep -> read" workflow. After using
    `grep_content` to find relevant files and line numbers, use this tool to perform a
    targeted read of only those specific sections.

    **SECTION-AWARE READING (RECOMMENDED):**

    When reading structured markdown files (like session logs, documentation, etc.),
    use `read_to_next_pattern` to automatically read until the next section boundary.
    This eliminates the need to calculate end_line yourself.

    Example - Reading a log entry:
    ```python
    # Step 1: Find the decision entry
    grep_content(pattern=r"\[DECISION\]", search_path="WORK.md")
    # Output: File: WORK.md, Line: 120

    # Step 2: Read from that line to the next log entry
    read_files([{
        "path": "WORK.md",
        "start_line": 120,
        "read_to_next_pattern": r"^\[LOG-"
    }])
    # Reads lines 120-144 (stops when line 145 matches ^\[LOG-)
    ```

    Example - Reading a markdown section:
    ```python
    # Step 1: Find the section
    grep_content(pattern=r"^## Implementation", search_path="README.md")
    # Output: File: README.md, Line: 45

    # Step 2: Read until next header
    read_files([{
        "path": "README.md",
        "start_line": 45,
        "read_to_next_pattern": r"^## "
    }])
    # Reads the entire "## Implementation" section
    ```

    **Common boundary patterns:**
    - Markdown headers (any level): r"^#+ "
    - Level 2 headers only: r"^## "
    - Log entries: r"^\[LOG-"
    - XML-style tags: r"</section>"
    - Blank line (paragraph boundary): r"^$"

    **When NOT to use `read_to_next_pattern`:**
    - When you already know the exact end_line
    - When reading entire small files (omit all line parameters)
    - When using head/tail for sampling

    **LARGE FILE HANDLING:**
    [... existing large file documentation ...]

    Args:
        files: A list of file read requests. Each request can include:
            - path (required): File path to read
            - start_line: Line number to start reading from (1-indexed)
            - end_line: Line number to stop reading at (inclusive)
            - read_to_next_pattern: Regex pattern - read until a line matches this
            - head: Read first N lines
            - tail: Read last N lines
        large_file_passthrough: If False (default), blocks reading large JSON/YAML files.
    """
```

---

## Spec: `grep_content` Enhancement (OPTIONAL - P2)

This enhancement is lower priority but adds convenience for section-aware workflows.

### New Output Field: `section_end_hint`

When the grep pattern matches what appears to be a section start (header or log entry), include a hint about where that section might end.

**Current output:**
```
File: WORK.md, Line: 120
---
[LOG-015] - [2026-01-27 10:00] - [DECISION] - Task: MODEL-A
---
```

**Enhanced output:**
```
File: WORK.md, Line: 120, Section-End-Hint: 144 (next: ^\[LOG-)
---
[LOG-015] - [2026-01-27 10:00] - [DECISION] - Task: MODEL-A
---
```

### Implementation

```python
# After finding a match, look ahead for common section boundaries
section_patterns = [
    (r"^\[LOG-", "log entry"),
    (r"^## ", "level 2 header"),
    (r"^# ", "level 1 header"),
]

for pattern, pattern_type in section_patterns:
    next_match = find_next_match(file_path, line_number + 1, pattern)
    if next_match:
        section_end = next_match - 1
        output += f", Section-End-Hint: {section_end} (next: {pattern})"
        break
```

### Why "Hint"?

It's called `Section-End-Hint` (not `Section-End`) because:
1. It's based on heuristics (common patterns), not user specification
2. The user might want different boundaries
3. It's guidance, not authoritative

Agents can use the hint directly OR ignore it and use `read_to_next_pattern` with their own pattern.

---

## Usage Examples

### Example 1: Read a Specific Log Entry

**Scenario:** Agent found `[DECISION]` at line 120, wants full entry content.

```python
# grep found: Line 120
read_files([{
    "path": "WORK.md",
    "start_line": 120,
    "read_to_next_pattern": r"^\[LOG-"
}])
```

**Result:** Lines 120-144 returned (next [LOG- is at line 145)

### Example 2: Read a Markdown Section

**Scenario:** Agent wants the "## Phase Boundary" section from CONTEXT.md

```python
# grep found: Line 7
read_files([{
    "path": "CONTEXT.md",
    "start_line": 7,
    "read_to_next_pattern": r"^## "
}])
```

**Result:** Lines 7-22 returned (next ## is at line 23)

### Example 3: Read Last Section (No Pattern Match)

**Scenario:** Agent reads the last section in file.

```python
# grep found: Line 189 (## Deferred Ideas - last section)
read_files([{
    "path": "CONTEXT.md",
    "start_line": 189,
    "read_to_next_pattern": r"^## "
}])
```

**Result:** Lines 189-end returned (no more ## found, reads to EOF)

### Example 4: Read to Blank Line (Paragraph Boundary)

**Scenario:** Agent wants just the first paragraph of a section.

```python
read_files([{
    "path": "README.md",
    "start_line": 10,
    "read_to_next_pattern": r"^$"
}])
```

**Result:** Reads until first blank line

### Example 5: Fallback When No Grep Tool

**Scenario:** Agent doesn't have grep_content, but knows the file structure.

```python
# Agent knows Current Understanding is always lines 1-30 in WORK.md
# But doesn't know exact end... use pattern-aware read
read_files([{
    "path": "WORK.md",
    "start_line": 1,
    "read_to_next_pattern": r"^## 2\."  # Read until "## 2. Key Events Index"
}])
```

---

## Graceful Degradation

If `read_to_next_pattern` is not implemented yet, agents can fall back to:

1. **Fixed chunk size:** `read_files([{"path": "X", "start_line": 120, "end_line": 170}])` — reads 50 lines
2. **Read to EOF:** `read_files([{"path": "X", "start_line": 120}])` — reads from 120 to end
3. **Manual calculation:** Agent greps for boundaries and calculates end_line

The docstring should document the recommended pattern. Even without the code change, agents that read the docstring will understand the workflow.

---

## Priority Order

1. **P0: Update `read_files` docstring** — Document the grep→read workflow with examples. Zero code changes, immediate benefit.

2. **P1: Add `read_to_next_pattern` to `read_files`** — Core enhancement. Enables section-aware reading.

3. **P2: Add `Section-End-Hint` to `grep_content`** — Nice-to-have. Reduces agent inference even further.

---

## Testing Checklist

After implementing, verify:

- [ ] `read_to_next_pattern` with pattern found → stops at correct line
- [ ] `read_to_next_pattern` with pattern NOT found → reads to EOF
- [ ] `read_to_next_pattern` combined with `start_line` → works correctly
- [ ] Error when `read_to_next_pattern` used without `start_line`
- [ ] Error when `read_to_next_pattern` used with `end_line`
- [ ] Error when `read_to_next_pattern` used with `head` or `tail`
- [ ] Works with log entry pattern `^\[LOG-`
- [ ] Works with header pattern `^## `
- [ ] Works with any-header pattern `^#+ `

---

## Context

This spec was created during Phase 1.7 of the GSD-lite project (Refactor Artifacts for Grep Synergy). The goal is to optimize markdown artifacts for grep-first workflows, enabling efficient non-linear retrieval by AI agents.

The workflow-side changes (PROTOCOL.md teaching agents the grep-first pattern) will be implemented separately. This spec covers only the MCP server enhancements.
