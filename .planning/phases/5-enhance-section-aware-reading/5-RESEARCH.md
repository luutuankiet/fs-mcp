# Phase 5: Enhance Section-Aware Reading - Research

**Researched:** 2026-01-27
**Domain:** Code & Structured Text Parsing
**Confidence:** HIGH

## Summary

This research investigates the best approach to enhance "section-aware reading" capabilities, moving beyond simple text matching to structural and semantic understanding of files. The goal is to identify a robust, scalable, and performant way to define, identify, and extract logical sections from various file types, such as functions in Python or sections in Markdown.

The primary recommendation is to adopt a hybrid search strategy utilizing `ripgrep` for initial fast filtering and the `tree-sitter` parsing library for deep structural analysis. This combination leverages the strengths of both tools: `ripgrep`'s raw speed for text matching and `tree-sitter`'s powerful and accurate Abstract Syntax Tree (AST) parsing. This avoids the performance cost of parsing every file for every query while providing highly accurate, language-aware results.

**Primary recommendation:** Use `tree-sitter` with language-specific grammars to parse files and execute queries that define logical "sections". Trigger this parsing only after `ripgrep` has confirmed the presence of a user's search term, using the line number from `ripgrep` to locate the relevant section in the parsed syntax tree.

## Standard Stack

The established libraries/tools for this domain are `tree-sitter` and its ecosystem of language grammars.

### Core
| Library | Version | Purpose | Why Standard |
|---|---|---|---|
| `tree-sitter` | ~0.25 | Core parsing engine and Python bindings. | Industry standard for building fast, robust, and incremental parsers. Used in major editors like Neovim and Helix. Has official Python bindings. |
| `tree-sitter-python` | Latest | Tree-sitter grammar for Python. | Official, well-maintained grammar for parsing Python code into a reliable AST. |
| `tree-sitter-markdown` | Latest | Tree-sitter grammar for Markdown. | The de-facto standard for parsing Markdown with tree-sitter. Supports CommonMark and GFM extensions. |

### Supporting
| Library | Purpose | When to Use |
|---|---|---|
| `ripgrep` | Fast text search (pre-filter) | Used in the initial step of any search to quickly find line numbers containing the target text before initiating a full parse. |

**Installation:**
The core library and per-language grammars are installed via pip. This is a significant advantage as it avoids manual compilation of grammars.

```bash
# Core library
pip install tree-sitter

# Per-language grammars
pip install tree-sitter-python
pip install tree-sitter-markdown
# Add other languages as needed (e.g., tree-sitter-json, tree-sitter-bash)
```

## Architecture Patterns

### Recommended: Hybrid Ripgrep + Tree-sitter Search

This pattern maximizes performance and accuracy by combining a fast line-based search with a slower, more detailed structural search.

**Flow:**
1.  **Fast Filter (Ripgrep):** A user query is first executed with `ripgrep` against the target file(s). This returns a list of line numbers where the search term appears. If there are no matches, the process stops.
2.  **Parse (Tree-sitter):** If `ripgrep` finds matches, the entire source file is read and parsed using the appropriate `tree-sitter` language grammar. This produces a full AST.
3.  **Define Sections (Tree-sitter Queries):** For each supported language, define a set of `tree-sitter` queries that capture what constitutes a "section".
4.  **Locate & Extract (Code Logic):**
    a. For each line number returned by `ripgrep`, find the AST node that contains that line.
    b. Traverse up from that node to find the first parent node that matches one of the predefined "section" queries.
    c. Extract the full text of this section node (from its `start_byte` to `end_byte`).
    d. Return the extracted section(s).

### Pattern: Defining Sections with Queries

Sections are defined using `tree-sitter`'s query language. These queries are stored separately and loaded at runtime.

**Example for Python (finding a function or class):**
```scm
; queries/python.scm
(function_definition) @section
(class_definition) @section
```

