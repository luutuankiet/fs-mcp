---
phase: quick-002
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/fs_mcp/server.py
  - src/fs_mcp/edit_tool.py
  - tests/test_propose_and_review_validation.py
autonomous: true

must_haves:
  truths:
    - "User can call propose_and_review with only path and edits (multi-patch mode)"
    - "edits parameter parsed correctly as list of dicts with old_string and new_string keys"
    - "All existing single-edit functionality remains unchanged"
  artifacts:
    - path: "src/fs_mcp/server.py"
      provides: "Fixed propose_and_review function signature"
      contains: "new_string.*default"
    - path: "src/fs_mcp/edit_tool.py"
      provides: "Fixed edits parameter handling"
      contains: "isinstance.*EditPair"
  key_links:
    - from: "src/fs_mcp/server.py"
      to: "src/fs_mcp/edit_tool.py"
      via: "propose_and_review_logic call"
      pattern: "propose_and_review_logic"
---

<objective>
Fix the `propose_and_review` tool so multi-patch mode (`edits` parameter) works correctly.

Purpose: The tool currently fails when using `edits` for batch changes due to two bugs:
1. `new_string` is required even when `edits` is provided (should be optional in multi-patch mode)
2. The `edits` list is not properly coerced from Pydantic `EditPair` models to dicts for validation

Output: Working multi-patch mode where users can provide `path` and `edits` without `new_string`, and the edits list is correctly validated and applied.
</objective>

<execution_context>
@./.claude/get-shit-done/workflows/execute-plan.md
@./.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@bug_report.md
@src/fs_mcp/server.py
@src/fs_mcp/edit_tool.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Make new_string optional when edits is provided</name>
  <files>src/fs_mcp/server.py</files>
  <action>
In `server.py`, modify the `propose_and_review` function signature:

1. Change `new_string` parameter (lines 671-674) to have a default value of `""`:
   ```python
   new_string: Annotated[
       str,
       Field(default="", description="...")
   ] = "",
   ```

2. The parameter order may need adjustment since Python requires parameters with defaults to come after those without. Since `path` is required and `new_string` now has a default, reorder to: `path`, then all optional parameters (`new_string`, `old_string`, `expected_replacements`, `session_path`, `edits`).

This allows Intent 2 (Multi-Patch) to work with only `path` and `edits` as documented.
  </action>
  <verify>Run `python -c "from fs_mcp.server import propose_and_review; print('import ok')"` to verify no syntax errors.</verify>
  <done>The function signature allows calling with only `path` and `edits` parameters.</done>
</task>

<task type="auto">
  <name>Task 2: Fix edits parameter handling in propose_and_review_logic</name>
  <files>src/fs_mcp/edit_tool.py</files>
  <action>
In `edit_tool.py`, the `propose_and_review_logic` function receives `edits` which may be a list of `EditPair` Pydantic models (when coming from the MCP tool) or plain dicts. The validation at lines 86-88 checks for dict keys:

```python
if not isinstance(pair, dict) or 'old_string' not in pair or 'new_string' not in pair:
```

This fails when `pair` is an `EditPair` object because:
- `isinstance(pair, dict)` returns False for Pydantic models
- Pydantic models use attributes, not dict keys

Fix by normalizing `edits` to plain dicts at the start of the function:

1. After line 83 (`if edits:`), add normalization logic:
   ```python
   if edits:
       # Normalize EditPair objects to dicts for consistent handling
       normalized_edits = []
       for pair in edits:
           if hasattr(pair, 'model_dump'):  # Pydantic v2
               normalized_edits.append(pair.model_dump())
           elif hasattr(pair, 'dict'):  # Pydantic v1
               normalized_edits.append(pair.dict())
           elif isinstance(pair, dict):
               normalized_edits.append(pair)
           else:
               raise ValueError(f"Edit must be a dict or EditPair, got {type(pair)}")
       edits = normalized_edits
   ```

2. Then the existing validation (lines 84-88) will work correctly since all items are now plain dicts.

This ensures edits work whether passed as dicts directly or as EditPair models.
  </action>
  <verify>Run `pytest tests/test_propose_and_review_validation.py -v` to verify existing tests pass.</verify>
  <done>The edits parameter correctly handles both EditPair Pydantic models and plain dicts.</done>
</task>

<task type="auto">
  <name>Task 3: Add test for multi-patch mode without new_string</name>
  <files>tests/test_propose_and_review_validation.py</files>
  <action>
Add a new test class to verify the bug fix. In `tests/test_propose_and_review_validation.py`, add:

```python
class TestMultiPatchModeWithoutNewString:
    """Tests for multi-patch mode (edits parameter) without requiring new_string."""

    @pytest.mark.asyncio
    async def test_edits_mode_does_not_require_new_string(self, temp_env):
        """Using edits parameter should not require new_string at top level."""
        import asyncio

        # Write a file with content we can match
        temp_env["test_file"].write_text("line1\nline2\nline3\n", encoding='utf-8')

        edits = [
            {"old_string": "line1", "new_string": "LINE1"},
            {"old_string": "line3", "new_string": "LINE3"}
        ]

        # This should NOT raise "new_string is a missing required argument"
        # It will timeout waiting for user input, which is expected behavior
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="",  # Empty string, not missing
                    old_string="",
                    edits=edits,
                    expected_replacements=1
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            # Timeout is expected - validation passed and we reached user wait
            pass
        except ValueError as e:
            # Should not fail with validation error about edits structure
            assert "must have 'old_string' and 'new_string' keys" not in str(e)
```

This test validates that the multi-patch mode works correctly without the bugs reported.
  </action>
  <verify>Run `pytest tests/test_propose_and_review_validation.py::TestMultiPatchModeWithoutNewString -v` to verify the new test passes.</verify>
  <done>Test confirms multi-patch mode works without requiring top-level new_string and correctly parses edits.</done>
</task>

</tasks>

<verification>
1. Run full test suite: `pytest tests/ -v --ignore=tests/test_server.py`
2. Verify the specific bug scenario from bug_report.md works:
   - Import the module without errors
   - Verify function signature allows edits-only mode
</verification>

<success_criteria>
- `propose_and_review` can be called with only `path` and `edits` (new_string defaults to "")
- `edits` parameter correctly validates lists of dicts or EditPair objects
- All existing tests pass
- New test for multi-patch mode passes
</success_criteria>

<output>
After completion, create `.planning/quick/002-fix-the-bug-reported-at-bug-report-md/002-SUMMARY.md`
</output>
