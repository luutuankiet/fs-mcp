# Domain Pitfalls: Ripgrep-Based Content Search for AI Agents

**Domain:** MCP filesystem server with ripgrep-based grep tool for AI agent codebase exploration

**Researched:** 2026-01-26

**Focus:** Common mistakes when building search tools for agent-facing systems, with emphasis on context efficiency and weak agent support

---

## Critical Pitfalls

Mistakes that cause crashes, timeouts, or render the tool unusable for agents.

### Pitfall 1: Unbounded Search Results Causing Context Exhaustion

**What goes wrong:**
A single grep search returns thousands or tens of thousands of matches, consuming the agent's entire context window. The agent becomes unable to think, plan, or take further action. Observed failures at 100K+ matches causing subprocess crashes.

**Why it happens:**
- No result limiting built into the grep command
- Overly broad regex patterns (e.g., searching for common terms)
- Large codebases with highly duplicated content (minified JS, vendored dependencies, logs)
- Developer assumes "agents will just use first few results" — agents can't truncate mid-tool-response

**Consequences:**
- Tool call fails with exit code 1 or timeout
- Agent loses context and halts execution
- Entire MCP session may become unresponsive
- User experiences unexplained hangs with no actionable error message

**Prevention:**
- **Hard cap matches returned:** Enforce a maximum result count (e.g., 50-100 matches) at the ripgrep command level with `--max-count` or post-process output
- **Line limit per file:** Prevent single large matches from bloating response (e.g., grep into minified JS with thousands of matches on one line)
- **Configuration with warnings:** If result set is capped, warn the agent in output: `"Showing first 50 of 1,234 matches. Refine your pattern for more specific results."`
- **Test with pathological patterns:** Unit test grep with patterns known to match high-frequency terms to validate limits work

**Detection (Warning Signs):**
- Search tool occasionally returns HTTP 413 (payload too large) or timeout errors
- Grep results exceed 50K characters or 100+ matches
- Agent reports "context window exceeded" after grep calls
- Tool timeout threshold frequently triggered in real usage

**Phase to Address:** Phase 1 (Core grep implementation) — must be built in from the start, not retrofitted

---

### Pitfall 2: Broken Symlinks Causing Ripgrep to Fail Silently or With Exit Code 2

**What goes wrong:**
Ripgrep encounters a broken symlink during search, exits with code 2 (indicating both successful matches and errors), or fails silently. The agent receives incomplete results without knowing data is missing.

**Why it happens:**
- Ripgrep's `--follow` flag attempts to descend into symlinks
- Broken symlinks (pointing to deleted or inaccessible targets) cause ripgrep to error
- Exit code 2 (error occurred but also had matches) is ambiguous — did the search succeed or fail?
- No default handling for symlinks in MCP grep implementations

**Consequences:**
- Search results are incomplete, misleading the agent about codebase structure
- Agent makes decisions based on false negatives (assumes code doesn't exist when it's just unreachable)
- Hard to debug: agent behavior changes unpredictably based on filesystem state
- Security exposure: symlinks outside allowed directories could be followed if not validated

**Prevention:**
- **Disable symlink following by default:** Use ripgrep without `--follow` unless explicitly requested
- **Validate symlink targets:** Before running grep, scan for broken symlinks and warn user: `"Found 3 broken symlinks in search path. These will be skipped."`
- **Explicit exit code handling:** Treat ripgrep exit code 2 as a warning, not a failure. Log what errored, return partial results + warning message
- **Path validation after resolution:** For allowed paths, resolve symlinks to real paths and verify they're still in allowed directories (prevents sneaking access outside bounds)
- **Document symlink behavior in tool description:** Agents should know: "This tool does not follow symlinks. Use with `-L` flag if you need to search through linked directories."

**Detection (Warning Signs):**
- Ripgrep exit code 2 appears in logs (error + matches, not just matches)
- Search returns fewer results than expected after filesystem structure changes
- Test suite fails intermittently depending on temp directory symlink state
- Security audit reveals symlinks pointing outside allowed directories

**Phase to Address:** Phase 1 (Core grep implementation) — symlink handling must be in security design, not patched later

---

### Pitfall 3: Missing Ripgrep Binary Not Caught, No Graceful Fallback

**What goes wrong:**
User runs the grep tool on a system where ripgrep isn't installed. The MCP server crashes with "command not found" or returns an opaque error message like `"Shell returned exit code 127"` instead of a helpful install instruction.

