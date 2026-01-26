# Research Synthesis: Ripgrep-Based Grep Tool for fs-mcp

**Project:** fs-mcp grep tool for AI agent content search
**Researched:** 2026-01-26
**Confidence Level:** HIGH

---

## Executive Summary

The fs-mcp grep tool should be a **lightweight subprocess wrapper around ripgrep CLI**, using `rg --json` output format for machine-readable results. This approach provides zero external Python dependencies, perfect agent-friendly structured output, and leverages ripgrep's mature ecosystem.

The tool must be **aggressively bounded** (max 100 matches, line number limiting) and **security-hardened** (path validation, symlink handling) from day one. The existing fs-mcp architecture provides perfect integration points—reusing the `validate_path()` security gate and subprocess patterns already established for the VS Code diff tool.

**Key Risk:** Unbounded results causing context exhaustion. This must be architected in, not bolted on. **Key Opportunity:** The grep → read pattern enables 80% token savings vs. full file reads, making agents dramatically more efficient.

---

## Recommended Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| **Core Search Engine** | ripgrep CLI binary | 14.1+ | Fast (SIMD), parallel, respects .gitignore, mature, ubiquitous on dev machines |
| **Python Integration** | subprocess module | 3.10+ (existing) | Zero external dependencies, stable, sufficient for CLI invocation |
| **Output Format** | `rg --json` (JSON lines) | Built-in | Structured, type-safe for agents, no regex parsing needed |
| **Error Handling** | subprocess + shutil | Python stdlib | TimeoutExpired, CalledProcessError, binary detection via shutil.which() |
| **Dependency Strategy** | Optional system dependency | Latest available | Fail gracefully with helpful install message if missing |

**Not Recommended:**
- `ripgrepy` library (adds 5-10ms overhead, external dependency)
- `ripgrep-python` native bindings (10-50x faster but adds Rust build complexity, not needed for agent workloads)
- Python regex (100x slower than ripgrep, not acceptable)

---

## MVP Features (Table Stakes)

**Must Include in Phase 1:**

1. **Regex Pattern Matching** — Core functionality via ripgrep's Rust engine
2. **Line Numbers** — Essential for agent → read_files workflow (`-n` flag)
3. **File Paths** — Relative paths (normalized) for navigation
4. **Context Lines** — Default 2-3 lines before/after match (`-B 2 -A 2`)
5. **Recursion** — Search entire directory trees by default
6. **Bounded Output** — Hard cap at 100 matches max (non-negotiable for context safety)
7. **Respecting .gitignore** — Ripgrep default behavior, skip build artifacts
8. **Error Messages** — Detect missing ripgrep, provide platform-specific install help
9. **Line Length Limiting** — Use `--max-columns 500` to prevent minified code bloat
10. **Tool Guidance** — Docstring emphasizes "grep → read pattern" workflow

**Should Include (minimal overhead):**
- Case-insensitive search (`-i` flag)
- File type filtering (`-t` flag)
- Fixed-string search (`-F` flag)
- Plaintext output (ripgrep default format)

**Defer to Phase 2+:**
- Match density reporting
- Automatic context tuning
- Multiline pattern support
- Search result caching
- JSON output variant
- Compression support

---

## Architecture Approach

### Integration Pattern

The grep tool fits seamlessly into existing fs-mcp architecture with **zero architectural changes**:

```
Agent → MCP Tool (@mcp.tool() decorator)
    ↓
grep_content(path, pattern, ...)
    ↓
validate_path(path) — reuse existing security gate
    ↓
_build_ripgrep_args() — construct safe subprocess command
    ↓
subprocess.run(args, cwd=validated_root, timeout=10)
    ↓
_format_grep_results() — standardize output (text format, agent-friendly)
    ↓
Agent receives bounded results with line numbers + context
```

### Security by Reuse

- **Path Validation:** Reuse existing `validate_path()` from server.py (lines 72-124)
- **Subprocess Safety:** Match existing pattern used for VS Code diff tool (no `shell=True`, argument list only)
- **Symlink Handling:** Disable symlink following by default (`--no-follow` implicit), validate targets after resolution

### Component Boundaries

**Tool Layer Structure:**
- **Discovery Tools group:** `search_files()` (glob-based) + `grep_content()` (content-based)
- **Input:** Individual parameters (simple for weak agents), not Pydantic model
- **Output:** Standardized text format: `File: path\n  line_number: matched_text\n` with context lines indented
- **Bounded output:** Three-layer defense (ripgrep flags + Python post-processing + output format)

---

## Top Pitfalls to Avoid

### Critical (Phase 1 - Must Address)

