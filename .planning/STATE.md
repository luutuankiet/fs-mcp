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

**Milestone Status:** All phases complete
**Active Phase:** None
**Progress:**
- Phase 5 Plan 1 complete (enhance read_files for section-aware reading)
- Phase 5 Plan 2 complete (enhance grep_content with section end hints)

**Progress Bar:**
```
[████████████████████████████████████████████████████████████] 100% (Phase 5 complete)
```
[████████████████████████████████████████████████████████████] 100% (Phase 5 complete)
```

---

## Key Artifacts

**ROADMAP.md**
- 5 phases derived from requirements
- Phase 1: Ripgrep Integration & Core Grep Tool (13 requirements) - **Complete**
- Phase 2: Agent Workflow Optimization (3 requirements) - **Complete**
- Phase 3: Production Polish & Cleanup (1 requirement) - **Complete**
- Phase 4: Add jq and yq for querying large json and yaml files - **Complete**
- Phase 4.1: Enhance jq and yq to handle complex multiline queries request - **Complete**
- Phase 5: enhance Section-Aware Reading - **Complete**
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
12. **Temp file approach for complex CLI inputs:** Use tempfile.NamedTemporaryFile for query expressions to avoid shell escaping issues. Write content, close, execute subprocess with -f/--from-file flag, cleanup in finally block.
13. **Use default section patterns for `grep_content` hinting:** Provide immediate utility without agent configuration.
14. **Make `grep_content` hint generation skippable:** Allow agents to pass `[]` to disable the feature.
15. **Suppress hint generation errors:** Prevent the enhancement from ever breaking core `grep_content` functionality.
16. **Use `itertools.islice` for efficient file slicing:** Ensures memory-safe reading of file sections.
17. **Return structured errors for invalid `read_files` parameters:** Helps agents self-correct on invalid input combinations.
18. **Read to EOF if `read_to_next_pattern` is not found:** Provides predictable behavior for agents when a pattern is missing.

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

- Phase 5 added: enhance Section-Aware Reading
- Phase 4 added: Add jq and yq for querying large json and yaml files
- Phase 4.1 inserted after Phase 4: Enhance jq and yq to handle complex multiline queries request (URGENT)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 001 | Fix propose_and_review tool blocking issue - investigate if synchronous execution causes client blocking when user reviews too long | 2026-01-28 | a9517fb | [001-fix-propose-and-review-tool-blocking-iss](./quick/001-fix-propose-and-review-tool-blocking-iss/) |
| 002 | Fix multi-patch mode (edits parameter) bugs in propose_and_review - make new_string optional and normalize EditPair models | 2026-01-29 | fe2c383 | [002-fix-the-bug-reported-at-bug-report-md](./quick/002-fix-the-bug-reported-at-bug-report-md/) |
| 003 | Fix pytest failures from validation order and schema description issues - add async decorators, handle nested anyOf, update length threshold | 2026-01-29 | bf58c1f | [003-fix-the-bug-outlined-at-2-bug-report-md-](./quick/003-fix-the-bug-outlined-at-2-bug-report-md-/) |

---

## Session Continuity

**Last Activity:** 2026-01-29 - Quick task 003 execution complete

**What's Next:**
Quick task 003 complete - fixed 11 failing pytest tests (async decorators, schema descriptions, length thresholds)

---

**Last Updated:** 2026-01-29 (after quick-003 execution)
