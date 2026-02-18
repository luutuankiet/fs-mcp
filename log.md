Now I have full context. Let me examine what Gemini reported vs. what my runtime tool schema actually shows. The key question is: **Is Gemini's reported schema accurate, and is the "append" gap real?**

Let me compare the schemas systematically:

---

## Analysis: Gemini's Report vs. My Runtime Schema

### 1. Schema Type Notation Difference

**Gemini reported:**
```json
"type": "OBJECT"
"type": "ARRAY"
"type": "STRING"
"type": "INTEGER"
"type": "BOOLEAN"
```

**My runtime schema (what Claude sees):**
```json
"type": "object"
"type": "array"
"type": "string"
"type": "integer"
"type": "boolean"
```

**Verdict:** This is **expected behavior**. Gemini uses uppercase type constants internally. The `google-genai` SDK transforms lowercase JSON Schema types to uppercase Gemini-native types. This is not a bug — Gemini is reporting what it sees *after* transformation.

---

### 2. Schema Structure Comparison

Let me show you the **actual** schema I'm connected to (verbatim from Claude's system prompt):

**`read_files` — My Runtime Schema:**
```json
{
  "name": "mcp_tools_gsd-lite-fs_read_files",
  "parameters": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": false,
    "properties": {
      "files": {
        "description": "A list of file read requests...",
        "items": {
          "description": "A request to read a file...",
          "properties": {
            "path": {"description": "...", "type": "string"},
            "start_line": {"description": "...", "nullable": true, "type": "integer"},
            "end_line": {"description": "...", "nullable": true, "type": "integer"},
            "head": {"description": "...", "nullable": true, "type": "integer"},
            "tail": {"description": "...", "nullable": true, "type": "integer"},
            "read_to_next_pattern": {"description": "...", "nullable": true, "type": "string"}
          },
          "required": ["path"],
          "type": "object"
        },
        "type": "array"
      },
      "large_file_passthrough": {"description": "...", "type": "boolean"}
    },
    "required": ["files"],
    "type": "object"
  }
}
```

**Key difference from Gemini's report:**
- My schema has `"nullable": true` on optional fields
- Gemini's reported schema **omits `nullable`** — this is expected, Gemini doesn't need it once defaults are handled

---

### 3. The Real Issue: Gemini's Analysis is Correct

**Gemini correctly identified the gap:**

> **"TO APPEND:** Read the last 10-20 lines (using read_files tail=...), copy them as `match_text` to ensure uniqueness, then set `new_string` to `match_text` + `\n` + `new_content`."

This pattern **is not documented** in the `propose_and_review` tool description. Looking at the SPECIAL VALUES section:

```
SPECIAL VALUES FOR match_text
════════════════════════════════════════════════════════════════════
""              = Create new file (file must not exist)
"OVERWRITE_FILE" = Replace entire file content
```

**Missing: How to append to end of file.**

---

## Proposed Enhancement

Based on Gemini's debugging and my verification, here's my recommendation:

### Option A: Add `APPEND_TO_FILE` Sentinel (Clean)

Add a third special value:
```
"APPEND_TO_FILE" = Append new_string to end of file (file must exist)
```

This is the cleanest solution but requires code changes.

### Option B: Document the Workaround (No Code Change)

Update the `match_text` description to include the append pattern:

```
SPECIAL VALUES FOR match_text
════════════════════════════════════════════════════════════════════
""               = Create new file (file must not exist)
"OVERWRITE_FILE" = Replace entire file content

**TO APPEND:** No special value — use the "tail anchor" pattern:
1. Read last 5-10 lines: read_files([{"path": "file.md", "tail": 10}])
2. Copy those lines as match_text (ensures uniqueness)
3. Set new_string = match_text + "\n" + new_content
This replaces the tail with tail+new, effectively appending.
```

---

**Question for you:** 
1. Do you want to add a new `APPEND_TO_FILE` sentinel (cleaner UX, code change required)?
2. Or document the tail-anchor workaround (no code change, relies on agent understanding)?

Also — Gemini's schema parsing looks accurate here. The uppercase types are expected transformation behavior, not a bug. The real issue is the **missing documentation for append semantics**.