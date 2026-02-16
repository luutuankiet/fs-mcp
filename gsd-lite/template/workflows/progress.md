---
description: Progress check workflow - show current state and route to next action
---

# Progress Workflow

[SYSTEM: PROGRESS MODE - Situational Awareness]

## Entry Conditions

- User requests progress, status, or "where are we?"
- Session start without clear context
- Any time user wants situational awareness

## Exit Conditions

- Status report presented
- Next action suggested with clear routing
- User confirms direction

---

## Purpose

Quick situational awareness before continuing work. Show where we are, what's pending, and route to the appropriate next action.

**Philosophy:** You stay the author who can explain the "why" - this workflow surfaces that context quickly. When starting a fresh session, the agent must demonstrate understanding so you have confidence to continue pair programming.

**Why Echo Back Matters:** Fresh agents have zero prior context. By echoing back understanding at both high-level (PROJECT.md, ARCHITECTURE.md) and ground-level (WORK.md current state), the agent proves it has onboarded correctly. This avoids the "forwarder problem" where agents execute without understanding.

---

## Progress Check Process

### Step 1: Verify Structure Exists

Check if `gsd-lite/` directory exists:

```bash
test -d gsd-lite && echo "exists" || echo "missing"
```

**If missing:**

```
No GSD-Lite structure found.

To start: Create gsd-lite/ directory and initialize WORK.md

Or describe what you want to build - I'll help set it up.
```

Exit.

### Step 2: Discover Artifact State

Use grep-first to understand what exists:

```bash
ls -la gsd-lite/*.md 2>/dev/null
```

Track what exists:
- `WORK.md` - Session state and execution log
- `INBOX.md` - Loop capture
- `PROJECT.md` - Project vision (optional)
- `ARCHITECTURE.md` - Codebase structure (optional)
- `HISTORY.md` - Completed work (optional)

### Step 3: Echo Back Project Vision (High-Level Context)

**If PROJECT.md exists**, read and echo back understanding:

```bash
head -50 gsd-lite/PROJECT.md
```

Extract and present:
- **What This Is** — The project description (2-3 sentences)
- **Core Value** — The ONE thing that must work
- **Success Criteria** — High-level goals (the 5000ft view)

**Why:** PROJECT.md captures the "why" behind the project. Created during new-project workflow (see `../PROJECT.md` template and `./new-project.md` workflow). Fresh agents must demonstrate they understand project intent before diving into tasks.

**If PROJECT.md missing:** Refer to the "Missing High-Level Context" special case handling below.

### Step 4: Echo Back Architecture Overview (Technical Context)

**If ARCHITECTURE.md exists**, read and echo back understanding:

```bash
head -60 gsd-lite/ARCHITECTURE.md
```

Extract and present:
- **Project Structure** — Key directories and their purpose
- **Tech Stack** — Runtime, language, critical dependencies
- **Entry Points** — Where to start reading code

**Why:** ARCHITECTURE.md grounds the agent in the codebase reality. Understanding the technical landscape prevents misguided suggestions.

**If ARCHITECTURE.md missing:** Refer to the "Missing High-Level Context" special case handling below.

### Step 5: Read Current Understanding (Ground-Level State)

**Grep-first pattern:**

```bash
grep "^## " gsd-lite/WORK.md
```

Read the Current Understanding section (top of WORK.md to first `---`):

Extract from XML tags:
- `<current_mode>` - What workflow are we in?
- `<active_task>` - What's being worked on?
- `<parked_tasks>` - What's on hold?
- `<blockers>` - What's blocking progress?
- `<next_action>` - What's the specific next step?

**Why:** WORK.md is the ground-level truth of where we are RIGHT NOW. This complements the high-level PROJECT.md context with immediate tactical state.

### Step 6: Count Active Loops

If INBOX.md exists:

```bash
grep -c "^## LOOP-" gsd-lite/INBOX.md 2>/dev/null || echo "0"
grep "Status: Open" gsd-lite/INBOX.md 2>/dev/null | wc -l
```

### Step 7: Present Status Report

Present a comprehensive status that demonstrates understanding at both levels:

