# Phase 2: Agent Workflow Optimization - Research

**Researched:** 2026-01-26
**Domain:** LLM Tool Design, File Search
**Confidence:** MEDIUM

## Summary

This research focuses on optimizing an agent's workflow by guiding it to use a `grep` → `read` pattern for file-related tasks. The key is to provide a well-designed `grep` tool, powered by `ripgrep`, with a description that strongly encourages efficient discovery over brute-force reading. By making `grep` the path of least resistance for finding information, we can reduce token usage and improve agent performance.

The core challenge is not technical implementation, but rather the design of the tool's interface and documentation for a non-human user. The recommendations below are based on `ripgrep`'s powerful feature set and established best practices for designing tools for Large Language Models (LLMs).

**Primary recommendation:** Implement a `grep` tool using `ripgrep` with a carefully crafted description that explicitly guides the agent to use it for searching and discovery *before* attempting to read files. The tool's output should be structured to make the subsequent `read` call trivial.

## Standard Stack

The established "stack" for this problem is a single, powerful command-line tool, `ripgrep`, which will be wrapped as a tool for the agent.

### Core
| Library | Version | Purpose | Why Standard |
|---|---|---|---|
| `ripgrep` (rg) | 13.0+ | High-performance file content search | `ripgrep` is the industry standard for fast, recursive code search. It's faster than traditional `grep`, respects `.gitignore` files by default, and offers structured output formats suitable for machine parsing. |

### Supporting
There are no additional libraries required. The implementation will involve calling `ripgrep` via a Python `subprocess` and parsing its output.

**Installation:**
The system should detect if `rg` is in the `PATH`. If not, it should provide platform-specific installation instructions. The application should gracefully disable the `grep` tool if `ripgrep` is not available.

## Architecture Patterns

### Recommended `ripgrep` Invocation

The `grep` tool should be a wrapper around a `ripgrep` command. The command should be constructed to produce predictable, parsable output.

```bash
rg --vimgrep --no-heading --color=never -S --context=2 -m 10 "{pattern}" {path_or_glob}
```

-   `--vimgrep`: Produces structured output: `{file}:{line}:{column}:{text}`. This is easily parsable and directly feeds into the `read` tool.
-   `--no-heading`: Prevents printing the filename above each group of matches, ensuring every output line is in the same format.
-   `--color=never`: Strips ANSI color codes that would confuse the agent.
-   `-S`/`--smart-case`: A sensible default for case-sensitivity. Searches case-insensitively if the pattern is all lowercase.
-   `-C 2`/`--context=2`: Provides 2 lines of context before and after the match, as per requirements.
-   `-m 10`/`--max-count=10`: A defense-in-depth measure to prevent a single file from returning an overwhelming number of matches. The overall 100-match cap will be handled in the Python wrapper.

### Pattern 1: The `grep` → `read` Workflow

This is the central pattern to encourage.

1.  **Agent Goal:** Find a specific piece of information or code within the project.
2.  **Agent Action 1 (`grep`):** The agent uses the `grep` tool with a pattern.
    -   *Good:* `grep(pattern="function validate_user")`
    -   *Bad:* `list_files()` followed by `read("file1.py")`, `read("file2.py")`...
3.  **Tool Output:** The `grep` tool returns a list of matching lines, prefixed with the file path and line number.
    -   `src/auth.py:125:8:def validate_user(username, password):`
4.  **Agent Action 2 (`read`):** The agent identifies the most relevant file from the `grep` output and uses the `read` tool to get the full context.
    -   `read(file_path="src/auth.py")`

### Pattern 2: Tool Description Engineering

The tool's description is the primary mechanism for guiding the agent. It must be clear, direct, and opinionated.

**Good Description (Guides the agent):**
```json
{
  "name": "grep",
  "description": "Searches for a regex pattern in files. Use this to find specific code or text *before* reading a file. Essential for discovery. Returns results in 'file:line:match' format.",
  "parameters": {
    "pattern": "The regex pattern to search for.",
    "glob": "Optional glob pattern to filter files (e.g., '*.py', 'src/**/*')."
  }
}
```

