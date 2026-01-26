# Architecture

**Analysis Date:** 2026-01-26

## Pattern Overview

**Overall:** Modular MCP (Model Context Protocol) Server with Multi-Transport Support

**Key Characteristics:**
- **Protocol-first design:** Built on FastMCP with support for Stdio, HTTP, and WebSocket transports
- **Layered separation:** CLI orchestration, MCP server logic, UI presentation, and filesystem tooling are distinct layers
- **Human-in-the-loop pattern:** Interactive review/approval workflow for file edits via VS Code diff interface
- **Security-centric:** Path validation enforces sandboxed directory access with symlink resolution
- **Stateless HTTP:** Server can run without maintaining request state across connections

## Layers

**CLI Orchestration Layer:**
- Purpose: Entry point and process lifecycle management, transport selection
- Location: `src/fs_mcp/__main__.py`
- Contains: Argument parsing, background process spawning, signal handling
- Depends on: `fs_mcp.server`, `fs_mcp.http_runner`, `fs_mcp.web_ui`
- Used by: Command-line users, Docker containers, CI/CD systems

**MCP Server Core:**
- Purpose: Implements filesystem tools and security logic, defines the protocol interface
- Location: `src/fs_mcp/server.py`
- Contains: Tool definitions (@mcp.tool decorators), path validation, directory initialization
- Depends on: FastMCP, Pydantic, `fs_mcp.edit_tool`
- Used by: All transports (Stdio, HTTP, UI), edit tool

**Edit Tool Layer:**
- Purpose: Sophisticated file editing with proposal/review workflow, multi-edit batching
- Location: `src/fs_mcp/edit_tool.py`
- Contains: EditResult dataclass, RooStyleEditTool class, propose_and_review_logic function
- Depends on: Path validation from server, subprocess (VS Code), difflib
- Used by: `propose_and_review` and `propose_and_review` continuation tools

**HTTP Transport Layer:**
- Purpose: Expose filesystem tools over HTTP REST interface with CORS support
- Location: `src/fs_mcp/http_runner.py`
- Contains: HTTP server initialization, CORS middleware configuration, subprocess entry point
- Depends on: FastMCP HTTP transport, Starlette middleware
- Used by: Remote agents, web clients, container environments

**Web UI Layer:**
- Purpose: Interactive testing interface with tool discovery and schema translation
- Location: `src/fs_mcp/web_ui.py`
- Contains: Streamlit UI, tool execution wrapper, Gemini schema transformation, workspace discovery
- Depends on: Streamlit, google-genai transformers, FastMCP inspect utilities
- Used by: Developers testing tools locally, schema validation

## Data Flow

**Tool Discovery & Initialization:**

1. CLI (`__main__.py`) parses arguments and calls `server.initialize(dirs)`
2. `server.initialize()` validates directories, builds `ALLOWED_DIRS` and `USER_ACCESSIBLE_DIRS`
3. Tools are registered via `@mcp.tool()` decorator on functions in `server.py`
4. FastMCP builds schema from function signatures and docstrings

**Request Path (HTTP Mode):**

1. HTTP client sends request → FastMCP HTTP transport (port 8124)
2. Transport routes to tool function in `server.py`
3. Tool calls `validate_path()` for security check
4. Tool executes filesystem operation
5. Result serialized as MCP response with content blocks
6. Web UI or agent receives JSON response

**Interactive Edit Path (propose_and_review):**

1. Agent calls `propose_and_review(path, old_string, new_string)`
2. `edit_tool.propose_and_review_logic()` prepares temp directory structure
3. Creates `current_<filename>` (original) and `future_<filename>` (proposed)
4. Optionally launches VS Code diff view: `code --diff current future`
5. Blocks in watch loop, polling `future_file.stat().st_mtime`
6. On save: checks if file ends with `\n\n` (approval signal)
   - **APPROVE:** Returns `{"user_action": "APPROVE"}`
   - **REVIEW:** Returns `{"user_action": "REVIEW", "user_feedback_diff": unified_diff}`
7. Agent calls `commit_review()` to finalize changes and clean temp directory

**State Management:**

- **Global state in `server.py`:** `ALLOWED_DIRS`, `USER_ACCESSIBLE_DIRS`, `IS_VSCODE_CLI_AVAILABLE`
  - Initialized once at startup via `initialize()`
  - Read-only after initialization for security
- **Session state:** Temporary directories created per review session (prefix: `mcp_review_`)
  - Lives in system temp directory with strict access rules
  - Cleaned up after `commit_review()` or on error
- **UI session state:** Streamlit `st.session_state` for workspace description caching

## Key Abstractions

**Path Validation Gate:**
- Purpose: Enforce security boundary, prevent directory traversal
- Examples: `src/fs_mcp/server.py` lines 72-124 (`validate_path` function)
- Pattern:
  - Resolve relative paths to base allowed directory
  - Canonicalize absolute paths (resolve symlinks, remove `..`)
  - Verify final path starts with one of `ALLOWED_DIRS`
  - Special case: temp directory (`mcp_review_*`, `pytest-*` prefixes only)

