# Phase 5: enhance Section-Aware Reading - Research

**Researched:** 2026-01-27
**Domain:** Python, File I/O, Regular Expressions
**Confidence:** HIGH

## Summary

This research outlines the implementation strategy for enhancing the `read_files` and `grep_content` tools based on the decisions in `CONTEXT.md`. The core of the implementation relies on Python's standard libraries, ensuring no new external dependencies are required.

For `read_files`, the approach uses a memory-efficient combination of file iterators and `itertools.islice` to read from a specific start line until a regex pattern is found or the end of the file is reached. For `grep_content`, a similar line-by-line scanning technique is recommended to find the `section_end_hint` after a primary match is located.

The primary implementation challenge is carefully managing the conversion between 1-based line numbers (from the tool's interface) and 0-based indices used by Python's slicing and iteration tools. The provided code examples and patterns directly address this to prevent common off-by-one errors.

**Primary recommendation:** Use `itertools.islice` for all partial-file reading operations to ensure memory safety and performance, even with very large files.

## Standard Stack

The established libraries/tools for this domain are all part of the Python 3 standard library.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `re` | Python 3 | Regular expression operations | The standard and most powerful regex engine available in Python. |
| `itertools` | Python 3 | Memory-efficient iteration | Provides `islice` for creating an iterator over a slice of a file without reading the entire file into memory. This is the canonical solution for this problem. |

**Installation:**
No new installations are required. These are built-in Python modules.

## Architecture Patterns

### Recommended Project Structure
This change modifies existing tool functions. No change to the project file structure is anticipated. The logic should be implemented within the existing functions for `read_files` and `grep_content`.

### Pattern 1: Bounded Section Reading (`read_files`)
**What:** Reads a section of a file from a `start_line` until a line matching a `read_to_next_pattern` regex is found. It's designed to be memory-efficient.
**When to use:** When implementing the new functionality in the `read_files` tool.

**Logic:**
1.  Validate that `end_line` and `read_to_next_pattern` are not used simultaneously.
2.  Open the file and create a memory-efficient iterator starting at the target line using `itertools.islice(file_handle, start_line - 1, None)`. The `start_line - 1` correctly converts the 1-based input to a 0-based index.
3.  Read the first line from the iterator. If it's `None`, the `start_line` was invalid (greater than file length).
4.  Loop through the remainder of the iterator, appending lines to a result list.
5.  For each line, perform `re.search(pattern, line)`. If it matches, the boundary is found. Stop reading and break the loop. The line with the match is *not* included.
6.  If the loop finishes, the pattern was not found. The result includes all lines to the end of the file. Append the required informational note.

### Pattern 2: Section End Hinting (`grep_content`)
**What:** After finding a primary grep match, this pattern scans forward from that point to find the next line that matches a set of section boundary patterns.
**When to use:** When adding the `section_end_hint` feature to the `grep_content` tool.

**Logic:**
1.  After finding a grep match on `match_line_number`.
2.  Open the file again and create a new iterator that starts on the line *after* the match: `itertools.islice(file_handle, match_line_number, None)`. (Note: `match_line_number` is already 0-indexed if it comes from `enumerate`, otherwise convert it). If it's 1-based, use `islice(f, match_line_number, None)`.
3.  Iterate through this new slice of the file.
4.  For each line, check it against every regex in the `section_patterns` list.
5.  The first line that matches any pattern becomes the `section_end_hint`. Record its line number and break the search.
6.  If the end of the file is reached with no match, no hint is generated for that grep result.

### Anti-Patterns to Avoid
- **`file.readlines()`:** Do not use `file.readlines()` on the whole file. This loads the entire file into memory and defeats the purpose of section-aware reading, making the tool vulnerable to crashes with large files.
- **Manual Line Counting:** Do not read from the beginning of the file and manually count lines in a `for` loop to find the start position. This is inefficient. `itertools.islice` handles this optimally.

## Don't Hand-Roll

Problems that look simple but have existing, robust solutions.

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Partial File Reading | A loop that reads from line 1 and discards lines until `start_line` is reached. | `itertools.islice()` | `islice` is highly optimized in C for this exact purpose. It efficiently advances the file iterator to the desired start position without loading intermediate lines into memory. |
| Regex Matching | String methods like `if "pattern" in line:` or custom parsing. | `re.search()` | The `re` module is the correct tool for handling regular expressions. Simple string matching cannot handle regex syntax and is not what the feature requires. |

**Key insight:** Python's standard library is powerful and optimized for I/O. Trusting its iterators and tools leads to more robust and performant code than manual implementations.

## Common Pitfalls

### Pitfall 1: 1-Based vs. 0-Based Indexing
**What goes wrong:** Off-by-one errors in output. The tool might start reading from the wrong line, or stop one line too early or too late.
**Why it happens:** The tool interface uses 1-based line numbers for human readability (e.g., "start at line 10"). Python's list indices, enumeration, and `itertools.islice` are 0-based.
**How to avoid:** Always subtract 1 from the incoming `start_line` parameter before passing it to `itertools.islice`. When reporting line numbers back to the user (e.g., in the hint), ensure they are converted back to 1-based.
**Warning signs:** Test cases that fail at the boundaries (first line, last line, pattern on the line right after `start_line`).

### Pitfall 2: Re-using a Consumed Iterator
**What goes wrong:** Subsequent operations on the same file handle or iterator produce no results or start from an unexpected position.
**Why it happens:** A file iterator can only be traversed once. After a loop runs to completion, the iterator is "exhausted."
**How to avoid:** For the `grep_content` hint logic, which needs to scan forward from each match, create a *new* `islice` iterator for each hint calculation. Do not try to reuse a single iterator for the entire file.

## Code Examples

Verified patterns from official sources and best practices.

### Bounded Section Reading (`read_files`)
```python
import re
import itertools

def read_section_from_file(filepath: str, start_line: int, read_to_next_pattern: str):
    """
    Reads from start_line until a line matches read_to_next_pattern.
    Source: Python Docs on itertools.islice and re
    """
    if start_line < 1:
        # Or return a structured error as per requirements
        raise ValueError("start_line must be 1 or greater.")

    lines_to_read = []
    pattern_found = False
    note = ""

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # islice uses 0-based indexing, so subtract 1
            line_iterator = itertools.islice(f, start_line - 1, None)

            # Eagerly read the first line to ensure it's included
            try:
                first_line = next(line_iterator)
                lines_to_read.append(first_line)
            except StopIteration:
                # This means start_line is > number of lines in file
                # Return structured error as per requirements
                return [], "Error: start_line is beyond the end of the file."

            # Scan subsequent lines for the pattern
            for line in line_iterator:
                if re.search(read_to_next_pattern, line):
                    pattern_found = True
                    break
                lines_to_read.append(line)

        if not pattern_found:
            note = f"Note: Pattern '{read_to_next_pattern}' not found after line {start_line}. Read to end of file."

        return "".join(lines_to_read), note

    except FileNotFoundError:
        return [], "Error: File not found."
```

### Section End Hinting (`grep_content`)
```python
import re
import itertools

def find_next_section_end(filepath: str, after_line_num: int, section_patterns: list[str]) -> int | None:
    """
    Finds the line number of the first line matching any section_pattern
    that occurs after after_line_num.
    Source: Python Docs on itertools.islice and re
    """
    if not section_patterns:
        return None

    # after_line_num is 1-based from the user's perspective
    # islice is 0-based, so this starts it on the *next* line.
    start_index = after_line_num

    with open(filepath, 'r', encoding='utf-8') as f:
        line_iterator = itertools.islice(f, start_index, None)
        
        # We need to track the actual line number
        current_line_num = start_index
        for line in line_iterator:
            current_line_num += 1
            for pattern in section_patterns:
                if re.search(pattern, line):
                    return current_line_num # Return 1-based line number

    return None # No pattern found
```

## Open Questions

There are no significant open questions. The implementation path is clear and relies on the standard library. The `CONTEXT.md` provides all necessary specificity.

## Sources

### Primary (HIGH confidence)
- **Python Official Documentation:** For `re` module behavior.
- **Python Official Documentation:** For `itertools.islice` for memory-efficient file slicing.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Core Python libraries are the unambiguous choice.
- Architecture: HIGH - The iterator-based patterns are standard Python practice for this type of task.
- Pitfalls: HIGH - The 1-based vs. 0-based indexing issue is a well-known and documented problem in programming.

**Research date:** 2026-01-27
**Valid until:** 2027-01-27 (These Python standard library features are stable).
