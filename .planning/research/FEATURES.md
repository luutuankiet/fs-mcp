# Feature Landscape: Ripgrep-Based MCP Grep Tool

**Domain:** AI Agent-Facing Content Search Tool
**Researched:** 2026-01-26
**Confidence:** HIGH

---

## Table Stakes

Features that agents (and the pattern they follow) depend on. Missing any = tool feels incomplete or unusable.

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|-----------|--------------|-------|
| **Regex Pattern Matching** | Core search capability. Agents need to find code by pattern (function names, imports, error messages, etc.) | Low | Ripgrep built-in | Use ripgrep's regex engine (Rust-based, SIMD-optimized). Don't re-implement. |
| **Line Numbers in Results** | Agents *must* know line numbers to fetch exact content via `read_files()`. Without this, agents can't navigate to matches. | Low | Ripgrep `-n` flag | This is critical for the grep → read workflow pattern. |
| **Context Lines (-A, -B, -C)** | Agents need surrounding code to understand match context without an extra read call. Typical pattern: 2-3 lines before/after. | Low | Ripgrep `-A`, `-B`, `-C` flags | Keep defaults conservative (2-3 lines) to avoid bloat. Agents should be able to customize. |
| **File Path in Results** | Agents need to know which files matched. Essential for navigation and follow-up reads. | Low | Ripgrep built-in | Return relative paths (agent-friendly). |
| **Recursion (Directory Traversal)** | Agents explore unfamiliar codebases. Must search entire directory trees, not just single files. | Low | Ripgrep built-in with `-r` | Should be default behavior. |
| **Respecting .gitignore** | Agents shouldn't waste time searching generated files, node_modules, .venv, etc. This is a usability win—prevents noise. | Low | Ripgrep built-in | Out-of-box behavior. Don't override unless explicitly needed. |
| **Bounded Output (Max Matches)** | Uncapped results = context overflow. A common pitfall. Must limit total matches returned (e.g., first 100 matches). | Medium | Ripgrep `--max-count` or post-processing | Critical for token efficiency. Start with sane default (50-100 matches). |
| **Case-Insensitive Search** | Agents often don't know exact casing. `-i` flag covers this use case. | Low | Ripgrep `-i` flag | Standard grep feature. Include as parameter. |
| **Plaintext (Not JSON) Output** | Agents parse text easily. JSON is overbuilt for this use case—adds parsing overhead and tokens. | Low | Ripgrep default output | Format: `path:line:column:matched_text` with context lines before/after. Keep it simple. |
| **Human-Readable Error Messages** | If ripgrep isn't installed, agent sees cryptic "command not found". Must detect and provide platform-specific install help. | Medium | Wrapper detection + error messaging | Catch ripgrep not found → suggest `brew install ripgrep` (macOS), `apt install ripgrep` (Debian), etc. |
| **Type-Based File Filtering** | Agents often want to search only code (e.g., `-tpy` for Python, `-tjs` for JS). Saves time vs. regex escaping. | Medium | Ripgrep `-t` flag | Include as optional parameter. Document common types. |
| **Fixed-String Search** | Not all searches are regex. Fixed-string mode (`-F`) is faster and simpler for literal matching (e.g., searching imports). | Low | Ripgrep `-F` flag | Include as optional parameter. Good for beginners/weak agents. |

---

## Differentiators

Features that set fs-mcp apart. Not expected by default, but valued by agents working with large codebases.

