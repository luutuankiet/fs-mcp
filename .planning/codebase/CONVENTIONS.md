# Coding Conventions

**Analysis Date:** 2026-01-26

## Naming Patterns

**Files:**
- Lowercase with underscores: `server.py`, `edit_tool.py`, `web_ui.py`, `http_runner.py`, `__main__.py`
- Test files use `test_` prefix: `test_server.py`, `test_edit_tool.py`

**Functions:**
- snake_case for all functions: `validate_path()`, `read_files()`, `format_size()`, `list_directory()`, `get_file_info()`
- Private functions (internal only) prefixed with underscore: `_calculate_adaptive_chunk_size()`, `_analyze_json_structure()`, `_analyze_csv_structure()`, `_prepare_edit()`
- Decorator functions use `@mcp.tool()` or `@pytest.fixture`

**Variables:**
- snake_case for local variables: `original_content`, `normalized_content`, `error_response`, `edit_pairs`
- CONSTANT_UPPERCASE_SNAKE_CASE for module-level constants: `USER_ACCESSIBLE_DIRS`, `ALLOWED_DIRS`, `IS_VSCODE_CLI_AVAILABLE`, `APPROVAL_KEYWORD`

**Types and Classes:**
- PascalCase for class names: `FileReadRequest`, `EditResult`, `RooStyleEditTool`
- Pydantic models inherit from `BaseModel`: `FileReadRequest(BaseModel)`
- Dataclasses use `@dataclass` decorator: `EditResult` in `edit_tool.py`

## Code Style

**Formatting:**
- No explicit formatter configured (no `.black`, `.flake8`, or `.pylintrc` files)
- Follows Python PEP 8 conventions de facto
- Line length: Generally kept reasonable (longest observed lines in `propose_and_review_logic` function around 100 characters)

**Linting:**
- No linter configuration files present (no `eslint`, `pylint`, or `flake8` config)
- Type hints used consistently: `def read_files(files: List[FileReadRequest]) -> str:`, `def format_size(size_bytes: float) -> str:`

**Indentation:**
- 4 spaces throughout all files
- Consistent within classes and nested functions

## Import Organization

**Order:**
1. Standard library imports: `json`, `os`, `sys`, `tempfile`, `time`, `shutil`, `subprocess`, `argparse`, `inspect`, etc.
2. Third-party library imports: `fastmcp`, `pydantic`, `starlette`, `streamlit`, `google.genai`, etc.
3. Local relative imports: `from .edit_tool import ...`, `from fs_mcp import server`

**Path Aliases:**
- No path aliases configured in `pyproject.toml`
- Uses relative imports for same-package modules: `from .edit_tool import EditResult, RooStyleEditTool`

**Examples from codebase:**
- `server.py` line 1-27: Standard lib first, then third-party (pydantic, fastmcp, pathlib), then relative imports
- `edit_tool.py` line 1-9: Standard lib (dataclasses, typing, difflib, json, etc.) then third-party (pathlib is stdlib)

## Error Handling

**Patterns:**
- Broad exception catching with `except Exception as e:` for user-facing operations
- Specific exception catching for critical paths: `except UnicodeDecodeError:`, `except json.JSONDecodeError:`, `except PermissionError:`, `except FileNotFoundError:`
- Errors returned as strings in tool responses when non-critical: `"Error: Is a directory"`, `"Error: Binary file. Use read_media_file."`
- Errors raised as exceptions with descriptive messages for validation failures: `raise ValueError(f"Access denied: ...")`, `raise FileNotFoundError(...)`

**Error Response Pattern:**
- For review tool (`propose_and_review_logic`), errors returned as JSON objects with structure:
  ```python
  error_response = {
      "error": True,
      "error_type": "validation_error",  # or "file_not_found", etc.
      "message": "Human-readable error message",
      "file_content": "...",  # Included if file < 5000 lines
      "hint": "Guidance for fixing the error"
  }
  raise ValueError(json.dumps(error_response, indent=2))
  ```

**Validation Pattern:**
- Central validation through `validate_path()` function that raises `ValueError` with security context
- All tools use `validate_path()` before file operations: `path_obj = validate_path(path)`

## Logging

**Framework:** Built-in `print()` function

**Patterns:**
- Status messages to stderr: `print(..., file=sys.stderr)`
- Tool output to stdout: `print(f"Successfully wrote to {path}")`
- Debug output when launching processes: `print(f"🚀 Launching background HTTP MCP server..."`
- Success/failure indicators: `✅`, `❌`, `⚠️` emojis

