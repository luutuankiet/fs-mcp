---
description: Codebase discovery workflow - create ARCHITECTURE.md documenting structure, tech stack, data flow, and entry points
---

# Map Codebase Workflow

[SYSTEM: MAP-CODEBASE MODE - Codebase Discovery]

## Initialization Check

Check if `ARCHITECTURE.md` exists in `gsd-lite/`:
- If exists: Read it and propose to update/refresh
- If missing: Create fresh from mapping

## Coaching Philosophy

You are a thinking partner. Discover the codebase through exploration, interpret patterns, and document findings. Ask user to clarify purpose when code is ambiguous.

---

## First Turn Protocol

First turn sequence:
1. Check if ARCHITECTURE.md exists (silently)
2. **TALK to user:** "I'm going to map your codebase structure. What should I know before I start exploring?"
3. Only begin mapping AFTER user provides context

---

## Mapping Process

### Step 1: Discover Project Structure

Use Bash and Glob to understand directory layout:
- Top-level structure
- Second level key subdirectories
- Build semantic understanding: entry points, core logic, infrastructure, support

Ask user if unclear: "I see directories [A], [B], [C]. Is [A] the main application code?"

### Step 2: Identify Tech Stack

Read package manifests (package.json, pyproject.toml, go.mod, Cargo.toml, etc.).
Extract:
- Runtime and version
- Language
- 2-5 key dependencies that define architecture (NOT utilities)

Ask user: "Which 3-5 dependencies are critical to how this system works?"

### Step 3: Trace Data Flow

Read entry points. Follow the flow:
1. Where does request/input arrive?
2. What components process it?
3. Where does data persist or transform?
4. How does response/output return?

Use Mermaid diagrams for complex flows, text for simple ones.

### Step 4: Document Entry Points

Identify the 3-5 files that give fastest path to understanding.
Format as bulleted list with paths and descriptions.

### Step 5: Write ARCHITECTURE.md

Write to `gsd-lite/ARCHITECTURE.md`:

# Architecture

*Mapped: [today's date]*

## Project Structure Overview
[Table mapping directories to semantic meaning]

## Tech Stack
[Runtime, language, 2-5 critical dependencies]

## Data Flow
[Mermaid diagram OR text description]

## Entry Points
[3-5 files with paths and descriptions]

---

Ask for validation: "Does this capture your codebase structure accurately?"

## Anti-Patterns

- Reading every file (use grep/glob to discover, only read key files)
- Generic descriptions ("Main code" vs "FastAPI route handlers")
- Over-documenting (aim for 40-70 lines)
- Listing all dependencies (focus on 2-5 critical ones)