| Feature | Value Proposition | Complexity | Implementation | Notes |
|---------|-------------------|-----------|-----------------|-------|
| **Automatic Context Tuning** | Weak agents (GPT-3.5, Gemini Flash) don't know optimal context lines. Auto-detect match density and adjust (-A/-B values) to balance context usefulness and token cost. | High | Ripgrep output analysis → heuristic adjustment | If 10+ matches in single file, reduce context (expensive). If 1-2 matches, increase context (cheap, useful). |
| **Tool Description Guidance** | Explicitly guide agents to the grep → read pattern in tool descriptions. "Use grep to narrow, then read_files to get full context." Many agents won't discover this alone. | Low | Documentation in `@mcp.tool()` docstring | This addresses the weak agent problem. Example: embed recommendation in tool description. |
| **Match Density Report** | Return summary line: "Found 47 matches in 12 files. Average 3.9 lines per file." Helps agents decide next action (narrow pattern vs. proceed with reads). | Medium | Post-process ripgrep output | Useful for agents to calibrate their strategy. Costs tokens but saves redundant searches. |
| **Multiline Pattern Support** | Some searches need to cross line boundaries (e.g., find function definitions with their signatures). Enable via ripgrep's `-U` flag (multiline mode). | Low | Ripgrep `-U` flag | Optional. Document with examples. Not table stakes because single-line patterns cover 90% of agent use cases. |
| **Search History in Session** | Track searches within a session context to avoid redundant patterns. Suggest narrowing if agent repeats similar searches. | High | Session state tracking in MCP server | Complex. Requires stateful server design. Defer to post-MVP. |
| **Encoding Detection** | Some codebases have UTF-16 or latin-1 files. Auto-detect and apply correct encoding via ripgrep's `-E` flag. | Medium | Ripgrep `-E` flag + encoding detection | Edge case. Include as optional parameter, but don't auto-detect on first MVP. |
| **Compression Support** | Codebases sometimes bundle `.tar.gz` or `.zip` archives. Search inside via ripgrep's `-z` flag. | Low | Ripgrep `-z` flag | Nice-to-have. Likely low agent demand. Defer post-MVP. |
| **Search Result Caching** | Cache recent search results to avoid redundant ripgrep calls for identical patterns. Cuts latency and tokens. | Medium | In-memory cache keyed by (pattern, path, options) | Good optimization but not MVP. Useful once patterns stabilize. |
| **Structured Output Mode (JSON)** | For agents that prefer parsing (though text is preferred), offer `--json` mode via optional parameter. | Low | Ripgrep `--json` flag | Optional. Most agents prefer plaintext. Include but don't promote. |

---

## Anti-Features

Features to **deliberately NOT build**. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Semantic/Embedding-Based Search** | Violates zero-setup constraint. Requires pre-indexing (vector DB, embeddings). Agents can't use it on cold codebases. Adds external dependencies (embedding model, inference cost). | Stick with ripgrep (text-based). It covers 90% of use cases. If agents need semantic search, they'll ask explicitly. Document the limitation. |
| **AST-Aware Code Search** | Adds complexity without MVP justification. Requires parsing per language (Python, JS, Go, etc.). Maintenance burden. Most agents don't need AST patterns yet. | Ripgrep's regex engine is powerful enough for most structure searches (find imports, function signatures, class definitions). If demand emerges, evaluate ast-grep as separate future tool. |
| **Global Configuration Files** | Tempting to let users set ripgrep config in `~/.rgignore` or project `.rgignore`. But MCP server runs as agent, not user. Breaks predictability. Agent behavior becomes environment-dependent. | No config file support in MVP. All ripgrep options passed via explicit tool parameters. Predictable. Later: discuss with roadmap if users need custom ignores. |
| **Relevance Ranking / Sorting** | Agents don't need results ranked by "relevance." Grep doesn't do this—it returns matches in file order. Ranking requires heuristics (match count, proximity, semantic scoring) that cost tokens without clear ROI. | Return results in ripgrep's natural order (file order, line order). Let agents decide if they want to narrow the pattern. Simpler. Faster. |
| **Fuzzy Matching** | Tempting for typo tolerance. But fuzzy search is slower, harder to tune, and most agents don't make typos. Adds complexity for marginal benefit. | Rely on regex patterns for flexibility. Agents can use patterns like `import.*os` to catch variations. Ripgrep is fast enough for multiple attempts. |
| **Syntax Highlighting in Output** | Agents don't parse visual formatting (colors, bold, etc.). It's noise in their context. Ripgrep's `--color=never` is the right default. | Plain text output only. No ANSI codes, no color. Keep it parseable. |
| **Custom Result Formatting** | Tempting to let agents choose output format (CSV, JSON, XML, custom templates). But each format is a maintenance burden. Agents should parse text easily. | Single output format: `path:line:column: matched_text` + context lines. Simple. Parseable. Sufficient. If agents need JSON, ripgrep has `--json` available as fallback. |
| **Search Result Persistence (DB)** | Storing search results in a database (SQLite, etc.) adds state and complexity. Violates stateless HTTP principle of MCP. | Stateless only. Results computed fresh per request. Agents handle caching if they need it. Simpler to reason about. |
| **Interactive Result Navigation** | Tools like `rg --interactive` let humans step through results. Not useful for agents. Breaks streaming. Adds overhead. | Fire-and-forget tool. Return all results at once (bounded). No interactivity. Agents either are satisfied or refine and call again. |

