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

**Milestone Status:** Phase 2 In Progress

**Active Phase:** Phase 2: Agent Workflow Optimization

**Progress:**
- Phase 2, Plan 1 of 1 executed and verified.
- Agent workflow guidance implemented in tool descriptions and project documentation.
- Next step: Plan Phase 3 execution.

**Progress Bar:**
```
[█████████████████████████...........] 66% (Phase 2 complete → Phase 3 planning)
```

---

## Key Artifacts

**ROADMAP.md**
- 3 phases derived from requirements
- Phase 1: Ripgrep Integration & Core Grep Tool (13 requirements) - **Complete**
- Phase 2: Agent Workflow Optimization (3 requirements) - **Complete**
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
6. **Explicit Agent Guidance:** Explicitly guide agents via tool descriptions rather than relying on emergent behavior.

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
| Weak agent behavior | HIGH | Explicit guidance removes ambiguity for weaker models |

### Known Blockers

None currently. Phase 3 can begin.

---

## Session Continuity

**Last Activity:** 2026-01-26 - Phase 2, Plan 1 execution complete

**What's Next:**
1. Plan Phase 3: `/gsd-plan-phase 3`
2. Execute Phase 3: `/gsd-execute-phase 3`

---

**Last Updated:** 2026-01-26 (after 02-01 plan execution)
