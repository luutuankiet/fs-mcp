# Codebase Concerns

**Analysis Date:** 2026-01-26

## Tech Debt

**Bare Exception Handler in list_directory_with_sizes:**
- Issue: Using naked `except: continue` without specifying exception type (line 262 in `src/fs_mcp/server.py`). This silently catches all exceptions including KeyboardInterrupt and SystemExit, which should never be caught.
- Files: `src/fs_mcp/server.py:262`
- Impact: Errors in file stat operations (permissions, disk issues) are silently ignored, potentially hiding real problems. Makes debugging harder if operations fail unexpectedly.
- Fix approach: Replace with `except (OSError, PermissionError): continue` to catch only expected filesystem errors. This maintains the graceful degradation while allowing system signals to propagate.

**Unimplemented grounding_search Tool:**
- Issue: The `grounding_search` function at line 593-597 in `src/fs_mcp/server.py` is a placeholder that returns "DEVELOPER PLEASE UPDATE THIS WITH ACTUAL CONTENT".
- Files: `src/fs_mcp/server.py:593-597`
- Impact: Tool is exposed in MCP schema but non-functional. Agents attempting to use it will receive placeholder text instead of performing actual search operations. This blocks workflow automation.
- Fix approach: Either implement the search logic (likely RAG/full-text search) or remove the tool entirely. If intended for future use, mark as experimental in docstring and return meaningful error instead of placeholder.

## Known Bugs

**Potential Path Traversal via Symlinks in Temp Directory:**
- Symptoms: While `validate_path` properly resolves symlinks with `.resolve()`, the temporary directory check applies only to paths matching "mcp_review_" or "pytest-" prefixes. Symlinks could potentially bypass these checks if created in allowed directories and linked into the temp directory.
- Files: `src/fs_mcp/server.py:72-124` (validate_path function)
- Trigger: Creating a symlink from an allowed directory that points to a restricted file, then accessing it via the temp directory context.
- Workaround: Current implementation mitigates this by requiring specific naming patterns (`current_` or `future_` prefixes) for review files, which restricts what can be accessed even if symlink bypass occurs.

**Windows Line Ending Handling Edge Case:**
- Symptoms: The `normalize_line_endings` function in `src/fs_mcp/edit_tool.py:29-30` normalizes CRLF/CR to LF, but the matching logic could still fail if the file uses mixed line endings (some CRLF, some LF).
- Files: `src/fs_mcp/edit_tool.py:29-30`, `src/fs_mcp/server.py` read operations
- Trigger: Files with inconsistent line endings on Windows or from merged sources
- Workaround: The normalization happens before comparison, so most cases work. Full testing with mixed line-ending files would confirm edge cases.

## Security Considerations

**CORS Configured as Wildcard in HTTP Mode:**
- Risk: Line 21 in `src/fs_mcp/http_runner.py` sets `allow_origins=["*"]`, which allows any domain to make requests to the HTTP server. This could expose the filesystem API to unauthorized cross-origin requests.
- Files: `src/fs_mcp/http_runner.py:18-26`
- Current mitigation: The server still validates all paths through the security barrier in `validate_path()`, so unauthorized path access is blocked. However, CSRF attacks from web pages could make requests on behalf of users.
- Recommendations:
  1. Add configuration option to restrict CORS to specific origins (e.g., environment variable)
  2. Document the security implications clearly in README
  3. Consider requiring authentication token in HTTP mode, especially for write operations
  4. Restrict HTTP server to localhost by default, only expose globally when explicitly configured

**Temp Directory Access Pattern Restrictions Are Partial:**
- Risk: The temp directory validation only restricts access to specific file name patterns (`current_*`, `future_*`) within `mcp_review_*` and `pytest-*` directories. However, any code that runs within those directories during `propose_and_review` sessions could still write arbitrary files.
- Files: `src/fs_mcp/server.py:106-120`
- Current mitigation: Review directories are created fresh with `tempfile.mkdtemp()` and cleaned up after session, so damage is isolated to the session.
- Recommendations:
  1. Document the trust model: "gsd-lite directory auto-approves all edits" (line 87 in `src/fs_mcp/edit_tool.py`) means this directory is a known safe zone
  2. Consider adding audit logging for all operations in temp review directories
  3. Add option to require approval even for gsd-lite directory on sensitive machines

