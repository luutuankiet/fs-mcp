I don't have filesystem access to read the local files directly. However, based on the PROTOCOL.md and discuss.md workflow you've shared, I have sufficient context to understand this is **GSD-Lite itself** — the protocol development project.

---

## Responding to Your Point

You're absolutely right. The ASCII-style headers (`=====`, `-----`) are:

1. **Human visual aids** — great for scanning in a text editor
2. **Token-expensive** — extra characters that add no semantic value
3. **Potentially confusing** — weak agents might not parse them consistently

**Markdown headers are the minimal, universal solution:**

| Current | Proposed | Why |
|---------|----------|-----|
| `===== SECTION =====` | `## SECTION` | Every LLM understands markdown. Zero ambiguity. |
| `--- divider ---` | `---` or just a blank line | Horizontal rule if needed, otherwise whitespace |

**For WORK.md specifically:**

```markdown
## Current Understanding
...

## Session Log
### [LOG-009] - [OBSERVATION] - ASCII headers are not context-friendly - Task: PROTOCOL
...

## Key Events Index
...
```

Clean. Grepable. Weak-agent-proof.

---

**Want me to capture this as a decision/observation to add to LOG-009?** 

And — do you have a way to share the current WORK.md content so I can see the existing log structure and propose the minimal diff?