```
# Progress Check

## 🎯 Project Vision (High-Level)

**What This Is:** [2-3 sentence summary from PROJECT.md]

**Core Value:** [The ONE thing that must work]

**Success Criteria:**
- [Criterion 1 from PROJECT.md]
- [Criterion 2 from PROJECT.md]
- [Criterion 3 from PROJECT.md]

*(If PROJECT.md missing: "No PROJECT.md found - project vision not yet captured")*

## 🏗️ Architecture Overview

**Stack:** [Runtime + Language + Key dependencies summary]

**Key Entry Points:**
- [Entry point 1]
- [Entry point 2]

*(If ARCHITECTURE.md missing: "No ARCHITECTURE.md found - codebase not yet mapped")*

---

## 📍 Current State (Ground-Level)

**Mode:** [current_mode from WORK.md]

**Active Task:** [active_task or "None"]
**Parked:** [count of parked_tasks or "None"]
**Open Loops:** [count] in INBOX.md

## Blockers

[blockers content or "None - clear to proceed"]

## Next Action

[next_action from Current Understanding]

---
```

**Why this format:** The report flows from high-level (project "why") to mid-level (technical "how") to ground-level (tactical "what now"). This gives you confidence the agent has onboarded correctly before you continue pair programming.

### Step 8: Route to Next Action

Based on `current_mode` and artifact state, suggest the appropriate workflow:

| current_mode | Meaning | Suggested Action |
|--------------|---------|------------------|
| `none` or empty | No active work | "Describe what you want to build" |
| `planning` or `moodboard` | Extracting vision | "Continue vision exploration" |
| `moodboard-complete` | Ready for plan | "Ready to present plan - say 'show me the plan'" |
| `execution` | Active work | "Continue with: [next_action]" |
| `checkpoint` | Session paused | "Resume from checkpoint - [next_action]" |


**Present routing:**

```
---

## ▶ Next Up

**[Workflow]:** [Brief description]

[Specific next step from next_action]

---

**Also available:**
- "checkpoint" or "pause" — save state for later
- "write PR for [TASK]" — extract PR description
- "archive [TASK]" — move to HISTORY.md

---
```

---

## Special Cases

### No WORK.md Exists

```
No active session found.

**What I Know:**
- PROJECT.md: [Found/Missing - summary if found]
- ARCHITECTURE.md: [Found/Missing - summary if found]

**Options:**
1. Tell me what you want to build → I'll help set up PROJECT.md (see new-project workflow)
2. "map the codebase" → I'll document existing code in ARCHITECTURE.md (see map-codebase workflow)
3. Start fresh → Describe your first task

What would you like to do?
```

### Missing High-Level Context

If PROJECT.md or ARCHITECTURE.md is missing, note it clearly:

```
⚠️ Context Gaps Detected:

- [ ] PROJECT.md missing — I don't yet understand the project's "why"
- [ ] ARCHITECTURE.md missing — I don't yet know the codebase structure

Would you like to:
1. Describe your project → I'll create PROJECT.md
2. "map the codebase" → I'll create ARCHITECTURE.md
3. Continue anyway → I'll work with what's available
```

This transparency builds trust — you know exactly what the agent does and doesn't understand.

### WORK.md Has Example Content Only

If Current Understanding contains "EXAMPLE" entries:

```
WORK.md exists but contains only template examples.

Ready to start real work. What would you like to build or accomplish?
```

### Multiple Blockers

If blockers section has content:

```
⚠️ Blockers need attention before continuing:

[List blockers]

Would you like to:
1. Resolve blockers now
2. Park blocked work and start something else
3. Continue anyway (if blockers are soft)
```

**Why "ONBOARDED":** The sticky note now confirms the agent has loaded both high-level context (project vision) and ground-level state (current tasks). This gives you confidence the agent is ready for pair programming.

---

## Anti-Patterns

- **Reading entire WORK.md** — Use grep-first, read only Current Understanding
- **Suggesting actions without context** — Always read current_mode first
- **Ignoring blockers** — Surface blockers prominently before suggesting next action
- **Complex routing** — Keep it simple: one clear next action
- **Over-reporting** — Status should be glanceable, not a wall of text
- **Skipping the echo-back** — Fresh sessions MUST demonstrate understanding before diving in
- **Silent onboarding** — Don't read PROJECT.md/ARCHITECTURE.md silently; echo back what you learned
- **Assuming context** — Fresh agents have zero prior context; prove you understand by stating it

---

*Progress Workflow - Part of GSD-Lite Protocol v2.0*