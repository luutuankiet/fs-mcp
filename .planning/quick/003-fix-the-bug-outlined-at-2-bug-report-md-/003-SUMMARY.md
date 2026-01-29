---
type: quick
task_id: "003"
title: Fix pytest failures from validation order and schema description issues
completed: 2026-01-29
duration: "3 minutes"
subsystem: testing
tags: [pytest, testing, schema-validation, async, pydantic]
files_modified:
  - tests/test_concurrent_review.py
  - tests/test_tool_arg_descriptions.py
  - tests/test_propose_and_review_validation.py
---

# Quick Task 003: Fix pytest failures from validation order and schema description issues

**One-liner:** Fixed 11 failing pytest tests by adding async decorators, handling nested anyOf schema structures, and updating length threshold from 500 to 2000 chars

## Objective

Restore passing test suite after recent propose_and_review changes by fixing:
1. Missing pytest.mark.asyncio decorators (2 tests)
2. Schema description extraction from nested anyOf structures (6 tests)
3. Incorrect old_string length validation threshold (3 tests)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix async test decorators in test_concurrent_review.py | e691154 | tests/test_concurrent_review.py |
| 2 | Fix schema description assertions in test_tool_arg_descriptions.py | bd4ec95 | tests/test_tool_arg_descriptions.py |
| 3 | Fix length threshold in validation tests | bf58c1f | tests/test_propose_and_review_validation.py |

## Changes Made

### Task 1: Async Test Decorators

**Root cause:** Async test functions lacked `@pytest.mark.asyncio` decorator

**Fix applied:**
- Added pytest import to test_concurrent_review.py
- Added `@pytest.mark.asyncio` to `test_concurrent_async_operations`
- Added `@pytest.mark.asyncio` to `test_async_function_verification`

**Result:** Both async tests now execute properly without "async def functions are not natively supported" errors

### Task 2: Schema Description Assertions

**Root cause:** Optional parameters with `Annotated[Optional[T], Field(...)]` create nested anyOf structures where descriptions end up in inner schema, not at top level

**Schema structure example:**
```json
{
  "anyOf": [
    {"anyOf": [...], "default": None, "description": "The actual description"},
    {"type": "null"}
  ]
}
```

**Fix applied:**
- Created `get_description_from_schema()` helper function to traverse nested anyOf structures
- Updated 4 test methods to use helper instead of direct description access:
  - `test_section_patterns_has_description`
  - `test_session_path_has_description`
  - `test_edits_has_description`
  - `test_all_top_level_params_have_descriptions`
- Updated `test_required_parameters` to remove `new_string` from required list (now optional with default="")

**Result:** All 6 schema description tests now pass, properly handling Pydantic's nested anyOf structure for optional annotated fields

### Task 3: Length Validation Threshold

**Root cause:** Tests used 501 chars but actual `OLD_STRING_MAX_LENGTH = 2000` in edit_tool.py

**Fix applied:**
- Updated module docstring: 500 → 2000 characters
- Renamed and updated 3 test functions:
  - `test_old_string_over_500_chars_raises_error` → `test_old_string_over_2000_chars_raises_error` (501 → 2001 chars)
  - `test_old_string_exactly_500_chars_is_allowed` → `test_old_string_exactly_2000_chars_is_allowed` (500 → 2000 chars)
  - `test_old_string_under_500_chars_allowed` → `test_old_string_under_2000_chars_allowed`
- Updated 2 edits parameter tests to use 2001 chars instead of 501

**Result:** All length validation tests now use correct 2000-char threshold matching production code

## Verification

```bash
pytest -v
# Result: 59 passed, 1 warning in 9.87s
```

All tests pass:
- 2 async decorator tests pass ✓
- 35 schema description tests pass ✓
- 13 validation tests pass ✓
- 9 other tests pass ✓

## Deviations from Plan

None - plan executed exactly as written.

## Technical Decisions

**Decision 1: Helper function for schema description extraction**
- **Context:** Pydantic generates nested anyOf structures for Optional[Annotated[...]] fields
- **Approach:** Created reusable helper to traverse schema and find description
- **Rationale:** More maintainable than updating each test individually; handles future schema changes

**Decision 2: Updated required parameters test**
- **Context:** `new_string` is now optional with default="" (from quick-002 changes)
- **Approach:** Removed `new_string` from required assertions, kept only `path`
- **Rationale:** Test should reflect actual schema structure after recent API changes

## Dependencies

**Requires:**
- quick-002 (multi-patch mode changes that made new_string optional)

**Provides:**
- Passing test suite (59/59 tests)
- Proper test coverage for async operations
- Correct validation threshold tests

**Affects:**
- Future test development (helper function available for reuse)

## Next Steps

No follow-up required. Test suite is fully passing and validates:
1. Async non-blocking behavior
2. Schema descriptions for all tool parameters
3. Validation rules (blank old_string, length limits, OVERWRITE_FILE sentinel)

## Notes

- All 11 failing tests traced back to recent propose_and_review API changes
- Tests were correct in intent, just needed synchronization with updated implementation
- No production code changes required - purely test fixes
- Duration: ~3 minutes (very fast - straightforward test updates)
