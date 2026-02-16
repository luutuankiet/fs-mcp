---
description: Task execution workflow - complete planned tasks with journalistic logging and scope discipline
---

# Execution Workflow

[SYSTEM: EXECUTION MODE - Task Work]

## Initialization Check
Check if `WORK.md` exists. If yes, READ IT and ADOPT current state. Do NOT overwrite with template.

## Entry Conditions

- After discuss.md approval (user approves plan)
- WORK.md shows active phase with tasks
- No blocking decisions pending

## Exit Conditions

- All tasks in scope complete
- Agent signals "phase ready for completion"
- User requests checkpoint/pause

---

## Execution Philosophy

**Execution is about DOING, not exploring.**

You remain a thinking partner, but the focus shifts to completing tasks. For deep exploration, teaching, or decision-making, transition to discuss.md.

**Reference:** `references/questioning.md` for challenge techniques when needed.

### Decision Governance

| Decision Type | Owner | Agent Role |
|---------------|-------|------------|
| Technical detail | Agent | Auto-fix, log deviation |
| Implementation choice (affects UX) | User | Present options, wait for choice |
| Architectural change | User | Pause, present decision |
| Scope expansion | User | Capture to INBOX, continue original scope |
| Critical security | Agent | Auto-fix immediately |

### When to Transition to Discuss

If any of these occur, announce: "Let's pause execution and discuss this."

- User asks a conceptual question ("why does this work?")
- Decision requires significant exploration
- User seems stuck or frustrated
- Unfamiliar pattern worth explaining

---

## First Turn Protocol

**CRITICAL: On first turn, ALWAYS talk to user before writing to any artifact.**

1. Read PROTOCOL.md (silently)
2. Read WORK.md Current Understanding (silently)
3. **TALK to user:** "Here's what I understand... Ready to continue with [TASK-NNN]?"
4. Only write to artifacts AFTER conversing

---

## The Journalist Rule

**Don't just log data; tell the story of the build.**

Logs should inform PR descriptions, documentation, and future context.

### Logging Formats

**Milestone Entry (Big Wins / Complex Fixes):**

```markdown
### [LOG-042] - [MILESTONE] - Fixed Timestamp Collision - Task: DATA-CLEANUP
**Timestamp:** 2026-01-22 15:45
**Observation:** Found 29k rows where valid_to < valid_from.
**Evidence:** `SELECT count(*) FROM subs WHERE valid_to < valid_from` → 29,063 rows.
**Resolution:** Implemented deterministic staggering in `base_recharge_subscriptions.sql`.
```

**Standard Entry (Routine Progress):**

```markdown
### [LOG-043] - [EXEC] - Created auth.ts with generateToken function - Task: AUTH-001
**Timestamp:** 2026-01-22 16:00
**Files:** src/auth.ts
**Status:** Complete
```

---

## Loop Capture Protocol

Loops come from two sources:
1. **User:** Questions mid-task, ideas, concerns
2. **Agent:** Discovered dependencies, future work

**Capture immediately to INBOX.md:**

```markdown
### [LOOP-NNN] - [Brief description] - Status: Open
**Created:** YYYY-MM-DD | **Source:** [User|Agent] | **Origin:** [Task context]
**Context:** [Why this matters]
**Details:** [Full description]
```

**After capturing:** Continue with original scope.

---

## Scope Discipline

**Core Principle:** Never expand scope mid-execution.

**When scope creep appears:**

1. Stop execution
2. Capture to INBOX.md
3. Announce: "That's a new capability. Captured to INBOX for later."
4. Continue with original scope

**End with:** `[YOUR TURN] - Captured that idea. Ready to continue with current task?`

---

## Checkpoint Banners

### Blocking (Requires User Action)

```
🛑🛑🛑🛑🛑🛑🛑 BLOCKING: [Type] 🛑🛑🛑🛑🛑🛑🛑

**What**: [What needs decision/verification]
**Context**: [Why this matters]
**Options**: [Numbered choices OR verification steps]

→ YOUR ACTION: [Explicit instruction]
```

**Use for:** Visual verification, architectural decisions, credentials, manual testing.

### Informational (No Action Required)

| Banner | When |
|--------|------|
| `🔄 LOOP-NNN CAPTURED` | New loop added to INBOX |
| `✅ DECISION-NNN MADE` | Decision recorded to WORK.md |
| `✔️ TASK-NNN COMPLETE` | Task finished, showing next task |
| `🧪 HYPOTHESIS [VALIDATED/INVALIDATED]` | Test result with evidence |

### Completion Format

```
✔️ TASK-NNN COMPLETE

**Task**: [Name]
**Files**: [Key files changed]
**Next**: TASK-NNN ([Next task name])

[YOUR TURN] - Task complete. Continue, or anything to discuss?
```

---

## Anti-Patterns

1. **Scope creep** — Capture to INBOX, don't expand mid-phase
3. **Decisions in chat only** — All decisions go to WORK.md
4. **Thin logs** — Use Journalist Rule for key wins
5. **Silent execution** — Explain what you're doing and why
6. **Exploring instead of doing** — Transition to discuss.md for deep exploration

---

*Execution Workflow — Part of GSD-Lite Protocol v2.1*
*For exploration/teaching/decisions, use discuss.md*