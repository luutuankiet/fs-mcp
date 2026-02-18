# fix: Add explicit `APPEND_TO_FILE` mode and clarify tool semantics

**Status:** Ready for Merge

## Context & Discovery
During cross-model testing of the `fs-mcp` server, we observed a consistent failure pattern with weaker reasoning models (specifically Gemini 1.5 Pro). These models struggled to use the `propose_and_review` tool for appending content to files—a critical operation for task logging.

The root cause was semantic: the tool required an implicit "tail-anchor" pattern (read file tail → use as match text → replace with match + new content). While strong models like Claude Opus derive this pattern naturally, weaker models fail to infer the multi-step dependency, leading to hallucinations or failed edits.

## Why This Change
This PR bridges the semantic gap between the tool's capabilities and the reasoning limits of current-generation models. By making the "Append" operation explicit, we:
1.  **Reduce Hallucinations:** Models no longer need to "guess" how to append.
2.  **Improve Reliability:** The `APPEND_TO_FILE` sentinel provides a deterministic path for the most frequent file operation (logging).
3.  **Clarify Usage:** Explicitly documenting the 5 mutually exclusive modes prevents invalid parameter combinations.

## What Changed

### 1. New `APPEND_TO_FILE` Sentinel
We implemented a dedicated sentinel value that simplifies the append operation into a single atomic instruction.

*Before (Implicit & Fragile):*
> "Read the last 10 lines, verify uniqueness, then replace that block with itself plus the new content."

*After (Explicit & Robust):*
> "Append this content to the file."

Code-wise, this introduces `APPEND_SENTINEL` logic in `src/fs_mcp/edit_tool.py` that bypasses the match-verification loop and directly appends to the file buffer.

### 2. Documentation Overhaul
The `propose_and_review` tool description was refactored to explicitly categorize its five operating modes. This "menu" approach helps weaker models select the correct tool invocation pattern:
1.  **SINGLE EDIT:** Standard find-and-replace
2.  **BATCH EDIT:** Prioritized for efficiency (multiple edits in one call)
3.  **NEW FILE:** Creating non-existent files
4.  **OVERWRITE:** Replacing entire file content
5.  **APPEND:** The new mode for adding to the end of a file

### 3. Efficiency Improvements
We updated the `edits` parameter description to strongly encourage BATCH mode for *any* multi-change operation. This addresses a common inefficiency where models would make 3 separate tool calls for 3 changes, tripling token costs and user review fatigue.

## Verification
- **Gap Coverage:** Addresses the critical missing append pattern and clarifies mode exclusivity.
- **Soundness:** Verified implementation of `APPEND_SENTINEL` in `edit_tool.py`, ensuring it works correctly in both single and batch edit modes.
- **Tests:** Added `tests/test_append_sentinel.py` to verify the new append behavior.

## Checklist
- [x] Implements `APPEND_TO_FILE` logic
- [x] Updates docstrings in `server.py` with clear mode definitions
- [x] Verifies soundness of implementation
- [x] Tests included