**JSON Error Responses Include File Content:**
- Risk: When validation fails in `propose_and_review_logic`, error responses include the full file content if it has fewer than 5000 lines (e.g., lines 103-105, 177-179 in `src/fs_mcp/edit_tool.py`). If files contain sensitive data, this leaks them through error messages.
- Files: `src/fs_mcp/edit_tool.py:97-106, 171-180, 236-253, 278-282`
- Current mitigation: The 5000-line threshold provides some protection for large files
- Recommendations:
  1. Add configuration to disable file content in error responses
  2. Implement sensitive-file detection (e.g., `.env`, `.key`, `credentials`)
  3. For large files, only include the matching context lines rather than entire file
  4. Add warning in error response when file content is included

## Performance Bottlenecks

**Large File Handling via Full Read into Memory:**
- Problem: `read_files` with `head`/`tail` parameters still reads file modifications with `f.readlines()` into memory (line 194 in `src/fs_mcp/server.py`). For very large files (GB+), this causes memory bloat.
- Files: `src/fs_mcp/server.py:141-204`
- Cause: Using Python's file readlines which loads entire file into memory rather than streaming.
- Improvement path:
  1. For tail operations, use `collections.deque` with maxlen for memory-efficient last-N-lines
  2. For head operations, consider early termination reading
  3. Add warning in docstring for files over 100MB recommending chunked reading

**JSON Structure Analysis on Large Files:**
- Problem: `_analyze_json_structure` at line 423 calls `json.loads(content)` on files up to 10MB, which creates full in-memory object graphs that are discarded after analysis.
- Files: `src/fs_mcp/server.py:344-348`
- Cause: 10MB threshold is generous for token budgets; parsing large JSON structures is expensive
- Improvement path:
  1. Reduce threshold to 1MB for JSON parsing
  2. Implement streaming JSON parser for structure analysis only (keys, array counts)
  3. Cache analysis results for frequently-analyzed files

**CSV Analysis Uses String Split Without Validation:**
- Problem: `_analyze_csv_structure` at line 457 uses `content.split(',')` which is naive and will fail on quoted fields containing commas. Large CSV files will be misparsed.
- Files: `src/fs_mcp/server.py:457-478`
- Cause: Quick implementation without CSV module
- Improvement path: Use Python's `csv` module or at least handle quoted fields correctly

## Fragile Areas

**Complex Path Validation Logic:**
- Files: `src/fs_mcp/server.py:72-124`
- Why fragile: Multiple layers of validation (relative path resolution, allowed directory check, temp directory special case) make it easy to introduce security gaps if modified. The temp directory logic especially is intricate (lines 106-120).
- Safe modification: Always add tests for any change to path validation. Current test coverage exists (`test_security_barrier`, `test_temp_file_access_security`) but new scenarios should have corresponding tests.
- Test coverage: Security tests exist but don't cover edge cases like symlinks pointing outside allowed dirs, deeply nested temp directories, or Unicode path names.

**propose_and_review Session State Machine:**
- Files: `src/fs_mcp/edit_tool.py:66-338`
- Why fragile: Complex state management with three intents (new single-edit, new multi-edit, continuing session) and multiple error paths. User feedback interpretation (detecting approval via double-newline) is brittle.
- Safe modification: Changes to user action detection (lines 312-336) need comprehensive testing. The `user_feedback_diff` computation must match agent's expectations exactly.
- Test coverage: Basic tests exist (`test_identity_edit_on_real_file`, `test_edit_preserves_literal_escape_sequences`) but session continuation with user edits and multi-edit scenarios lack coverage.

**Streamlit UI Tool Discovery and Invocation:**
- Files: `src/fs_mcp/web_ui.py:109-184`
- Why fragile: Uses dynamic inspection to discover and call tools. If tool signature changes (parameters added/removed) or if tool functions have inconsistent behavior with/without decorators, the UI breaks.
- Safe modification: Any tool signature change requires testing in the UI. The `.fn` accessor for unwrapping decorators (line 177) is a code smell indicating tight coupling.
- Test coverage: No tests for the UI tool discovery/execution pipeline. Manual testing required.

## Scaling Limits

**Session Cleanup Not Automatic on Failure:**
- Current capacity: One review session per invocation, cleanup only on commit or completion
- Limit: If a session is started but never approved or committed, the temporary directory persists indefinitely (though it uses OS temp which eventually cleans up)
- Scaling path:
  1. Add session TTL (time-to-live) with automatic cleanup after 1-2 hours
  2. Implement session registry to track active sessions and clean orphaned ones
  3. Add CLI command to manually list and clean old sessions

