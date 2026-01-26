# Requirements: fs-mcp Ripgrep Integration

**Defined:** 2026-01-26
**Core Value:** One-command remote agent access — `uvx fs-mcp` on any server, agents can read, write, and explore immediately.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Startup & Dependencies

- [ ] **INIT-01**: Server checks for ripgrep (`rg`) availability at startup before accepting connections
- [ ] **INIT-02**: Server displays platform-specific install command if ripgrep is missing (macOS: `brew install ripgrep`, Linux: `apt install ripgrep`, Windows: `choco install ripgrep`)
- [ ] **INIT-03**: Server logs clear warning but continues running without grep tool if ripgrep unavailable

### Grep Tool (Core)

- [ ] **GREP-01**: Agent can search file contents using regex patterns via ripgrep
- [ ] **GREP-02**: Search results include file paths relative to allowed directory
- [ ] **GREP-03**: Search results include line numbers for each match
- [ ] **GREP-04**: Search results include configurable context lines before/after match (default: 2)
- [ ] **GREP-05**: Search results are bounded to max 100 matches to prevent context overflow
- [ ] **GREP-06**: Search respects `.gitignore` and excludes common build artifacts (`node_modules`, `.venv`, `__pycache__`)
- [ ] **GREP-07**: Agent can perform case-insensitive search via optional parameter

### Grep Tool (Error Handling)

- [ ] **GREP-08**: Tool returns helpful error message if ripgrep not found (with install instructions)
- [ ] **GREP-09**: Tool handles ripgrep exit code 1 (no matches) gracefully — returns "No matches found" not error
- [ ] **GREP-10**: Tool times out after 10 seconds to prevent runaway searches

### Tool Guidance

- [ ] **GUID-01**: Grep tool description explicitly recommends "grep → read" workflow pattern
- [ ] **GUID-02**: read_files tool description references grep as discovery step for large codebases
- [ ] **GUID-03**: search_files (glob) tool description clarifies it's for file names, grep is for file contents

### Cleanup

- [ ] **CLEN-01**: Remove `grounding_search` placeholder tool

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Grep Enhancements

- **GREP-11**: Agent can filter search by file type (`-t py`, `-t js`)
- **GREP-12**: Agent can use fixed-string mode for literal matches (non-regex)
- **GREP-13**: Agent can use multiline pattern matching
- **GREP-14**: Tool returns match density summary ("Found X matches in Y files")

### Optimization

- **OPT-01**: Cache recent grep results to avoid redundant searches

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Semantic/embedding search | Violates zero-setup — requires pre-indexing |
| AST-aware code search | Complexity without MVP justification; ripgrep regex covers 90% of use cases |
| Result ranking/relevance | Adds complexity; agents can refine patterns themselves |
| Custom ripgrep config files | Breaks predictability; all options via explicit tool parameters |
| JSON output mode | Plaintext with line numbers is sufficient and token-efficient |
| Search result persistence (DB) | Violates stateless HTTP principle |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INIT-01 | — | Pending |
| INIT-02 | — | Pending |
| INIT-03 | — | Pending |
| GREP-01 | — | Pending |
| GREP-02 | — | Pending |
| GREP-03 | — | Pending |
| GREP-04 | — | Pending |
| GREP-05 | — | Pending |
| GREP-06 | — | Pending |
| GREP-07 | — | Pending |
| GREP-08 | — | Pending |
| GREP-09 | — | Pending |
| GREP-10 | — | Pending |
| GUID-01 | — | Pending |
| GUID-02 | — | Pending |
| GUID-03 | — | Pending |
| CLEN-01 | — | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 0
- Unmapped: 17 ⚠️ (awaiting roadmap)

---
*Requirements defined: 2026-01-26*
*Last updated: 2026-01-26 after initial definition*