**File Request Model:**
- Purpose: Structured input for multi-file read operations
- Examples: `FileReadRequest` dataclass in `src/fs_mcp/server.py` lines 5-10
- Pattern: Pydantic BaseModel with optional head/tail/start_line/end_line for chunked reading

**Edit Result Dataclass:**
- Purpose: Standardized response from edit operations with diagnostic info
- Examples: `EditResult` in `src/fs_mcp/edit_tool.py` lines 12-19
- Pattern: success flag + message + optional diff/error_type/content for debugging

**Tool Schemas (OpenAI + Gemini):**
- Purpose: Translate FastMCP-generated schemas to provider-specific formats
- Examples: `convert_to_gemini_schema()` in `src/fs_mcp/web_ui.py` lines 132-158
- Pattern: Use `google.genai._transformers.process_schema()` for anyOf-to-nullable conversion, then prune forbidden keys

## Entry Points

**CLI Entry Point:**
- Location: `src/fs_mcp/__main__.py:main()`
- Triggers: `fs-mcp` command or `python -m fs_mcp`
- Responsibilities:
  - Parse arguments (directories, --no-ui, --no-http, host/port)
  - Spawn HTTP server subprocess if `--no-ui` not set
  - Launch Streamlit UI or wait for HTTP server
  - Handle graceful shutdown on Ctrl+C

**HTTP Server Entry Point:**
- Location: `src/fs_mcp/http_runner.py:main()`
- Triggers: Subprocess spawned by `__main__.py` with args `--host`, `--port`, `dirs`
- Responsibilities:
  - Initialize server with allowed directories
  - Configure CORS middleware (allow all origins)
  - Run FastMCP on specified host/port with HTTP transport

**Streamlit UI Entry Point:**
- Location: `src/fs_mcp/web_ui.py` (lines 1-397, top-level execution)
- Triggers: `streamlit run web_ui.py` with CLI args after `--`
- Responsibilities:
  - Parse directories from CLI arguments
  - Initialize server
  - Discover and transform tool schemas
  - Render interactive form and JSON editors

**Tool Functions:**
- Location: `src/fs_mcp/server.py` (decorated with `@mcp.tool()`)
- Examples: `read_files()`, `write_file()`, `list_directory()`, `propose_and_review()`, etc.
- Each tool is an independent entry point when called via MCP protocol

## Error Handling

**Strategy:** Validation-first with detailed error context

**Patterns:**

1. **Security Errors (path validation):**
   - Raise `ValueError` with message: "Access denied: {path} is outside allowed directories"
   - Caught by FastMCP and returned as error content block to agent

2. **File Not Found / Doesn't Exist:**
   - Return user-friendly error string in tool result
   - Example: `read_files()` returns `"File: {path}\nError: {e}"`
   - Tools do not crash; they return partial results with errors

3. **Edit Validation Errors:**
   - `propose_and_review_logic()` returns detailed JSON with error context
   - Includes original file content (if < 5000 lines) to aid debugging
   - Error structure: `{"error": true, "error_type": "validation_error", "message": "...", "file_content": "...", "hint": "..."}`

4. **Permission Errors (directory traversal):**
   - Caught during `pathlib.iterdir()`, suppress and continue (e.g., `list_directory_with_sizes()` line 262)
   - Graceful degradation: skip inaccessible entries instead of failing entire operation

5. **Binary File Errors:**
   - `read_files()` detects UnicodeDecodeError and returns: `"Error: Binary file. Use read_media_file."`
   - Routes user to correct tool for media handling

6. **Schema Transformation Errors (UI):**
   - Try-catch around `inspect_fastmcp()` and schema conversion
   - Display Streamlit error toast if tools cannot be discovered
   - Fall back to raw JSON input if form fails

## Cross-Cutting Concerns

**Logging:**
- Approach: Print-based stderr output for CLI feedback
- Examples: Progress messages like `"🚀 Launching UI on http://..."` (line 88 in `__main__.py`)
- No structured logging framework; relies on user redirection/capture

**Validation:**
- Path validation via `validate_path()` guards all file operations
- Pydantic models validate request shapes (e.g., `FileReadRequest`)
- Edit string matching checks via `count_occurrences()` ensure expected replacements

**Authentication:**
- Not implemented; security model is directory-based (allowed dirs)
- CORS allows all origins in HTTP mode (assumes trusted network)
- Relies on network isolation or firewall for access control in production

**Resource Management:**
- Temporary session directories cleaned up after `commit_review()` or error
- Tempfile cleanup with explicit `shutil.rmtree()` on success/failure paths
- Process cleanup in `__main__.py` finally block: `terminate()` then `kill()` if needed

---

*Architecture analysis: 2026-01-26*