**Bad Description (Ambiguous and unhelpful):**
```json
{
  "name": "grep",
  "description": "Runs a search command.",
  "parameters": {
    "query": "The query."
  }
}
```
The good description uses action verbs, defines the input/output, and explicitly states the desired workflow ("*before* reading a file").

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| File content search | A custom Python script that walks directories and reads files. | `ripgrep` subprocess | `ripgrep` is written in Rust and is orders of magnitude faster. It handlesgitignore rules, binary file filtering, Unicode, and parallelism correctly out of the box. A custom solution would be slow, buggy, and insecure. |
| Regex Matching | `re` module in Python for complex patterns across many files. | `ripgrep` | `ripgrep`'s regex engine is highly optimized for this exact task. Offloading the search to a dedicated binary is far more efficient. |

## Common Pitfalls

### Pitfall 1: Agent Ignores `grep` and Reads Everything
-   **What goes wrong:** The agent uses `list_files` or `glob` to get all files, then reads them one-by-one, consuming a massive number of tokens and running slowly.
-   **Why it happens:** The `grep` tool's purpose is unclear, or the agent defaults to a familiar but inefficient pattern.
-   **How to avoid:** A clear, prescriptive tool description (see above). The name `grep` itself is a strong hint for experienced developers, and the description should solidify its purpose for the agent.
-   **Warning signs:** A sequence of `list_files` -> `read` -> `read` -> ... in the agent's action history.

### Pitfall 2: Overly Broad `grep` Patterns
-   **What goes wrong:** The agent provides a very simple pattern (e.g., "import", "class", "a") which matches hundreds of lines, hitting the 100-result cap with low-quality results.
-   **Why it happens:** The agent is not being specific enough in its search.
-   **How to avoid:** The tool wrapper should return a helpful message when the result limit is hit, e.g., "100 results returned, but there were more. Try a more specific pattern." This provides feedback for the agent to refine its next attempt.
-   **Warning signs:** The `grep` tool repeatedly returns the 100-result cap message.

## Code Examples

### Agent-Facing Tool Definition
```python
# This is a conceptual example of the tool's definition
class GrepTool:
    name = "grep"
    description = (
        "Searches for a regex pattern in files. Use this to find specific code "
        "or text *before* reading a file. Essential for discovery. Returns "
        "results in 'file:line:match' format."
    )

    def run(self, pattern: str, glob: str = None) -> str:
        # ... implementation calls ripgrep subprocess ...
        pass
```

### Example `ripgrep` Invocation in Python
```python
import subprocess

def run_ripgrep(pattern, path="."):
    command = [
        "rg",
        "--vimgrep",
        "--no-heading",
        "--color=never",
        "-S",
        "--context=2",
        "-m", "10", # Max 10 matches per file
        pattern,
        path
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        lines = result.stdout.strip().split('\n')
        # Further processing to cap total lines at 100
        return "\n".join(lines[:100])
    except FileNotFoundError:
        return "Error: `rg` (ripgrep) command not found. Please install it."
    except subprocess.TimeoutExpired:
        return "Error: Search timed out. Your pattern may be too complex or broad."
    except subprocess.CalledProcessError as e:
        return f"Error executing ripgrep: {e.stderr}"
```

## Open Questions

1.  **Optimal JSON vs. vimgrep format:** The `--json` flag for `ripgrep` could provide a more robust, extensible output format. My research tools were unable to confirm the details of this flag. The `--vimgrep` format is a safe and effective starting point, but JSON would be better for extensibility (e.g., adding byte offsets, multiple matches per line).
   -   **Recommendation:** Start with `--vimgrep`. If the agent has trouble parsing it or more complex data is needed later, investigate the `--json` flag with access to the full documentation.

## Sources

### Primary (HIGH confidence)
-   Partial content from `ripgrep` man page via `webfetch`: `https://mankier.com/1/rg`

### Tertiary (LOW confidence)
-   Web searches for "best practices for writing llm tool descriptions" failed to execute, so the guidance in "Architecture Patterns" is based on my training data and general prompt engineering principles, not on verifiable external sources from 2026. This is the main source of the MEDIUM confidence rating for this report.

## Metadata

**Confidence breakdown:**
-   Standard stack: HIGH - `ripgrep` is the undisputed standard.
-   Architecture: MEDIUM - The `ripgrep` command is solid, but the tool description advice is based on general principles, not specific, recent research.
-   Pitfalls: MEDIUM - These are common failure modes for agents, but their specific manifestation with this tool is projected.

**Research date:** 2026-01-26
**Valid until:** 2026-07-26
