---
type: quick
task_id: "003"
title: Fix pytest failures from validation order and schema description issues
files_modified:
  - tests/test_concurrent_review.py
  - tests/test_tool_arg_descriptions.py
  - tests/test_propose_and_review_validation.py
---

<objective>
Fix 11 failing pytest tests across three categories:
1. Async test decorator issues (2 tests in test_concurrent_review.py)
2. Schema description assertion issues (6 tests in test_tool_arg_descriptions.py)
3. Wrong length threshold in validation tests (3 tests in test_propose_and_review_validation.py)

Purpose: Restore passing test suite after recent propose_and_review changes.
Output: All 59 tests pass with `pytest`.
</objective>

<context>
@2_bug_report.md
@pytest_fails.md
@src/fs_mcp/edit_tool.py
@tests/test_concurrent_review.py
@tests/test_tool_arg_descriptions.py
@tests/test_propose_and_review_validation.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix async test decorators in test_concurrent_review.py</name>
  <files>tests/test_concurrent_review.py</files>
  <action>
Add `@pytest.mark.asyncio` decorator to both async test functions:
- `test_concurrent_async_operations` (line 21)
- `test_async_function_verification` (line 82)

The tests are defined as `async def` but lack the pytest-asyncio marker needed
for pytest to run them properly.

Import pytest at the top if not already imported.
  </action>
  <verify>Run `pytest tests/test_concurrent_review.py -v` - both tests should pass</verify>
  <done>Both async tests pass without "async def functions are not natively supported" errors</done>
</task>

<task type="auto">
  <name>Task 2: Fix schema description assertions in test_tool_arg_descriptions.py</name>
  <files>tests/test_tool_arg_descriptions.py</files>
  <action>
The issue: Optional parameters with `Annotated[Optional[T], Field(...)]` create a nested
`anyOf` structure where the description ends up in the INNER structure, not at top level.

Example schema structure causing failures:
```json
{
  "anyOf": [
    {"anyOf": [...], "default": None, "description": "The actual description"},
    {"type": "null"}
  ]
}
```

Create a helper function at module level (after imports):

```python
def get_description_from_schema(param_schema: dict) -> str | None:
    """Extract description from schema, handling nested anyOf structures."""
    if "description" in param_schema:
        return param_schema["description"]
    # Check nested anyOf structures (common with Optional[Annotated[...]])
    if "anyOf" in param_schema:
        for option in param_schema["anyOf"]:
            if "description" in option:
                return option["description"]
    return None
```

Update these specific test methods:

1. `test_section_patterns_has_description` (line 111-116):
   Replace:
   ```python
   assert "description" in section_patterns
   assert "section" in section_patterns["description"].lower() or "def" in section_patterns["description"].lower()
   ```
   With:
   ```python
   desc = get_description_from_schema(section_patterns)
   assert desc is not None, "section_patterns missing description"
   assert "section" in desc.lower() or "def" in desc.lower()
   ```

2. `test_session_path_has_description` (line 222-227):
   Replace direct `assert "description" in session_path` with helper function check.

3. `test_edits_has_description` (line 229-234):
   Replace direct `assert "description" in edits` with helper function check.

4. `test_required_parameters` for propose_and_review (line 253-258):
   `new_string` is now optional (has default="") so remove:
   ```python
   assert "new_string" in schema["required"]
   ```
   Keep only `assert "path" in schema["required"]`.

5. `test_all_top_level_params_have_descriptions` (line 271-277):
   Replace:
   ```python
   assert "description" in param_schema, \
       f"Tool '{tool_name}' parameter '{param_name}' missing description"
   ```
   With:
   ```python
   desc = get_description_from_schema(param_schema)
   assert desc is not None, \
       f"Tool '{tool_name}' parameter '{param_name}' missing description"
   ```
  </action>
  <verify>Run `pytest tests/test_tool_arg_descriptions.py -v` - all tests should pass</verify>
  <done>All 6 failing schema tests pass, properly handling nested anyOf structures</done>
</task>

<task type="auto">
  <name>Task 3: Fix length threshold in validation tests</name>
  <files>tests/test_propose_and_review_validation.py</files>
  <action>
Root cause: Tests use 501 chars but `OLD_STRING_MAX_LENGTH = 2000` in edit_tool.py.
The tests incorrectly assume a 500-char limit when the actual limit is 2000 chars.

Update these tests to use 2001 characters (just over 2000 limit):

1. `test_old_string_over_500_chars_raises_error` (line 122-139):
   - Rename to `test_old_string_over_2000_chars_raises_error`
   - Change `"x" * 501` to `"x" * 2001`
   - Update docstring: "old_string over 2000 characters should raise ValueError"

2. `test_old_string_exactly_500_chars_is_allowed` (line 141-160):
   - Rename to `test_old_string_exactly_2000_chars_is_allowed`
   - Change `"x" * 500` to `"x" * 2000`
   - Update docstring accordingly

3. `test_old_string_under_500_chars_allowed` (line 162-179):
   - Rename to `test_old_string_under_2000_chars_allowed`
   - Change comment/docstring to mention 2000 not 500

4. `test_edits_with_long_old_string_raises_error` (line 207-227):
   - Change `"x" * 501` to `"x" * 2001`
   - Update docstring: "old_string over 2000 chars in edits..."

5. `test_multiple_edits_validates_all` (line 229-250):
   - Change `"y" * 501` to `"y" * 2001`
   - Update comment: "# This one is too long (over 2000)"
  </action>
  <verify>Run `pytest tests/test_propose_and_review_validation.py -v` - all tests should pass</verify>
  <done>Length validation tests use correct 2001-char threshold matching OLD_STRING_MAX_LENGTH=2000</done>
</task>

</tasks>

<verification>
```bash
# Run full test suite
pytest -v

# Expected: 59 passed, 0 failed
```
</verification>

<success_criteria>
- All 59 tests pass
- No test failures related to async decorators
- No test failures related to schema descriptions
- No test failures related to old_string length validation
</success_criteria>

<output>
After completion, update STATE.md with quick task 003 completion.
</output>
