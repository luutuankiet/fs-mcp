# PROJECT STATE: fs-mcp Ripgrep Integration

**Project:** fs-mcp remote agent access
**Milestone:** v1 (Ripgrep Integration)
**Started:** 2026-01-26

---

## Project Reference

**Core Value Proposition:**
One-command remote agent access. `uvx fs-mcp` on any server → agents can read, write, and explore the codebase immediately. No SSH tunnels, no environment setup.

**Current Focus:**
Add ripgrep-based content search to complete the grep → read pattern for efficient remote codebase exploration.

**Why Now:**
Agents exploring unfamiliar codebases burn context tokens. The grep → read workflow is 80% more token-efficient than full file reads, but requires a grep tool that doesn't exist yet.

**Success Metric:**
Complete grep tool implementation with bounded output, agent workflow guidance, and production-ready polish.

---

## Current Position

**Milestone Status:** Phase 1 Complete

**Active Phase:** Phase 1: Ripgrep Integration & Core Grep Tool

**Progress:**
- Phase 1 executed and verified
- Core `grep_content` tool and dependency checks are implemented.
- Next step: Plan Phase 2 execution

**Progress Bar:**
```
[█████████████...........................] 33% (Phase 1 complete → Phase 2 planning)
```

---

## Key Artifacts

**ROADMAP.md**
- 3 phases derived from requirements
- Phase 1: Ripgrep Integration & Core Grep Tool (13 requirements)
- Phase 2: Agent Workflow Optimization (3 requirements)
- Phase 3: Production Polish & Cleanup (1 requirement)
- 100% requirement coverage

**REQUIREMENTS.md**
- 17 v1 requirements across 4 categories
- All mapped to phases 1-3
- 5 v2 requirements deferred

---

## Accumulated Context

### Decisions Made

1. **3-Phase Structure:** Research suggested 3-phase approach; aligns with quick depth setting. Phases cluster naturally around: core functionality, agent optimization, production readiness.

2. **Ripgrep via subprocess:** Use ripgrep CLI binary (not Python library) for zero external Python dependencies and mature feature set.

3. **Bounded Output from Day One:** Hard cap at 100 matches; layer three defenses (ripgrep flags + Python processing + output formatting).

4. **Platform-Specific Install Guidance:** Detect ripgrep at startup; provide platform-specific commands (brew for macOS, apt for Ubuntu, etc.).

5. **Graceful Degradation:** Server continues running if ripgrep missing; grep tool disabled with helpful warning message.

### Implementation Notes

- **Path Validation:** Reuse existing `validate_path()` from server.py (proven secure)
- **Subprocess Pattern:** Match existing VS Code diff tool pattern (no shell=True, argument list only)
- **Output Format:** Text-based (not JSON exposed), standardized for agent parsing
- **Error Handling:** Three layers: FileNotFoundError → install help; TimeoutExpired → pattern refinement suggestion; CalledProcessError → ripgrep error returned
- **Timeout:** 10 seconds prevents runaway searches
- **Context Lines:** Default 2 before/after (configurable)

### Research Confidence

| Area | Confidence | Note |
|------|-----------|------|
| Subprocess pattern | HIGH | Proven in existing fs-mcp code |
| Ripgrep JSON output | HIGH | Official ripgrep documentation |
| Security patterns | HIGH | Existing validate_path() gate proven |
| CLI flags (--json, -n, -B/-A) | HIGH | Ripgrep stable across versions 14.0+ |
| Agent-friendly design | HIGH | Aligns with ripgrep's machine-readable output goals |
| Weak agent behavior | MEDIUM | Should validate with real GPT-3.5 testing in Phase 2 |

### Known Blockers

None currently. Phase 1 can begin immediately.

### Deferred to v2

- GREP-11: File type filtering (`-t py`, `-t js`)
- GREP-12: Fixed-string mode (literal matches)
- GREP-13: Multiline pattern matching
- GREP-14: Match density summary
- OPT-01: Result caching

---

## Performance Metrics

### Target State (End of v1)

| Metric | Target | Note |
|--------|--------|------|
| Grep search latency | <500ms | Most searches complete in <200ms |
| Max result size | <50KB | Hard cap 100 matches ensures this |
| Context window efficiency | 80% improvement | Grep → read uses far fewer tokens than full reads |
| Server startup time | <100ms added | Ripgrep availability check is lightweight |

### Current State

Metrics not yet measured (Phase 1 will establish baseline).

---

## Session Continuity

**Last Activity:** 2026-01-26 - Phase 1 execution complete

**What's Next:**
1. Plan Phase 2: `/gsd-plan-phase 2`
2. Execute Phase 2: `/gsd-execute-phase 2`

**Available Commands:**
- Review files: `cat .planning/ROADMAP.md`, `cat .planning/STATE.md`, `cat .planning/REQUIREMENTS.md`
- Proceed: `/gsd:plan-phase 1` (after approval)
- Revise: Provide feedback if roadmap needs adjustment

---

**Last Updated:** 2026-01-26 (roadmap creation)
**Status:** Roadmap complete, awaiting user approval
