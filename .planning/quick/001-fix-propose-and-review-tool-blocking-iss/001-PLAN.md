---
phase: quick-001
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/fs_mcp/edit_tool.py
  - src/fs_mcp/server.py
autonomous: true

must_haves:
  truths:
    - "propose_and_review tool does not block other tool calls when review is pending"
    - "Multiple clients can use propose_and_review concurrently without interference"
    - "Server remains responsive during long review sessions"
  artifacts:
    - path: "src/fs_mcp/edit_tool.py"
      provides: "Async propose_and_review_logic implementation"
      min_lines: 300
    - path: "src/fs_mcp/server.py"
      provides: "Async propose_and_review tool wrapper"
      exports: ["propose_and_review"]
  key_links:
    - from: "src/fs_mcp/server.py"
      to: "src/fs_mcp/edit_tool.py"
      via: "async function call"
      pattern: "await propose_and_review_logic"
---

<objective>
Fix the blocking behavior in propose_and_review tool that prevents concurrent requests.

Purpose: The current synchronous implementation uses `time.sleep(1)` in a while loop (lines 304-306 in edit_tool.py), blocking the entire request handler thread while waiting for user review. This causes:
1. Client timeouts leading to duplicate POST requests
2. Other tool calls from the same client to be blocked
3. Poor multi-client concurrency

Output: Async implementation using asyncio that allows FastMCP's async runtime to handle other requests during review wait.
</objective>

<execution_context>
@./.claude/get-shit-done/workflows/execute-plan.md
@./.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md

# Current Implementation
@src/fs_mcp/edit_tool.py
@src/fs_mcp/server.py

# Architecture Context
The server uses FastMCP 2.14.3 with stateless HTTP mode. FastMCP is async-based, but our tool implementations are synchronous. The blocking `while True: time.sleep(1)` loop in propose_and_review_logic holds up the request thread.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Convert propose_and_review_logic to async</name>
  <files>src/fs_mcp/edit_tool.py</files>
  <action>
Replace the synchronous blocking pattern in propose_and_review_logic with async/await:

1. Change function signature: `def propose_and_review_logic(...)` → `async def propose_and_review_logic(...)`

2. Replace the blocking wait loop (lines 303-306):
   ```python
   # OLD (BLOCKING):
   initial_mod_time = future_file_path.stat().st_mtime
   while True:
       time.sleep(1)
       if future_file_path.stat().st_mtime > initial_mod_time: break
   ```

   With async version:
   ```python
   # NEW (NON-BLOCKING):
   import asyncio
   initial_mod_time = future_file_path.stat().st_mtime
   while True:
       await asyncio.sleep(1)  # Yields control to event loop
       if future_file_path.stat().st_mtime > initial_mod_time: break
   ```

3. Add `import asyncio` at the top of the file if not already present

4. Keep all other logic identical - only change the blocking sleep to async sleep

Why async sleep matters: `await asyncio.sleep(1)` yields control back to FastMCP's event loop, allowing other requests to be processed during the wait. `time.sleep(1)` blocks the entire thread.
  </action>
  <verify>
1. Check that function signature is `async def propose_and_review_logic`
2. Verify `import asyncio` is present
3. Verify `await asyncio.sleep(1)` replaces `time.sleep(1)`
4. Run: `python -m py_compile src/fs_mcp/edit_tool.py` (syntax check)
  </verify>
  <done>
propose_and_review_logic is async and uses asyncio.sleep instead of time.sleep, allowing concurrent request handling
  </done>
</task>

<task type="auto">
  <name>Task 2: Update server.py tool wrapper to be async</name>
  <files>src/fs_mcp/server.py</files>
  <action>
Update the propose_and_review tool wrapper to match the async signature:

1. Find the `@mcp.tool()` decorated `propose_and_review` function (around line 573)