---

## Feature Dependencies

```
BASE LAYER (Required for any search):
├─ Regex Pattern Matching
├─ Line Numbers
└─ File Paths

CORE SEARCH (Everything grep needs):
├─ Context Lines (-A, -B, -C)
├─ Recursion
├─ .gitignore Respecting
├─ Bounded Output (Max Matches)
└─ Plaintext Output

WORKFLOW SUPPORT (Make agents effective):
├─ Human-Readable Error Messages
│  └─ (Detects ripgrep missing)
└─ Tool Description Guidance
   └─ (Instructs agents on grep → read pattern)

OPTIONAL ENHANCEMENTS:
├─ Case-Insensitive Search
├─ Type-Based Filtering
├─ Fixed-String Search
└─ Match Density Report
   └─ (Requires Core Search)

NOT IN MVP:
├─ Automatic Context Tuning
├─ Multiline Pattern Support
├─ Structured Output (JSON)
├─ Compression Support
└─ Search Caching
   └─ (Requires state management)
```

---

## MVP Recommendation

For the first release, prioritize features that make the **grep → read pattern** work reliably:

**Must Include:**
1. **Regex Pattern Matching** - Core functionality
2. **Line Numbers** - Essential for follow-up reads
3. **File Paths** - Navigation
4. **Context Lines** - Understand matches without extra read
5. **Recursion** - Search entire codebases
6. **Bounded Output** - Prevent context overflow
7. **Error Messages** - Help users understand ripgrep missing
8. **Tool Description** - Guide agents to the right pattern

**Should Include (minimal overhead):**
- Case-Insensitive Search (`-i` flag)
- Type-Based Filtering (`-t` flag)
- Fixed-String Search (`-F` flag)
- Plaintext Output (ripgrep default)

**Defer to Post-MVP:**
- Match Density Report
- Automatic Context Tuning
- Multiline Pattern Support
- JSON Output
- Compression Support
- Search Caching

---

## Token Efficiency Considerations

**Key Insight:** The grep tool's value is **token efficiency through pattern narrowing**, not through optimized output format.

| Scenario | Pattern | Token Cost | Notes |
|----------|---------|-----------|-------|
| Agent reads entire 50KB file | `read_files(path)` | ~12,500 tokens | Very expensive. Bad pattern. |
| Agent uses grep then reads 5 matching files (avg 5KB each) | `grep(pattern)` → `read_files([matches])` | ~1,250 + ~1,250 = ~2,500 tokens | 80% savings. **Gold standard.** |
| Agent uses grep with context, reads nothing | `grep(pattern, -A 3 -B 3)` | ~2,000 tokens | Useful if context suffices. Saves follow-up read. |
| Agent does 5 redundant grep calls | `grep(...)` × 5 | ~10,000 tokens | Bad pattern. Tool description should prevent this. |

**MVP Priority:** Get the basic grep → read pattern working flawlessly. Token optimization comes from **correct agent behavior**, not output formatting.

---

## Tool API Design

Based on Claude Code's Grep tool and ripgrep capabilities:

```python
@mcp.tool()
def grep(
    pattern: str,                    # Regex pattern to search
    path: str = ".",                 # Path or directory (relative OK)
    glob: Optional[str] = None,      # Filter by glob pattern (e.g., "*.py")
    type: Optional[str] = None,      # Filter by file type (e.g., "py", "js")
    context_before: int = 2,         # Lines before match (ripgrep -B)
    context_after: int = 2,          # Lines after match (ripgrep -A)
    max_matches: int = 100,          # Max matches to return
    case_insensitive: bool = False,  # -i flag
    fixed_string: bool = False,      # -F flag (literal, not regex)
    multiline: bool = False,         # -U flag (. matches newlines)
    include_binary: bool = False,    # Search binary files (default: skip)
) -> str:
    """
    Search for patterns in files using ripgrep.

    Returns matches in format:
    path/to/file:123:45: matched line text
    (with context_before and context_after lines surrounding)

    BEST PRACTICE: Use grep to narrow your search, then read_files() to get full context.
    Example:
    1. grep("import asyncio", path=".", max_matches=50)
    2. read_files([{path: matching_files[0]}, {path: matching_files[1]}])

    This pattern saves tokens by avoiding full file reads when grep context suffices.
    """
    # Implementation details in next section
```

