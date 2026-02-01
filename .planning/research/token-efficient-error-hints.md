# Token-Efficient Error Feedback for Code Editing Tools

**Research Date:** 2026-02-01
**Domain:** MCP filesystem tools, AI code editing, error handling
**Overall Confidence:** HIGH (multiple authoritative sources verified)

---

## Executive Summary

When a find-and-replace/match operation fails in a code editor tool, the current fs-mcp approach of dumping the entire file content (for files < 5000 lines) is **token-inefficient** and creates context window pressure. This research surveys best practices from Aider, Cursor, RooCode, and IDE patterns to identify token-efficient alternatives that provide helpful context without content dumps.

**Key Finding:** The most effective approach combines multiple strategies in a layered fashion:
1. **Fuzzy matching suggestions** ("did you mean X?")
2. **File structure outline** (class/function signatures)
3. **Line number context** around similar partial matches
4. **Targeted hints** based on error type

---

## Current State Analysis

### fs-mcp Current Behavior

From `/home/user/fs-mcp/src/fs_mcp/edit_tool.py` (lines 196-212):

```python
if prep_result.error_type == "validation_error":
    p = Path(path)
    if p.exists():
        content = p.read_text(encoding='utf-8')
        line_count = content.count('\n') + 1
        if line_count < 5000:
            error_response["file_content"] = content
            error_response["hint"] = f"File has {line_count} lines. Content included above..."
        else:
            error_response["hint"] = f"File has {line_count} lines (too large to include)..."
```

**Problems with this approach:**
- A 3000-line file at ~4 chars/token = 3000 tokens consumed just for error feedback
- Wastes context window on content the agent may have already seen
- No intelligent guidance on *where* to look or *what went wrong*
- Threshold of 5000 lines is arbitrary and still allows large token dumps

---

## Strategy 1: Fuzzy Matching Suggestions

### The Pattern

When `match_text` is not found exactly, use string similarity algorithms to find close matches and suggest "did you mean X?".

