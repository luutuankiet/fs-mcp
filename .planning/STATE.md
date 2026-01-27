# PROJECT STATE: fs-mcp Ripgrep Integration

**Project:** fs-mcp remote agent access
**Milestone:** v1 (Ripgrep Integration)
**Started:** 2026-01-26

---

## Project Reference

**Core Value Proposition:**
One-command remote agent access. `uvx fs-mcp` on any server → agents can read, write, and explore the codebase immediately. No SSH tunnels, no environment setup.

**Current Focus:**
Project goals for this milestone are complete.

**Why Now:**
Agents exploring large structured files that would overflow agent context windows. The grep → query pattern is more token-efficient.

**Success Metric:**
Complete query tool implementation with bounded output, agent workflow guidance, and production-ready polish.

---

## Current Position

**Milestone Status:** Phase 4 complete

**Active Phase:** Phase 4: Add jq and yq for querying large json and yaml files

**Progress:**
- Phase 4, plan 2 complete.
- This milestone is complete.

**Progress Bar:**
```
[██████████] 100% (6/6 plans complete)
```

---

## Key Artifacts

**ROADMAP.md**
- 4 phases derived from requirements
- Phase 1: Ripgrep Integration & Core Grep Tool (13 requirements) - **Complete**
- Phase 2: Agent Workflow Optimization (3 requirements) - **Complete**
- Phase 3: Production Polish & Cleanup (1 requirement) - **Complete**
- Phase 4: Add jq and yq for querying large json and yaml files - **Complete**
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
7. **Agent Simulation:** Simulated planner and checker agents during orchestration tasks where an executor agent cannot spawn other agents.
8. **Follow ripgrep pattern for jq/yq:** To maintain consistency for checking external CLI dependencies.
9. **Use a virtual environment for dependencies:** To resolve dependency conflicts and isolate the project environment.
10. **Follow ripgrep pattern for subprocess execution:** For consistency in error handling and result limiting.
11. **Make large file check in `read_files` opt-out:** To prevent accidental context overflows by agents.

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

None currently.

### Roadmap Evolution

- Phase 4 added: Add jq and yq for querying large json and yaml files

---

## Session Continuity

**Last Activity:** 2026-01-27 - Phase 4, Plan 2 execution complete

**What's Next:**
This milestone is complete.

---

**Last Updated:** 2026-01-27 (after 04-02 plan execution)