**Web UI Single-Threaded Tool Execution:**
- Current capacity: One tool at a time (blocking execution at line 364 in `src/fs_mcp/web_ui.py`)
- Limit: Multiple users on same Streamlit instance cannot run tools concurrently; they block each other
- Scaling path: Streamlit limitation, not code issue. Would require refactoring to async task queue backend if multi-user support needed.

## Dependencies at Risk

**google-genai >= 1.56.0 with Loose Version Constraint:**
- Risk: The dependency in `pyproject.toml:10` allows any version >= 1.56.0, but schema transformation logic in `web_ui.py:142` uses undocumented internal API `_transformers.process_schema()`. Future versions could break this without notice.
- Impact: Web UI schema export to Gemini would fail silently or produce invalid schemas
- Migration plan:
  1. Pin to specific tested version range (e.g., `>=1.56.0,<2.0.0`)
  2. Add version compatibility tests in CI
  3. Monitor google-genai releases and update constraints proactively
  4. Consider reimplementing schema transformation without internal API dependency

**fastmcp == 2.14.3 as Exact Pin:**
- Risk: Exact version pin means no bug fixes or security updates from minor versions
- Impact: Security vulnerabilities in fastmcp would not be patched until manual upgrade
- Migration plan: Use `^2.14.3` (or `~2.14`) compatible release constraint instead, allowing patch updates

## Missing Critical Features

**No Audit Logging:**
- Problem: File modifications, especially via `propose_and_review` and auto-approved gsd-lite edits, have no audit trail. An agent could modify code without human oversight being recorded.
- Blocks: Compliance requirements for sensitive environments, forensic analysis of unintended changes
- Implementation path: Add structured logging of all write operations (file path, diff, approval status, timestamp, user) to a central log

**No File Backup Before Edit:**
- Problem: Edits are applied directly without creating backups. If an edit is incorrect, the original file state is lost.
- Blocks: Safe rollback, comparison with previous versions
- Implementation path: Implement automatic backup system (e.g., .backup file or version directory) before applying edits

**No Multi-Directory Atomic Operations:**
- Problem: Tools operate on single files or directories; no support for atomic operations across multiple files (e.g., rename with cross-directory refactor safety checks)
- Blocks: Complex refactoring workflows
- Implementation path: Add batch operation support with transaction semantics (all-or-nothing)

## Test Coverage Gaps

**propose_and_review Session Continuation:**
- What's not tested: The `session_path` parameter in `propose_and_review` when a user provides feedback and edits. Current tests only cover new sessions.
- Files: `src/fs_mcp/edit_tool.py:151-205`
- Risk: User feedback loops with agent retries could fail silently or produce incorrect diffs
- Priority: High - this is a core user-facing feature

**Multi-Edit Batch Operations:**
- What's not tested: The `edits` parameter with multiple old_string/new_string pairs, especially error handling when one edit fails
- Files: `src/fs_mcp/edit_tool.py:162-184, 214-264`
- Risk: Partial edits could leave files in inconsistent state
- Priority: High - feature is documented but untested

**Binary File Handling:**
- What's not tested: `read_media_file` with various binary formats (corrupted files, empty files, very large files), error cases
- Files: `src/fs_mcp/server.py:206-220`
- Risk: Could crash or return invalid base64 data
- Priority: Medium - less critical path but could cause issues

**HTTP Server with CORS Requests:**
- What's not tested: Actual cross-origin requests to the HTTP server, request validation with wildcard CORS enabled
- Files: `src/fs_mcp/http_runner.py`
- Risk: Untested security surface
- Priority: High - security-relevant

**directory_tree with Deep/Complex Hierarchies:**
- What's not tested: Very deep directory structures (100+ levels), symbolic links, permission errors at various depths, circular symlinks
- Files: `src/fs_mcp/server.py:481-510`
- Risk: Could hang or crash on malformed filesystem structures
- Priority: Medium - edge case

**Error Path Handling in Streamlit UI:**
- What's not tested: How UI handles tools that raise exceptions, tools with invalid signatures, inspect failure scenarios
- Files: `src/fs_mcp/web_ui.py:205-250`
- Risk: UI could crash instead of displaying friendly error
- Priority: Low - UX issue but not critical

---

*Concerns audit: 2026-01-26*