2. Change function signature from:
   ```python
   @mcp.tool()
   def propose_and_review(path: str, new_string: str, ...) -> str:
   ```

   To:
   ```python
   @mcp.tool()
   async def propose_and_review(path: str, new_string: str, ...) -> str:
   ```

3. Change the return statement from:
   ```python
   return propose_and_review_logic(...)
   ```

   To:
   ```python
   return await propose_and_review_logic(...)
   ```

4. Keep all parameters and the docstring unchanged

Why this matters: FastMCP's @mcp.tool() decorator supports both sync and async tool functions. When a tool function is async, FastMCP automatically handles it with await in its async request handler, allowing proper concurrency.
  </action>
  <verify>
1. Check that function signature is `async def propose_and_review`
2. Verify `return await propose_and_review_logic(...)` is used
3. Run: `python -m py_compile src/fs_mcp/server.py` (syntax check)
4. Run: `python -c "from fs_mcp import server; import inspect; print('Is async:', inspect.iscoroutinefunction(server.propose_and_review))"` should print `True`
  </verify>
  <done>
propose_and_review tool is async and properly awaits the async logic function, enabling non-blocking operation
  </done>
</task>

<task type="auto">
  <name>Task 3: Test concurrent request handling</name>
  <files>tests/test_concurrent_review.py</files>
  <action>
Create a test to verify the fix works:

1. Create `tests/test_concurrent_review.py` with test code that:
   - Starts the HTTP server in test mode
   - Sends a propose_and_review request (which will block waiting for file save)
   - Immediately sends another request to a different tool (e.g., list_allowed_directories)
   - Verifies the second request completes successfully without waiting for the review

2. Test structure:
   ```python
   import pytest
   import asyncio
   import httpx
   import tempfile
   from pathlib import Path

   @pytest.mark.asyncio
   async def test_concurrent_requests_during_review():
       """Verify propose_and_review doesn't block other requests"""
       # 1. Setup: Create temp file
       # 2. Start propose_and_review in background (asyncio.create_task)
       # 3. Immediately call another tool
       # 4. Verify second tool responds quickly (< 2 seconds)
       # 5. Save the review file to unblock first request
       # 6. Verify both complete successfully
   ```

3. Run the test: `pytest tests/test_concurrent_review.py -v`

If pytest or httpx are not in dependencies, use a manual test script instead that uses curl or the requests library.
  </action>
  <verify>
1. Test file exists at `tests/test_concurrent_review.py`
2. Run: `pytest tests/test_concurrent_review.py -v` or manual script
3. Verify: Second request completes in < 2 seconds even while review is pending
4. Verify: No errors about blocked connections or timeouts
  </verify>
  <done>
Test confirms that propose_and_review no longer blocks concurrent requests to other tools
  </done>
</task>

</tasks>

<verification>
After all tasks complete:

1. **Syntax verification**: Both files compile without errors
2. **Async verification**: `inspect.iscoroutinefunction(server.propose_and_review)` returns True
3. **Concurrency verification**: Test demonstrates multiple requests can be handled during review wait
4. **Functionality verification**: propose_and_review still works correctly for its original use case

Manual verification steps:
1. Start server: `uvx fs-mcp --http-port 8124`
2. In one terminal: Call propose_and_review via HTTP/curl (will block waiting for save)
3. In another terminal: Call list_allowed_directories immediately after
4. Expected: Second call returns immediately, not blocked by first
5. Save the review file to unblock first call
6. Expected: First call completes successfully
</verification>

<success_criteria>
- [x] propose_and_review_logic is async with asyncio.sleep
- [x] propose_and_review tool wrapper is async with await
- [x] Files compile without syntax errors
- [x] Test or manual verification confirms concurrent requests work
- [x] Original propose_and_review functionality preserved
- [x] No blocking behavior when multiple clients connect
</success_criteria>

<output>
After completion, create `.planning/quick/001-fix-propose-and-review-tool-blocking-iss/001-SUMMARY.md`
</output>