---

## Complexity Assessment

| Feature | Implementation Effort | Risk | Notes |
|---------|---------------------|------|-------|
| **Basic ripgrep wrapper** | 2-3 hours | Low | Parse ripgrep output, handle errors. Straightforward. |
| **Bounded output** | 1 hour | Low | Count matches, cap at max_count parameter. |
| **Error detection** | 1 hour | Low | Check if `rg` command exists, catch stderr. |
| **Context lines** | 30 mins | Low | Pass `-B`, `-A`, `-C` flags to ripgrep. |
| **Type filtering** | 30 mins | Low | Pass `-t` flag to ripgrep. |
| **Tool description** | 30 mins | Low | Write clear docstring. |
| **Match density report** | 2 hours | Medium | Parse output, count files, compute averages. |
| **Automatic context tuning** | 4-6 hours | High | Heuristic logic, testing, edge cases. |
| **JSON output mode** | 1 hour | Low | Ripgrep has `--json`, just wire it. |

---

## Known Pitfalls to Avoid

### Pitfall 1: Unbounded Results
**What goes wrong:** Agent finds 10K matches, context overflows, token limit exceeded.
**Prevention:** Always apply `--max-count` (ripgrep flag). Default: 100 matches. Make it configurable but bounded.

### Pitfall 2: Missing Ripgrep
**What goes wrong:** User runs `fs-mcp` without `rg` installed. Sees generic "command not found" error. Frustrated.
**Prevention:** Detect ripgrep missing on startup OR catch subprocess error → provide helpful message with platform-specific install command.

### Pitfall 3: Weak Agents Miss the Pattern
**What goes wrong:** GPT-3.5 reads entire files with grep results available. Wastes tokens. Doesn't discover grep → read pattern.
**Prevention:** Tool description MUST explicitly recommend the pattern: "Use grep to find candidates, then read_files() to get full content. This saves tokens."

### Pitfall 4: Context Lines Too Aggressive
**What goes wrong:** `-A 10 -B 10` by default bloats output. 30 lines of context × 100 matches = 3000 lines = many tokens.
**Prevention:** Conservative defaults (2-3 lines). Let agents customize if needed. Document the token cost.

### Pitfall 5: .gitignore Surprise
**What goes wrong:** Agent expects grep to search `node_modules` for a dependency name, but ripgrep respects .gitignore and skips it.
**Prevention:** Document this behavior. It's usually correct (skip deps), but agents should know. Consider optional `--no-ignore` flag for rare cases.

### Pitfall 6: Encoding Issues
**What goes wrong:** Codebase has UTF-16 or latin-1 files. Ripgrep skips them silently or crashes.
**Prevention:** Post-MVP concern. For now, document that UTF-8 is assumed. Later: add `-E` flag for explicit encoding.

---

## Sources

- [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) - Best practices for agent tool design, token efficiency, context management
- [Claude Code Grep Tool Documentation](https://code.claude.com/docs/en/cli-reference) - Reference implementation, parameter design, output format
- [Ripgrep GitHub](https://github.com/BurntSushi/ripgrep) - Core capabilities, performance, regex engine, CLI options
- [Ripgrep User Guide](https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md) - Context lines, filtering, output modes
- [Why I'm Against Claude Code's Grep-Only Retrieval (Milvus Blog)](https://milvus.io/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens.md) - Critique and token cost analysis
- [MCP Grep Tool Search Optimization](https://nayakpplaban.medium.com/optimizing-context-with-mcp-tool-search-solving-the-context-pollution-crisis-with-dynamic-loading-224a9df57245) - MCP search patterns, context management, subagent architecture
- [ast-grep Agent Skills](https://github.com/ast-grep/agent-skill) - Alternative approach (AST-based), when to use semantic vs. text search
