# fs-mcp

## What This Is

A remote MCP server that lets AI agents manipulate remote workspaces like VS Code Remote SSH. Users run `uvx fs-mcp` on any server, connect their local AI CLI (Claude Code, OpenCode, Gemini CLI), and immediately start working on the remote codebase — zero setup, instant access.

## Core Value

**One-command remote agent access.** `uvx fs-mcp` on any server → agents can read, write, and explore the codebase immediately. No SSH tunnels, no environment setup, no config files.

## Requirements

### Validated

- ✓ Remote MCP server with HTTP/SSE transport (binds to 0.0.0.0) — existing
- ✓ File read with offset/limit (`start_line`/`end_line`, `head`/`tail`) — existing
- ✓ File write operations — existing
- ✓ Directory listing with size info — existing
- ✓ Path validation and security (sandboxed directory access) — existing
- ✓ `propose_and_review` workflow for human-in-the-loop editing — existing
- ✓ Web UI for manual tool testing — existing
- ✓ Glob-based file search (`search_files`) — existing
- ✓ Zero-setup distribution via `uvx fs-mcp` — existing

### Active

- [ ] **Ripgrep-based grep tool** — content search with line numbers and context lines, optimized for agent context windows
- [ ] **Ripgrep install detection** — helpful error message with platform-specific install command if `rg` not found
- [ ] **Enhanced tool descriptions** — embed grep → read workflow recommendation so weak agents discover the pattern
- [ ] **Remove `grounding_search` placeholder** — cleanup unused stub

### Out of Scope

- Embedding-based semantic search — violates zero-setup constraint (requires pre-indexing)
- AST-aware code search — adds complexity, ripgrep covers 90% of use cases
- Fix propose_and_review SSE timeout — real issue but separate scope (parked)
- Authentication/authorization — security model is directory-based sandboxing

## Context

**The Problem:**
AI agents (Claude Code, OpenCode, Gemini CLI) work great locally but require complex setup for remote codebases. Users want to spin up an agent on any server and start coding immediately.

**The Solution:**
An MCP server that exposes filesystem tools over HTTP. The agent connects, has full read/write/search capabilities, and the human reviews changes via `propose_and_review`.

**Current Gap:**
Agents exploring unfamiliar codebases burn context tokens. The grep → targeted read pattern (used by Claude Code) is optimal but:
1. No grep tool exists yet (only glob-based `search_files`)
2. Tool descriptions don't guide weak agents toward the pattern

**Target Users:**
Anyone using AI coding agents who wants remote codebase access. Primary use: developers with remote servers, shared dev environments, or container-based workflows.

**Weak Agent Consideration:**
GPT-3.5, Gemini Flash, and similar models. They can handle structured output but need explicit guidance in tool descriptions. They won't discover grep → read on their own.

## Constraints

- **Zero Setup**: User runs `uvx fs-mcp`, nothing else. No pre-indexing, no config files, no additional installs (except ripgrep for grep tool)
- **System Dependency**: Ripgrep (`rg`) must be installed for grep tool. Acceptable because it's ubiquitous and fast — provide clear install instructions
- **Context Efficiency**: Search results must be bounded (max matches, context lines) to prevent context overflow in agents
- **Transport Compatibility**: Must work with SSE/streamable-http for remote connections

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use ripgrep via shell instead of Python grep | Fastest, most capable, ubiquitous on dev machines | — Pending |
| Skip embedding-based search | Violates zero-setup — requires pre-indexing phase | — Pending |
| Keep glob and grep as separate tools | Different jobs: glob finds files by name, grep finds content | — Pending |
| Embed workflow guidance in tool descriptions | Weak agents need explicit hints to discover grep → read pattern | — Pending |

---
*Last updated: 2026-01-26 after initialization*

### Agent Workflows

#### The Grep -> Read Pattern

To explore the codebase efficiently, agents should use a two-step pattern:

1.  **`grep_content` to locate**: Use `grep_content` with a regex pattern to find *where* relevant code exists. This returns a small, targeted list of file paths and line numbers.
2.  **`read_files` to inspect**: Use the output from `grep_content` to read only the specific, relevant sections of files.

This is vastly more token-efficient than listing and reading entire files, and provides higher quality context to the agent.