**Why it happens:**
- Grep is implemented as subprocess call to system `rg` without prior existence check
- Error handling only catches exceptions, not stderr output
- No detection of "tool not in PATH" condition
- Agent sees generic error and doesn't know what to do
- Weak agents don't know how to solve "install ripgrep" from a system error code

**Consequences:**
- Grep tool becomes completely unusable on systems without ripgrep
- Users blame the MCP server, not their missing dependency
- Weak agents (GPT-3.5, Gemini Flash) can't recover or suggest next steps
- Breaks zero-setup promise: `uvx fs-mcp` now requires pre-installed ripgrep

**Prevention:**
- **Detect ripgrep at server startup:** Call `rg --version` during `initialize()`, cache result in global variable
- **Bail early with actionable message:** If ripgrep missing, either:
  - Disable grep tool entirely and document why in tool list
  - Return a helpful error tool that explains how to install: `"Ripgrep (rg) not found. Install with: brew install ripgrep (macOS), apt-get install ripgrep (Ubuntu), or https://github.com/BurntSushi/ripgrep#installation"`
- **Include platform-specific install commands:** In error message, detect OS and provide exact command
- **Test on minimal environments:** CI/CD test runs on container with only Python + MCP deps (no ripgrep) to catch this early
- **Document in README:** State clearly that ripgrep is an optional dependency for the grep tool

**Detection (Warning Signs):**
- "rg: command not found" in logs when grep is called
- Exit code 127 in subprocess returns
- Tool works in dev environment but fails on fresh server install
- Users report "grep doesn't work" without useful error message

**Phase to Address:** Phase 1 (Core grep implementation) — dependency detection should be first-day work, not an afterthought

---

### Pitfall 4: No Context Line Limiting, Agent Gets Wrapped Minified Files

**What goes wrong:**
A match is found in a minified JavaScript or HTML file where one logical line is 50KB+ of wrapped text. Ripgrep returns the entire line because that's what the pattern matched. The agent's response now contains 50KB of garbage in a single "line".

**Why it happens:**
- Ripgrep doesn't cap line length; it returns the matched line as-is
- Minified files, compiled output, and vendor code are common in many codebases
- `--max-columns` flag exists but isn't documented in grep tool description
- Agent has no way to know the response will be massive before the tool executes

**Consequences:**
- Context window blown by single tool call
- Text appears as wrapped garbage, unreadable to both human and agent
- Agent might hallucinate about what the match actually said
- Zero actionable information from the tool call

**Prevention:**
- **Use `--max-columns N` flag (e.g., 500):** Truncate lines longer than N characters, append `[... line truncated]` indicator
- **Document flag usage:** Tool description: `"Results are limited to 500 characters per line to prevent minified code from bloating context."`
- **Test with minified JS and CSS:** Add test files that are intentionally minified, verify grep output is readable
- **Consider `--type` filtering:** Exclude common binary/minified formats (`.min.js`, `.css`, `.json` when appropriate) from certain searches
- **Warn about truncation in output:** When a line is truncated, include note: `"Some matches on very long lines (minified code) have been truncated for readability."`