**Example for Markdown (finding a level 1 or 2 heading and its content):**
A query for this is more complex and involves capturing the heading and subsequent nodes.
```scm
; queries/markdown.scm
(section
  (atx_heading
    heading_level: (atx_h1_marker)
    heading_content: (_) @heading.text) @section)

(section
  (atx_heading
    heading_level: (atx_h2_marker)
    heading_content: (_) @heading.text) @section)
```
*(Note: The exact Markdown query requires knowledge of the grammar's structure for sibling nodes.)*

### Anti-Patterns to Avoid
-   **Parsing Every File:** Do not run `tree-sitter` on files that haven't first been filtered by `ripgrep`. The performance overhead is unnecessary.
-   **Regex-based Sectioning:** Avoid using regular expressions to find sections. They are brittle, error-prone, and cannot correctly handle nested structures or language syntax variations. `tree-sitter` is designed to solve this problem correctly.

## Don't Hand-Roll

Problems that look simple but have existing, robust solutions.

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Parsing source code | A custom regex or line-by-line parser. | `tree-sitter` library. | `tree-sitter` correctly and efficiently handles complex language syntax, nesting, comments, and error recovery. A hand-rolled solution will inevitably fail on edge cases. |
| Managing language grammars | Cloning and compiling grammars manually from git repos. | PyPI packages (`tree-sitter-python`, etc.). | The ecosystem provides pre-compiled wheels, simplifying dependency management and deployment. Manual compilation introduces build-time dependencies and complexity. |

## Common Pitfalls

### Pitfall 1: Grammar Management & Loading
**What goes wrong:** The application doesn't know which languages are supported or how to load the compiled grammar files.
**Why it happens:** The connection between a file extension (e.g., `.py`) and the installed `tree-sitter-python` package is not automatic.
**How to avoid:** Implement a language registry. Create a simple mapping from file extensions/language IDs to the `Language` object. This can be done with a dynamic import mechanism that loads the installed grammar packages.
**Warning signs:** `Language not found` errors; having to hard-code language loading logic for every new language.

### Pitfall 2: Overly Broad or Incorrect Queries
**What goes wrong:** `tree-sitter` queries either match nothing, or they match huge, meaningless sections of the file.
**Why it happens:** The query was written without understanding the specific AST structure produced by the language grammar. For example, `(_) @section` would match everything.
**How to avoid:** For each language, inspect the actual AST for sample files to write accurate queries. Use the `node.sexp()` method to get an S-expression representation of the tree for debugging. Queries should be tested against a suite of sample files.
**Warning signs:** Results are not useful; the entire file is returned as a single section; no sections are found in a file that clearly has them.

### Pitfall 3: Inefficient Tree Traversal
**What goes wrong:** Finding the section for a given line number is slow because the entire tree is traversed repeatedly in Python.
**Why it happens:** A naive search from the root node for every matched line number.
**How to avoid:** Use `tree.root_node.named_descendant_for_point_range()` or a similar efficient method to quickly find the smallest node that covers the line number from `ripgrep`. Once found, the upward traversal to the section boundary is very fast.
**Warning signs:** The tool becomes slow on files with many `ripgrep` matches.

## Code Examples

Verified patterns from official sources.

### Loading a Language and Parsing
```python
# Source: Official py-tree-sitter documentation
from tree_sitter import Language, Parser

# Assumes tree-sitter-python is installed
# A language registry would handle this loading more dynamically
import tree_sitter_python as tspython
PY_LANGUAGE = Language(tspython.language())

parser = Parser(PY_LANGUAGE)
tree = parser.parse(bytes("""
def my_function():
  return 1
""", "utf8"))

root_node = tree.root_node
```

### Running a Query to Find Sections
```python
# Source: Official py-tree-sitter documentation patterns
query_source = """
(function_definition
  name: (identifier) @function.name) @section
"""
query = PY_LANGUAGE.query(query_source)
captures = query.captures(tree.root_node)

for node, capture_name in captures:
    if capture_name == "section":
        print(f"Found section: {node.text.decode('utf8')}")
    if capture_name == "function.name":
        print(f"  - Function name: {node.text.decode('utf8')}")
```

## Sources

### Primary (HIGH confidence)
-   **py-tree-sitter PyPI Page:** `https://pypi.org/project/tree-sitter/` - Confirmed core library, version, and installation method.
-   **py-tree-sitter Official Docs:** `https://tree-sitter.github.io/py-tree-sitter/` - API reference for Python bindings.
-   **tree-sitter Official Docs (Queries):** `https://tree-sitter.github.io/tree-sitter/using-parsers/queries/1-syntax.html` - Authoritative source for query syntax.
-   **tree-sitter-markdown Grammar:** `https://github.com/MDeiml/tree-sitter-markdown` - Confirmed viability and approach for Markdown parsing.