**Source:** [Python difflib documentation](https://docs.python.org/3/library/difflib.html)

### Implementation: `difflib.get_close_matches()`

Python's built-in `difflib` module provides `get_close_matches()`:

```python
from difflib import get_close_matches, SequenceMatcher

def find_similar_blocks(match_text: str, file_content: str, cutoff: float = 0.6) -> list:
    """Find text blocks in file that are similar to match_text."""
    lines = file_content.split('\n')
    match_lines = match_text.split('\n')
    match_len = len(match_lines)

    candidates = []
    for i in range(len(lines) - match_len + 1):
        block = '\n'.join(lines[i:i + match_len])
        ratio = SequenceMatcher(None, match_text, block).ratio()
        if ratio >= cutoff:
            candidates.append({
                'line_start': i + 1,
                'line_end': i + match_len,
                'similarity': ratio,
                'preview': block[:200] + '...' if len(block) > 200 else block
            })

    # Return top 3 matches sorted by similarity
    return sorted(candidates, key=lambda x: x['similarity'], reverse=True)[:3]
```

### Error Message Format

```json
{
  "error": true,
  "error_type": "no_match",
  "message": "No exact match found for 'match_text'.",
  "suggestions": [
    {
      "line_start": 45,
      "line_end": 48,
      "similarity": 0.85,
      "preview": "def process_data(self, data: List[str]):\n    # Similar but with different param..."
    }
  ],
  "hint": "Found 1 similar block at lines 45-48 (85% match). Common issues: whitespace, indentation, or outdated content. Use read_files([{'path': '...', 'start_line': 45, 'end_line': 48}]) to verify."
}
```

### Token Cost

- **Current approach:** 3000+ tokens (full file)
- **Fuzzy match suggestion:** ~100-200 tokens (3 suggestions with previews)
- **Savings:** 90-95% reduction

---

## Strategy 2: File Structure Outline

### The Pattern

Instead of dumping file content, provide a structural outline showing class names, function signatures, and their line numbers. The agent can then do a targeted read.

**Sources:**
- [TLDR-Code](https://github.com/csimoes1/tldr-code) - Signature extraction for LLM context
- [Tree-sitter Code Navigation](https://tree-sitter.github.io/tree-sitter/4-code-navigation.html)

### Implementation Approaches

#### Option A: Regex-Based (Simple, No Dependencies)

```python
import re

def extract_outline_python(content: str) -> list:
    """Extract Python class and function signatures with line numbers."""
    outline = []
    lines = content.split('\n')

    patterns = [
        (r'^class\s+(\w+).*:', 'class'),
        (r'^def\s+(\w+)\s*\(([^)]*)\).*:', 'function'),
        (r'^\s+def\s+(\w+)\s*\(([^)]*)\).*:', 'method'),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, symbol_type in patterns:
            match = re.match(pattern, line)
            if match:
                outline.append({
                    'type': symbol_type,
                    'name': match.group(1),
                    'line': i,
                    'signature': line.strip()[:100]  # Truncate long signatures
                })

    return outline
```

#### Option B: Tree-sitter (Accurate, Language-Aware)

Tree-sitter provides incremental parsing with error recovery, making it ideal for incomplete or in-progress code.

**Source:** [Zed Editor Blog - Syntax-Aware Editing](https://zed.dev/blog/syntax-aware-editing)

```python
# Requires: pip install tree-sitter tree-sitter-python
from tree_sitter import Language, Parser

def extract_outline_treesitter(content: str, language: str) -> list:
    """Extract symbols using tree-sitter for accurate parsing."""
    # Implementation varies by language
    # Returns: [{'type': 'function', 'name': 'foo', 'line': 10, 'end_line': 25}, ...]
```

### Error Message Format with Outline

```json
{
  "error": true,
  "error_type": "no_match",
  "message": "No match found for 'match_text'.",
  "file_outline": [
    {"type": "class", "name": "RooStyleEditTool", "line": 30, "end_line": 71},
    {"type": "method", "name": "__init__", "line": 32, "end_line": 33},
    {"type": "method", "name": "count_occurrences", "line": 35, "end_line": 36},
    {"type": "method", "name": "_prepare_edit", "line": 41, "end_line": 71},
    {"type": "function", "name": "propose_and_review_logic", "line": 74, "end_line": 417}
  ],
  "hint": "File structure shown above. Use read_files with start_line/end_line to examine specific sections."
}
```

### Token Cost

- **Current approach:** 3000+ tokens
- **Outline approach:** ~50-150 tokens (depending on file complexity)
- **Savings:** 95-98% reduction

---

## Strategy 3: Line Number Context Around Matches

### The Pattern

When the exact match fails but partial matches exist, show line numbers and a small context window around potential matches.

**Source:** This is how `grep_content` already works in fs-mcp with its "section end hint" feature.

### Implementation

```python
def find_partial_matches(match_text: str, content: str, context_lines: int = 2) -> list:
    """Find lines containing key phrases from match_text and return with context."""

    # Extract distinctive phrases (non-whitespace, 3+ words)
    key_phrases = extract_key_phrases(match_text)

    lines = content.split('\n')
    matches = []

    for phrase in key_phrases:
        for i, line in enumerate(lines):
            if phrase.lower() in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                matches.append({
                    'phrase': phrase,
                    'line': i + 1,
                    'context': '\n'.join(f"{start+j+1}: {lines[start+j]}"
                                        for j in range(end - start))
                })

    return matches[:5]  # Limit to 5 matches
```

### Error Message Format

```json
{
  "error": true,
  "error_type": "no_match",
  "message": "No exact match found.",
  "partial_matches": [
    {
      "phrase": "def _prepare_edit",
      "line": 41,
      "context": "39:     return content.count(substr) if substr else 0\n40: \n41:     def _prepare_edit(self, file_path: str, match_text: str..."
    }
  ],
  "hint": "Found partial match 'def _prepare_edit' at line 41. Your match_text may be outdated or have whitespace differences."
}
```

---

## Strategy 4: Error-Type-Specific Hints

### The Pattern

Different error conditions require different guidance. Provide targeted hints based on the specific failure mode.

**Source:** [Aider Edit Errors Documentation](https://aider.chat/docs/troubleshooting/edit-errors.html)

### Error Categories and Hints

| Error Type | Cause | Token-Efficient Hint |
|------------|-------|---------------------|
| `no_match` | match_text not found anywhere | Fuzzy suggestions + outline |
| `multiple_matches` | match_text found N times | Line numbers of all occurrences |
| `whitespace_mismatch` | Indentation/spacing differs | Show expected vs actual whitespace |
| `outdated_content` | File changed since read | Show modification timestamp + diff hint |
| `encoding_issue` | Line ending differences | Detect CRLF vs LF |

### Implementation

```python
def generate_targeted_hint(
    match_text: str,
    content: str,
    error_type: str
) -> dict:
    """Generate error-specific hints without dumping full content."""

    if error_type == "no_match":
        # Check for whitespace-only differences
        normalized_content = normalize_whitespace(content)
        normalized_match = normalize_whitespace(match_text)

        if normalized_match in normalized_content:
            return {
                "hint_type": "whitespace_mismatch",
                "message": "Match found when ignoring whitespace differences.",
                "suggestion": "Check indentation (tabs vs spaces) and line endings."
            }

        # Try fuzzy matching
        similar = find_similar_blocks(match_text, content)
        if similar:
            return {
                "hint_type": "similar_found",
                "suggestions": similar,
                "message": f"Found {len(similar)} similar blocks. Closest at line {similar[0]['line_start']}."
            }

        # Fall back to outline
        return {
            "hint_type": "no_similar",
            "outline": extract_outline(content),
            "message": "No similar text found. File structure provided for navigation."
        }

    elif error_type == "multiple_matches":
        occurrences = find_all_occurrences(match_text, content)
        return {
            "hint_type": "ambiguous_match",
            "occurrences": [{"line": occ['line'], "context": occ['preview']}
                          for occ in occurrences],
            "message": f"Found {len(occurrences)} occurrences. Add more context to make match unique.",
            "suggestion": "Include surrounding lines in match_text to distinguish the target."
        }
```

---

## Strategy 5: AST/Syntax-Tree Based Hints

### The Pattern

Use syntax tree information to provide semantic context about where the match might belong.

**Sources:**
- [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/using-parsers/)
- [Code Structure-Guided Transformer](https://dl.acm.org/doi/10.1145/3522674)

### When to Use

AST-based hints are most valuable when:
1. The match appears to be a function/class definition
2. The file has complex nesting
3. Simple text matching is insufficient

### Implementation Concept

```python
def ast_based_hint(match_text: str, file_path: str) -> dict:
    """Provide AST-aware suggestions for where match_text belongs."""

    # Parse the match_text to understand what it is
    match_type = classify_code_block(match_text)  # 'function', 'class', 'statement', etc.

    # Parse the file to get its structure
    ast = parse_file(file_path)

    if match_type == 'function':
        # Find all functions and their locations
        functions = extract_functions(ast)

        # Find function with similar name
        match_name = extract_function_name(match_text)
        similar_funcs = [f for f in functions
                        if similar(f['name'], match_name) > 0.7]

        return {
            "hint_type": "ast_function_hint",
            "looking_for": f"function '{match_name}'",
            "similar_functions": similar_funcs,
            "message": f"Found {len(similar_funcs)} functions with similar names."
        }
```

### Trade-offs

| Approach | Accuracy | Complexity | Dependencies |
|----------|----------|------------|--------------|
| Regex | Medium | Low | None |
| Tree-sitter | High | Medium | tree-sitter package |
| Full AST | Highest | High | Language-specific parsers |

**Recommendation:** Start with regex-based outline for simplicity, add tree-sitter for commonly used languages (Python, JS/TS) if more accuracy is needed.

---

## How Other Tools Handle This

### Aider

**Source:** [Aider GitHub - editblock_prompts.py](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_prompts.py)

Aider's approach:
- **Strict exact matching requirement** - every SEARCH section must EXACTLY MATCH
- **Detailed error feedback** explaining the mismatch
- **Layered matching strategies** (exact, then fuzzy)
- **Middle-out fuzzy matching** in RooCode variant: estimate region, expand outward, use Levenshtein scoring

**Key insight from Aider:** "Aider's feedback is significantly more detailed than simple failure messages. It explains the mismatch, suggests potential correct targets, reiterates the matching rules, and instructs the AI on how to proceed."

### Cursor

**Source:** [Cursor 2.0 Guide](https://skywork.ai/blog/vibecoding/cursor-2-0-ultimate-guide-2025-ai-code-editing/)

Cursor's approach:
- **Context window awareness** - shows how much context is used
- **Automatic summarization** when context limit reached
- **`.cursorignore`** for excluding irrelevant files
- **Read full files when appropriate** (2MB cap removed in 2.0)

### GitHub Copilot

**Source:** [GitHub Copilot Troubleshooting](https://docs.github.com/copilot/troubleshooting-github-copilot/troubleshooting-common-issues-with-github-copilot)

Copilot's approach:
- **Agent mode** can iterate on its own code and recognize errors
- **Generic error messages** for service issues ("Sorry, your request failed")
- **Workspace trust** requirements for edit application

### MCP Filesystem Server (cyanheads)

**Source:** [filesystem-mcp-server](https://github.com/cyanheads/filesystem-mcp-server)

Approach:
- **Zod-based validation** at API layer before operations
- **McpError** and **ErrorHandler** classes for standardized error reporting
- **Context-aware logging** with request context tracking
- **Plain text and regex support** for search/replace

---

## Recommended Implementation for fs-mcp

### Proposed Error Response Structure

```python
@dataclass
class TokenEfficientErrorResponse:
    error: bool = True
    error_type: str  # 'no_match', 'multiple_matches', 'whitespace_mismatch', etc.
    message: str     # Human-readable explanation

    # Token-efficient context (include based on error type)
    suggestions: Optional[List[FuzzySuggestion]] = None  # For no_match
    occurrences: Optional[List[LineContext]] = None       # For multiple_matches
    file_outline: Optional[List[Symbol]] = None           # Fallback structure
    whitespace_diff: Optional[str] = None                 # For whitespace issues

    # Actionable guidance
    hint: str                                              # What to do next
    recommended_action: str                                # Tool call suggestion

@dataclass
class FuzzySuggestion:
    line_start: int
    line_end: int
    similarity: float  # 0.0 to 1.0
    preview: str       # First 200 chars

@dataclass
class Symbol:
    type: str          # 'class', 'function', 'method'
    name: str
    line: int
    end_line: Optional[int] = None
    signature: Optional[str] = None  # Truncated signature
```

### Phased Implementation

**Phase 1: Fuzzy Matching** (Highest Impact, Lowest Effort)
- Add `find_similar_blocks()` using difflib
- Return top 3 suggestions with line numbers and previews
- Estimated savings: 90% token reduction

**Phase 2: File Outline** (Medium Effort)
- Implement regex-based outline for Python, JS, TS
- Include in error response when no fuzzy matches found
- Estimated savings: 95-98% token reduction

**Phase 3: Error-Type-Specific Hints** (Refinement)
- Detect whitespace mismatches
- Detect line ending issues (CRLF vs LF)
- Provide targeted remediation guidance

**Phase 4: Tree-sitter Integration** (Optional, High Accuracy)
- Add tree-sitter for accurate parsing
- Enables semantic understanding of code structure
- Provides accurate scope boundaries

---

## Token Budget Analysis

### Current Approach (5000-line file)
```
File content: ~5000 tokens
Error metadata: ~50 tokens
Total: ~5050 tokens
```

### Proposed Approach
```
Error metadata: ~50 tokens
Fuzzy suggestions (3): ~150 tokens
File outline (20 symbols): ~100 tokens
Hint message: ~50 tokens
Total: ~350 tokens

Savings: 93% reduction
```

### For Very Large Files (10000+ lines)
```
Current: Would refuse or dump 10000 tokens
Proposed: Still ~350 tokens (outline + suggestions)

Savings: 97% reduction
```

---

## Anti-Patterns to Avoid

### 1. Dumping Full File Content
**Why bad:** Wastes tokens, agent may have already seen content
**Instead:** Use fuzzy matching + outline

### 2. Generic "No match found" Errors
**Why bad:** Provides no guidance on how to fix
**Instead:** Include suggestions, line numbers, or structural hints

### 3. Arbitrary Size Thresholds
**Why bad:** Current 5000-line threshold is arbitrary
**Instead:** Use token budget approach - always provide same structured response

### 4. Ignoring Whitespace Issues
**Why bad:** Common source of match failures
**Instead:** Detect and report whitespace differences explicitly

---

## Sources

### Primary Sources (HIGH Confidence)
- [Python difflib documentation](https://docs.python.org/3/library/difflib.html)
- [Tree-sitter Code Navigation](https://tree-sitter.github.io/tree-sitter/4-code-navigation.html)
- [Aider Edit Block Prompts](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_prompts.py)
- [MCP Tools Documentation](https://modelcontextprotocol.io/docs/concepts/tools)

### Secondary Sources (MEDIUM Confidence)
- [Cursor 2.0 Guide](https://skywork.ai/blog/vibecoding/cursor-2-0-ultimate-guide-2025-ai-code-editing/)
- [TLDR-Code Signature Extraction](https://github.com/csimoes1/tldr-code)
- [Zed Editor - Syntax-Aware Editing](https://zed.dev/blog/syntax-aware-editing)
- [Token Efficiency in Claude Code Workflows](https://medium.com/@pierreyohann16/optimizing-token-efficiency-in-claude-code-workflows-managing-large-model-context-protocol-f41eafdab423)

### Additional References
- [LongCodeZip - Code Compression for LLMs](https://arxiv.org/html/2510.00446v1)
- [Error Recovery in AI Agent Development](https://www.gocodeo.com/post/error-recovery-and-fallback-strategies-in-ai-agent-development)
- [Sourcegraph - Context Retrieval Lessons](https://sourcegraph.com/blog/lessons-from-building-ai-coding-assistants-context-retrieval-and-evaluation)
- [filesystem-mcp-server](https://github.com/cyanheads/filesystem-mcp-server)

---

## Conclusion

The research strongly supports replacing full-file content dumps with a layered approach:

1. **Fuzzy matching** as the primary suggestion mechanism
2. **File outline** as structural context fallback
3. **Error-type-specific hints** for targeted guidance
4. **Consistent token budget** regardless of file size

This approach can achieve **90-98% token reduction** while providing **more actionable feedback** to the AI agent. The implementation can be phased, starting with fuzzy matching (highest impact, lowest effort) and progressively adding more sophisticated analysis.