**Examples:**
- `print(f"Warning: Skipping invalid directory: {p}")` - in `initialize()`
- `print("✅ Approval detected. You can safely close the diff view.")` - in `propose_and_review_logic()`

## Comments

**When to Comment:**
- Security-critical sections: "--- Security Check: Resolve the final path...", "--- INTENT: CONTINUING AN EXISTING SESSION ---"
- Algorithm explanations: "# Rough approximation" (for token estimation)
- Section dividers for logical grouping: `# --- Global Configuration ---`, `# --- Tools ---`, `# --- Interactive Human-in-the-Loop Tools ---`

**Comment Style:**
- Single-line comments use `#` with space: `# This is a comment`
- Section headers use `# --- SECTION NAME ---` format
- Inline comments after code: `continue` has comment on same line in `list_directory_with_sizes()`

**JSDoc/TSDoc:**
- Not used (Python codebase)
- Docstrings used instead on functions (detailed docstrings on public tools)

## Function Design

**Size:** No rigid limits observed, but functions generally stay focused:
- Tool functions 10-30 lines (like `write_file()`, `move_file()`)
- Helper functions 20-50 lines (like `get_file_info()`)
- Complex handlers 100-200 lines (like `propose_and_review_logic()` at 270 lines - larger due to state management)

**Parameters:**
- Positional parameters for required values: `path: str, content: str`
- Optional parameters with defaults: `max_depth: int = 4`, `old_string: str = ""`, `session_path: Optional[str] = None`
- Use `Optional[Type]` from `typing` for nullable parameters
- Lists and complex types explicitly typed: `files: List[FileReadRequest]`, `edits: Optional[list] = None`

**Return Values:**
- String returns for tool outputs (following MCP pattern): `-> str`
- Dict returns for structured data (media files): `-> dict`
- Optional returns indicated: `-> Optional[str]`
- EditResult dataclass for complex results: `-> EditResult`

**Examples:**
```python
def validate_path(requested_path: str) -> Path:
    """Security barrier docstring..."""
    # Implementation

def read_files(files: List[FileReadRequest]) -> str:
    """Read the contents of multiple files..."""
    results = []
    # Implementation
    return "\n\n---\n\n".join(results)

def propose_and_review(
    path: str,
    new_string: str,
    old_string: str = "",
    expected_replacements: int = 1,
    session_path: Optional[str] = None,
    edits: Optional[list] = None
) -> str:
    """Detailed docstring..."""
    # Implementation
```

## Module Design

**Exports:**
- `server.py` exports functions decorated with `@mcp.tool()` - these become publicly available through FastMCP
- `edit_tool.py` exports `EditResult` dataclass and `RooStyleEditTool` class
- Global variables exported: `USER_ACCESSIBLE_DIRS`, `ALLOWED_DIRS`, `mcp` (FastMCP instance)

**Barrel Files:**
- `__init__.py` is empty (minimal export structure)
- No explicit barrel file pattern used

**Module-level State:**
- `server.py` maintains global state for directory access control:
  ```python
  USER_ACCESSIBLE_DIRS: List[Path] = []
  ALLOWED_DIRS: List[Path] = []
  mcp = FastMCP("filesystem", stateless_http=True)
  IS_VSCODE_CLI_AVAILABLE = False
  ```
- State initialized via `initialize(directories: List[str])` function
- This state is read by tools and validation functions

## Type Hints

**Coverage:** Consistent throughout codebase
- Function parameters all type-hinted: `path: str`, `files: List[FileReadRequest]`, `exclude_dirs: Optional[List[str]]`
- Return types always specified: `-> str`, `-> dict`, `-> Path`, `-> Optional[str]`
- Variable annotations in dataclasses and Pydantic models: `path: str`, `success: bool`, `diff: Optional[str]`

**Type Patterns:**
- Use `Optional[Type]` for nullable: `Optional[str]`, `Optional[int]`, `Optional[List[str]]`
- Use `List[Type]` for sequences: `List[Path]`, `List[str]`, `List[FileReadRequest]`
- Use `Dict[str, object]` for generic dicts: `Dict[str, object]`
- Use `Literal["value1", "value2"]` for enums: `Literal["APPROVE", "REVIEW"]`

---

*Convention analysis: 2026-01-26*