**1. Unbounded Results Exhausting Context** (Pitfall #1)
- **Risk:** 10K+ matches from single search crash agent context
- **Prevention:** Implement hard cap: `--max-count=100` in ripgrep, post-process to enforce limit
- **Detection:** Monitor for result sets >50K characters or >100 matches

**2. Missing Ripgrep Binary, No Graceful Fallback** (Pitfall #3)
- **Risk:** Tool silently fails with "command not found" on systems without ripgrep
- **Prevention:** Detect ripgrep at server startup (call `rg --version`); return helpful error with platform-specific install commands
- **Install message:** Include `brew install ripgrep` (macOS), `apt install ripgrep` (Ubuntu), `dnf install ripgrep` (Fedora), `choco install ripgrep` (Windows)

**3. Missing Line Numbers in Output** (Pitfall #6)
- **Risk:** Agent can't pinpoint match location in source; breaks grep → read workflow
- **Prevention:** Always use `rg -n` flag; format output as `filename:line_number:content`

**4. Broken Symlinks Causing Silent Data Loss** (Pitfall #2)
- **Risk:** Search results incomplete due to inaccessible symlinks
- **Prevention:** Disable symlink following by default; validate symlink targets post-resolution; handle ripgrep exit code 2 (partial error) as warning

**5. Minified Code Causing Context Bloat** (Pitfall #4)
- **Risk:** Single match on 50KB minified line exhausts context
- **Prevention:** Use `--max-columns 500` to truncate long lines; indicate truncation in output

**6. Weak Agents Misusing Grep as File Search** (Pitfall #5)
- **Risk:** Agent uses grep for filename discovery instead of content search, wasting tokens
- **Prevention:** Embed workflow guidance in docstring: "Use grep → read pattern. For file discovery by name, use search_files() instead."

### Moderate (Phase 1 - Should Address)

**7. No Context Lines** — Default `-B 2 -A 2`; make configurable
**8. No File Type Filtering** — Respect .gitignore by default; exclude build artifacts
**9. Path Format Mismatch** — Normalize to relative paths; test grep → read_files chaining

### Minor (Phase 1 or defer)

**10. Ripgrep Binary Name Confusion** — Check for both `rg` and `ripgrep` in PATH
**11. Result Caching** — Skip unless perf testing justifies (likely not needed for MVP)
**12. Regex Validation** — Set timeout to 10s; let ripgrep handle syntax errors

---

## Build Order Recommendation

### Phase 1: Core Grep Implementation (Week 1)

**Goal:** Functional grep tool with security, error handling, bounded output

**Tasks (in order):**
1. Detect ripgrep availability at server startup; disable tool gracefully if missing
2. Implement `grep_content()` function replacing `grounding_search()` stub
3. Add helper functions:
   - `_build_ripgrep_args()` — construct safe ripgrep command
   - `_execute_ripgrep_safe()` — subprocess execution with timeout (10s), error handling
   - `_format_grep_results()` — standardize output format with bounded lines
4. Implement bounded output (hard max 100 matches, truncation messaging)
5. Add line number limiting (`--max-columns 500`)
6. Add comprehensive error messages (ripgrep missing, timeout, invalid pattern)
7. Write security tests (path validation, symlink handling, injection prevention)
8. Write integration tests (grep → read_files workflow)

**Deliverable:** grep_content() that safely searches with bounded output, line numbers, context, and helpful errors

### Phase 2: Workflow Optimization (Week 2)

**Goal:** Improve agent efficiency and usability

**Tasks:**
1. Add optional parameters: case_insensitive, file_pattern (glob), context customization
2. Update tool descriptions in read_files and grep_content with workflow guidance
3. Add test with weak agents (Claude 3.5 Sonnet, GPT-3.5) to verify they use grep → read pattern
4. Consider: match density reporting (found X matches in Y files)

**Deliverable:** Agents naturally discover and use the efficient grep → read pattern

### Phase 3: Polish & Observability (Week 3)

**Goal:** Production-ready tool with metrics and documentation

**Tasks:**
1. Remove grounding_search() placeholder
2. Update README with ripgrep as optional dependency
3. Add logging: pattern searched, result count, timeout events
4. Performance benchmarking on realistic codebases
5. Documentation: examples of correct grep usage, why grep is better than full reads

**Deliverable:** Production-ready grep tool with full documentation and observability

---

## Research Flags & Confidence

### High Confidence Areas

| Area | Confidence | Basis |
|------|-----------|-------|
| **Subprocess pattern** | HIGH | Official Python docs + industry standard; used in fs-mcp for VS Code |
| **Ripgrep JSON output** | HIGH | Verified in ripgrep docs + GitHub issues + GUIDE.md |
| **Security patterns** | HIGH | Existing fs-mcp validate_path() gate proven; reusable |
| **CLI flags (--json, -n, -B/-A)** | HIGH | Ripgrep official documentation + extensive community usage |
| **Error handling** | HIGH | Python subprocess module well-documented |
| **Agent-friendly design** | HIGH | Aligns with ripgrep's design purpose (machine-readable output) |

### Medium Confidence Areas

| Area | Confidence | Basis |
|------|-----------|-------|
| **Performance claims (10-50x)** | MEDIUM | Library benchmarks credible but not independently verified for agent workloads |
| **Weak agent behavior** | MEDIUM | Based on agent SDK research + theory; should validate with real GPT-3.5 testing |
| **Token efficiency (80% savings)** | MEDIUM | Projected from grep vs. read patterns; should benchmark with real agents |

### Gaps to Address During Planning

1. **Weak agent testing** — Run Phase 1 implementation with GPT-3.5, Gemini Flash to verify they discover grep → read pattern (don't assume)
2. **Ripgrep version compatibility** — Verify --json output format stable across 14.0+ versions (likely yes, but check)
3. **Performance on monorepos** — Benchmark on fbsource-scale codebases (>1M files) to validate timeout strategy
4. **Symlink edge cases** — Test with circular symlinks, permission-denied symlinks, symlinks outside allowed dirs

---

## Key Findings Summary

### From STACK.md
- **Recommended approach:** subprocess-based ripgrep with `--json` output
- **Best practice:** Pattern 1 (sync search with timeout) for agent workloads
- **Error handling:** FileNotFoundError → install ripgrep; TimeoutExpired → suggest pattern refinement; CalledProcessError → ripgrep error returned
- **JSON parsing:** Per-line `json.loads()` sufficient for agent context sizes

### From FEATURES.md
- **Table stakes:** Line numbers, context lines, bounded output, error messages
- **Differentiators:** Automatic context tuning, match density reporting (defer to v2)
- **Anti-features:** Semantic search (out of scope), AST-aware search (defer), relevance ranking (unnecessary)
- **MVP sweet spot:** Basic ripgrep wrapper with careful output formatting and agent guidance

### From ARCHITECTURE.md
- **Integration:** Zero architectural changes; reuses validate_path() + subprocess patterns
- **Tool placement:** Discovery Tools group alongside search_files()
- **Output format:** Text-based (not JSON exposed), standardized for agent parsing
- **Build order:** Can be implemented independently; no dependencies on other features

### From PITFALLS.md
- **Top 6 critical pitfalls:** All Phase 1 concerns (unbounded output, symlinks, missing binary, line numbers, context, file filtering)
- **Architecture implication:** These aren't edge cases; they're fundamental requirements
- **Prevention strategy:** Layer three defenses (ripgrep flags + Python processing + output formatting)

---

## Roadmap Implications

### Why Grep First?

1. **Independent feature** — No dependencies on other fs-mcp tools; can be implemented in parallel
2. **High agent value** — Enables grep → read workflow that's 80% more token-efficient
3. **Integrates cleanly** — Reuses existing security + subprocess patterns; fits into existing architecture
4. **Risk is manageable** — Pitfalls are well-understood and addressable in Phase 1

### Phase Structure Recommendation

```
Phase 1 (Week 1): Core Grep Implementation
├─ Ripgrep detection + error handling
├─ grep_content() function with bounded output
├─ Security testing (path validation, injection prevention)
└─ Deliverable: Functional, safe, bounded grep tool

Phase 2 (Week 2): Workflow Optimization
├─ Optional parameters (case sensitivity, file filtering)
├─ Agent guidance in tool descriptions
├─ Weak agent testing (GPT-3.5 validation)
└─ Deliverable: Agents naturally use efficient patterns

Phase 3 (Week 3): Production Polish
├─ Documentation + examples
├─ Performance benchmarking
├─ Observability (logging + metrics)
└─ Deliverable: Production-ready grep tool
```

### What NOT to Build

- Semantic search (requires external dependencies, violates zero-setup)
- AST-aware search (language-specific complexity, ripgrep covers 90% of use cases)
- Result caching (defer until performance analysis justifies complexity)
- JSON output as primary format (text is simpler for agents to parse)

---

## Implementation Checklist for Planning

- [ ] Verify ripgrep version compatibility for --json flag (14.0+)
- [ ] Confirm validate_path() can be reused without modification
- [ ] Test subprocess timeout behavior on large codebases (>1M files)
- [ ] Define exact output format (specify colon delimiters, indentation, truncation messages)
- [ ] Plan weak agent testing (identify GPT-3.5 test patterns)
- [ ] Identify which ripgrep flags are stable across versions
- [ ] Define "bounded output" precisely (100 matches? 500 lines total?)
- [ ] Plan symlink edge case tests (broken, circular, out-of-bounds)
- [ ] Identify platform-specific ripgrep paths for detection logic

---

## Sources Integrated

**STACK.md:** Ripgrep CLI documentation, Python subprocess module, ripgrepy/ripgrep-python libraries, JSON output schema (Issue #930)

**FEATURES.md:** Anthropic context engineering guidance, Claude Code grep reference, ripgrep user guide, MCP tool design best practices

**ARCHITECTURE.md:** Existing fs-mcp server.py patterns, MCP protocol conventions, subprocess safety patterns, tool integration design

**PITFALLS.md:** Real-world MCP failure case studies, symlink security issues, context window exhaustion incidents, weak agent behavior patterns

---

**Research Complete:** Ready for requirements definition. All four domains synthesized. Architecture and risk profiles clear. Roadmap implications documented. Implementation can proceed with confidence.