**Detection (Warning Signs):**
- Single grep result contains thousands of characters on one line
- Agent reports "I can't understand the grep output, it's unreadable"
- Tools return "line too long to display" in logs
- Search results show `[... line truncated ...]` indicators (actually a good sign you're already mitigating)

**Phase to Address:** Phase 1 (Core grep implementation) — must be part of output formatting from day one

---

### Pitfall 5: Overly Broad Tool Description, Agent Uses Grep for File Discovery

**What goes wrong:**
Tool description says "search for content in your codebase" without guidance on when to use grep vs. file search. Weak agents (GPT-3.5, Gemini Flash) call grep when they should call `search_files` (glob), burning tokens and context on unnecessary content analysis.

**Why it happens:**
- Tool descriptions are minimal: just parameter names and types
- Agents without strong reasoning can't distinguish between "find files by name" and "find content"
- No guidance on "call grep → read tool pattern" that efficient agents use
- Weak agents don't recognize that grep output tells them *where* files are, not *what they contain*

**Consequences:**
- Agent uses grep to search for filenames instead of glob-based search
- Results are noisy and include all matching files' content
- Context bloat: 100 matching files = 100 snippets instead of 100 filenames
- Weak agents don't learn the better pattern even after seeing it work
- Real searches (for actual content) get mixed with file discovery

**Prevention:**
- **Embed workflow guidance in descriptions:** Instead of just "Search for content", include:
  ```
  "Search for content matching a regex pattern. Returns matching lines with context.

  ** WORKFLOW TIP: **
  To find files containing a pattern AND read their content efficiently:
  1. Call grep(pattern) to find which files match
  2. Use read_files() on the paths returned by grep
  This pattern saves context tokens vs. reading entire files first.

  For file discovery by name only (no content matching), use search_files() instead."
  ```
- **Add "when to use" section:** Documentation with examples of correct vs. incorrect grep usage
- **Separate tools cleanly:** `search_files` for globs, `grep` for content only
- **Test with weak agents:** Run prompts through Claude-3.5-Sonnet and GPT-3.5 to verify they choose the right tool

**Detection (Warning Signs):**
- Agent calls grep searching for filenames: `grep("\.py$")` instead of `search_files("*.py")`
- Repeated full-file-read pattern appearing in logs (weak agent didn't discover grep → read workflow)
- Tool usage metrics show grep called frequently with minimal actual content matches
- Agent spends many tokens on tool selection when file discovery would be clearer

**Phase to Address:** Phase 1 (Core grep implementation) — cannot be fixed by just improving the tool, must be in description/guidance

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or agent struggles (fixable but not trivial).

### Pitfall 6: No Line Numbers in Output, Agent Can't Locate Matches in Source

**What goes wrong:**
Grep returns matching lines but no line numbers. Agent knows the line content but not where to find it in the file. Agent must either read the whole file and search manually, or call grep again with `--only-matching` to extract precise line numbers.

**Why it happens:**
- Ripgrep `--no-line-number` is default (or `-n` option forgotten)
- Developer assumes "the line content is enough" — but context is everything for agents
- Tool description doesn't mention line numbers are available

**Consequences:**
- Agent can't use grep results directly with `read_files(..., start_line=X, end_line=Y)`
- Breaks the ideal "grep → targeted read" workflow
- Agent must do extra work to find matching lines: read file, search content again
- Lost efficiency; context wasted on extra tool calls

**Prevention:**
- **Always use `rg -n` (line numbers):** Include line numbers in every ripgrep call by default
- **Format output clearly:** `filename:line_number:matching_content` (ripgrep default with `-n`)
- **Document the output format:** Tool description includes example showing line numbers
- **Validate in tests:** grep output must include `:\d+:` line number indicators
- **Make line numbers copy-paste compatible:** Format so agents can extract `filename:123` and pass to read_files

**Detection (Warning Signs):**
- Grep output is missing line numbers or colon-delimited format
- Agent makes multiple sequential grep calls trying to pinpoint exact line
- Agent reads entire file after grep when targeted read would work
- Line number extraction logic in test suite (agent shouldn't have to parse it)

**Phase to Address:** Phase 1 (Core grep implementation) — fundamental feature, must be default

---

### Pitfall 7: No Context Lines, Agent Can't Understand Match Significance

**What goes wrong:**
Grep returns only the matching line with no surrounding context. A function call is matched but without seeing the function signature, import statement, or surrounding logic, it's meaningless to the agent.

**Why it happens:**
- Ripgrep by default shows only matching lines without context
- `-B N` (before) and `-A N` (after) flags require explicit request
- Tool description doesn't mention context is available
- Dev assumes "agent will ask for more info if needed" — but context costs tokens, better to include it upfront

**Consequences:**
- Agent gets partial information, makes incorrect assumptions
- Must follow up with targeted reads to understand context
- Extra tool calls, extra tokens, slower workflows
- Weak agents don't know to ask for context, make mistakes based on isolated lines

**Prevention:**
- **Default context lines: 2-3 lines before and after:** Use `rg -B 2 -A 2` by default
- **Make configurable:** Allow agent to request more context (e.g., `-B 10 -A 10`) via parameter
- **Document context behavior:** Tool description explains default context and how to customize
- **Balance context vs. size:** 2-3 lines is usually enough; anything more explodes result size
- **Test with realistic patterns:** Verify context is meaningful (e.g., searching for function calls should show function signature context)

**Detection (Warning Signs):**
- Grep output shows isolated lines without surrounding code context
- Agent frequently follows grep with targeted reads to understand context
- Tool description silent on context availability
- Test cases show agents struggling to interpret isolated matches

**Phase to Address:** Phase 1 (Core grep implementation) — small feature, huge UX improvement

---

### Pitfall 8: No File Type Filtering, Grep Searches Binary Files and Logs

**What goes wrong:**
Grep searches through entire directory including compiled binaries, `.pyc` files, build artifacts, and enormous log files. Returns garbage results or hangs on huge binary files.

**Why it happens:**
- Ripgrep without `--type` or `--ignore-vcs` searches everything
- No default `.gitignore` respect in MCP implementations
- Agent doesn't know which file types to exclude (should be done by tool, not agent)
- Build directories, node_modules, and venv can contain millions of files

**Consequences:**
- Grep becomes slow or times out on large codebases
- Results polluted with binary garbage
- Agent must refine search multiple times to exclude noise
- Defeats purpose of fast ripgrep: poor UX negates performance gains

**Prevention:**
- **Respect `.gitignore` by default:** Use `rg --smart-case` (built-in `.gitignore` support)
- **Exclude common build artifacts:** Default excludes: `.git`, `node_modules`, `.venv`, `__pycache__`, `.pytest_cache`, `build`, `dist`, `.egg-info`
- **Exclude file types:** Use `-t` (type) filtering to search only relevant file types by default (configurable)
- **Warn about large searches:** If pattern matches millions of files, include warning: `"Search found matches in 50,000+ files. Consider narrowing the pattern or using file filtering."`
- **Test on monorepos:** Run grep on large projects (fbsource scale) and verify performance is acceptable

**Detection (Warning Signs):**
- Grep results include nonsense from binary files or logs
- Search performance degrades on larger codebases
- `.gitignore` isn't being respected (tool searches ignored files)
- Agent struggles to find signal in noise

**Phase to Address:** Phase 1 (Core grep implementation) — filtering is fundamental, not optional

---

### Pitfall 9: Agent Doesn't Know File Path Format in Results, Can't Read Matching Files

**What goes wrong:**
Grep returns `src/components/Button.tsx` but the agent tries `read_files([{"path": "src/components/Button.tsx"}])` and it fails because the MCP tool expects a different path format (relative to working directory, or absolute, or from different base).

**Why it happens:**
- Grep and read_files have different path resolution bases
- Tool descriptions don't specify what path format to use in follow-up calls
- Relative vs. absolute paths handled inconsistently
- Agent has to guess: is it relative to project root? Current working directory? Absolute?

**Consequences:**
- Grep returns paths but agent can't use them with read_files
- Extra failed tool calls, debugging steps
- Workflow breaks; agent can't follow "grep → read" pattern
- Frustration; looks like tools are broken when it's just path format mismatch

**Prevention:**
- **Use consistent path format:** Ensure grep returns paths in same format that read_files expects
- **Prefer relative paths:** All tools use paths relative to the allowed base directory
- **Document path format explicitly:** Tool descriptions include example: `"Paths are relative to your project root. Example: src/index.ts"`
- **Validate path consistency:** Test suite includes: search with grep, extract path, read with that path — must succeed
- **Normalize paths:** Tool should normalize Windows backslashes to forward slashes for compatibility

**Detection (Warning Signs):**
- Agent can't read files returned by grep due to path mismatch
- Path handling tests failing when tools are called in sequence
- Agent uses absolute paths when relative expected, or vice versa
- Tool descriptions silent on path format

**Phase to Address:** Phase 1 (Core grep implementation) — part of tool integration design

---

## Minor Pitfalls

Mistakes that cause annoyance but are fixable without major rework.

### Pitfall 10: Ripgrep Binary Name Confusion on macOS/Homebrew

**What goes wrong:**
On some systems, the ripgrep binary is installed as `ripgrep` instead of `rg`, or in non-standard path. MCP looks for `rg` in PATH, doesn't find it, disables grep tool.

**Why it happens:**
- Homebrew installs `rg` but some installers use full name `ripgrep`
- Custom builds might install to non-standard locations
- Tool only checks for `rg`, not aliased or renamed versions
- User doesn't know why grep tool disappeared

**Consequences:**
- Minor: grep tool quietly disabled, user confused
- User must manually create symlink or alias
- Not a data loss issue, but breaks user experience

**Prevention:**
- **Check multiple binary names:** Look for both `rg` and `ripgrep` in PATH
- **Allow configuration:** Environment variable to specify custom ripgrep path: `RIPGREP_PATH=/usr/local/bin/rg`
- **Clear error message:** If neither found, tell user exactly what was searched and where to find it
- **Test on macOS/Linux/Windows:** Verify binary detection works on all platforms

**Detection (Warning Signs):**
- Grep tool unavailable on some systems but not others
- User has ripgrep installed but tool isn't found
- Non-standard ripgrep paths need manual symlink setup

**Phase to Address:** Phase 1 (initialization) — low effort, high user satisfaction

---

### Pitfall 11: No Result Caching, Identical Searches Hit Disk Repeatedly

**What goes wrong:**
Agent performs same grep search multiple times (during refinement, or different agents in same MCP server). Each search rescans entire directory from disk.

**Why it happens:**
- Simple grep implementation runs `rg` every call without checking prior results
- No caching layer in MCP server
- Agent doesn't realize repeated searches are inefficient
- Time is not usually visible to agent (tool calls are fast enough to not notice)

**Consequences:**
- Minor: unnecessary disk I/O in large codebases
- Slow: high-traffic MCP server doing redundant searches
- Not critical for single-user, but degrades in multi-user scenario

**Prevention:**
- **Simple LRU cache:** Cache last N grep results (keyed by pattern + path)
- **Invalidation strategy:** Flush cache if files change (use file watcher or simple TTL)
- **Don't cache across users:** Keep cache per-session to avoid security issues
- **Log cache hits:** Monitor whether caching helps or hurts (might not be worth complexity)

**Detection (Warning Signs):**
- Logs show identical grep calls back-to-back
- Performance analysis shows repeated disk scans for same pattern
- Monitoring reveals high I/O utilization from grep in multi-user scenarios

**Phase to Address:** Phase 2+ (optimization) — only if perf analysis shows it matters. Defer unless needed.

---

### Pitfall 12: No Regex Syntax Validation, Bad Pattern Crashes Server or Takes Forever

**What goes wrong:**
Agent (or user) passes a malformed regex like `(unclosed paren` or catastrophic backtracking pattern like `(a+)+b`. Ripgrep either crashes with a helpful error, or hangs for 10+ seconds doing exponential search.

**Why it happens:**
- Ripgrep is passed raw user regex without validation
- Regex syntax errors are ripgrep's responsibility to catch (it usually does)
- Catastrophic backtracking patterns are hard to detect; ripgrep just hangs
- Agent might stumble into these patterns during exploration

**Consequences:**
- Minor: tool call hangs or times out
- Ripgrep error messages are usually clear (helps agent debug)
- Rare in practice (agents usually avoid pathological regexes)

**Prevention:**
- **Set ripgrep timeout:** Kill search if it takes >10 seconds: `timeout 10 rg ...`
- **Validate regex syntax (optional):** Pre-validate pattern with Python `re.compile()` for basic errors
- **Document regex rules:** Tool description includes: "Use ripgrep-compatible Rust regex syntax. Avoid complex backtracking patterns."
- **Log slow queries:** Monitor and log queries that timeout, revisit if pattern emerges
- **Test with bad patterns:** Include test case with invalid regex, verify error handling

**Detection (Warning Signs):**
- Tool calls hang indefinitely (timeout not working)
- Regex syntax errors are unclear to agent
- Catastrophic backtracking patterns make grep unusable
- No log of what patterns caused slowness

**Phase to Address:** Phase 1+ (optional enhancement) — basic timeout handling is low effort, regex validation is nice-to-have

---

### Pitfall 13: Grep Output Not Machine-Parseable, Agent Can't Extract Paths Reliably

**What goes wrong:**
Grep output is human-readable but inconsistent or unparseable. Agent can't extract file paths and line numbers using simple rules, must use fragile regex or ask human for clarification.

**Why it happens:**
- Ripgrep output formatting varies (e.g., color codes if terminal, no color if pipe)
- Tool description doesn't specify exact output format
- Agent tries regex like `grep "(.+?):(\d+):"` but fails due to special chars in paths
- Different output modes (one-line per file vs. all matches) aren't clearly labeled

**Consequences:**
- Agent struggle to parse results; loses extracted information
- Weak agents can't write regex to parse tool output
- Extra manual intervention needed to understand results

**Prevention:**
- **Specify output format in description:** Document exact format: `"format: filename:line_number:matched_content"`
- **Use consistent delimiter:** Colon-delimited format is ripgrep default; stick with it
- **No special formatting:** Disable color, other fancy output: `rg --no-color ...`
- **Include schema examples:** Tool description shows 2-3 real example outputs
- **Test parsing:** Include test that extracts paths from grep output, verifies they work with read_files

**Detection (Warning Signs):**
- Agent has trouble extracting paths from grep output
- Multiple tool calls needed to understand single grep result
- Output format changes based on context (color on terminal, plain in pipe)
- Tool description doesn't show example output

**Phase to Address:** Phase 1 (Core grep implementation) — output format matters from day one

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|----------------|-----------|
| **Phase 1: Core Grep** | Result limiting | Unbounded results → context exhaustion | Implement hard cap on matches + lines; test with pathological queries |
| **Phase 1: Core Grep** | Symlink handling | Broken symlinks → incomplete results | Validate symlinks, handle exit code 2, document symlink behavior |
| **Phase 1: Core Grep** | Binary detection | Missing ripgrep → no fallback | Detect ripgrep at startup; provide install instructions if missing |
| **Phase 1: Core Grep** | Output formatting | Missing line numbers → inefficient agent workflow | Always use `-n` flag; verify read_files can use returned paths |
| **Phase 1: Core Grep** | Context lines | No surrounding context → agent confusion | Default `-B 2 -A 2`; make configurable |
| **Phase 1: Core Grep** | File filtering | Binary files in results → noise | Respect `.gitignore`, exclude build artifacts, use file type filtering |
| **Phase 1: Core Grep** | Tool guidance | Weak agents misuse grep as file search | Embed workflow tips in tool description: "Use grep → read pattern" |
| **Phase 1: Core Grep** | Path format | Grep paths incompatible with read_files | Normalize paths; document format; test sequential tool calls |
| **Phase 1: Core Grep** | Line length | Minified code → unreadable results | Use `--max-columns`; truncate gracefully; test with `.min.js` |
| **Phase 2+: Optimization** | Caching | Repeated searches → redundant I/O | Implement LRU cache only if perf analysis justifies it |
| **Phase 1: Core Grep** | Regex validation | Bad patterns → timeouts | Add timeout handling; log slow queries; optional pre-validation |
| **Phase 1: Core Grep** | Output parsing | Machine-readable format | Specify exact output format; disable color; include examples |

---

## Summary: Build Order for Risk Mitigation

**Must address in Phase 1 (Core Grep Implementation):**
1. **Result limiting** (unbounded context explosion) — implement at day 1
2. **Symlink validation** (security + correctness) — part of security design
3. **Binary detection** (graceful degradation for missing ripgrep) — prevents full feature unavailability
4. **Output format** (line numbers, context, machine-parseability) — enables agent workflows
5. **File filtering** (build artifacts, `.gitignore`) — makes tool usable in real codebases
6. **Tool guidance** (workflow tips for weak agents) — lifts agent capability

**Should address in Phase 1 but lower priority:**
7. Context lines by default
8. Path format consistency
9. Line length limiting (minified code handling)

**Can defer to Phase 2+ or skip entirely:**
10. Result caching (only if performance analysis shows need)
11. Ripgrep binary name variations (nice-to-have; most systems use `rg`)
12. Regex validation beyond what ripgrep provides

---

## Sources

- [ripgrep integration issues with broken symlinks](https://github.com/anomalyco/opencode/issues/8307)
- [ripgrep vs Grep performance analysis](https://www.codeant.ai/blogs/ripgrep-vs-grep-performance)
- [Claude Code SDK crashes with excessive grep results](https://github.com/anthropics/claude-agent-sdk-typescript/issues/72)
- [Preventing path traversal in MCP servers](https://snyk.io/articles/preventing-path-traversal-vulnerabilities-in-mcp-server-function-handlers/)
- [MCP tool design best practices](https://developers.redhat.com/articles/2026/01/08/building-effective-ai-agents-mcp)
- [Context engineering for AI agents - token optimization](https://www.flowhunt.io/blog/context-engineering-ai-agents-token-optimization/)
- [Orchestrator context explosion from unbounded agent responses](https://github.com/evalstate/fast-agent/issues/202)
- [Structured output patterns for agents](https://platform.openai.com/docs/guides/structured-outputs)
- [Graceful degradation strategies for missing dependencies](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_mitigate_interaction_failure_graceful_degradation.html)
- [MCP security best practices with symlink path traversal](https://github.com/efforthye/fast-filesystem-mcp/issues/10)
