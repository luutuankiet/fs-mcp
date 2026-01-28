import json
from pydantic import BaseModel
from typing import Optional

class FileReadRequest(BaseModel):
    path: str
    head: Optional[int] = None
    tail: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


import os
import base64
import mimetypes
import fnmatch
from pathlib import Path
from typing import List, Optional, Literal, Dict
from datetime import datetime
from fastmcp import FastMCP
import tempfile
import time
import shutil
import subprocess

from dataclasses import dataclass
from .edit_tool import EditResult, RooStyleEditTool, propose_and_review_logic
from .utils import check_ripgrep, check_jq, check_yq


# --- Global Configuration ---
USER_ACCESSIBLE_DIRS: List[Path] = []
ALLOWED_DIRS: List[Path] = []
mcp = FastMCP("filesystem", stateless_http=True)
IS_VSCODE_CLI_AVAILABLE = False
IS_RIPGREP_AVAILABLE = False
IS_JQ_AVAILABLE = False
IS_YQ_AVAILABLE = False


def initialize(directories: List[str]):
    """Initialize the allowed directories and check for VS Code CLI."""
    global ALLOWED_DIRS, USER_ACCESSIBLE_DIRS, IS_VSCODE_CLI_AVAILABLE, IS_RIPGREP_AVAILABLE, IS_JQ_AVAILABLE, IS_YQ_AVAILABLE
    ALLOWED_DIRS.clear()
    USER_ACCESSIBLE_DIRS.clear()
    
    IS_VSCODE_CLI_AVAILABLE = shutil.which('code') is not None
    IS_RIPGREP_AVAILABLE, ripgrep_message = check_ripgrep()
    if not IS_RIPGREP_AVAILABLE:
        print(ripgrep_message)

    IS_JQ_AVAILABLE, jq_message = check_jq()
    if not IS_JQ_AVAILABLE:
        print(jq_message)
    
    IS_YQ_AVAILABLE, yq_message = check_yq()
    if not IS_YQ_AVAILABLE:
        print(yq_message)

    raw_dirs = directories or [str(Path.cwd())]
    
    # Process user-specified directories
    for d in raw_dirs:
        try:
            p = Path(d).expanduser().resolve()
            if not p.exists() or not p.is_dir():
                print(f"Warning: Skipping invalid directory: {p}")
                continue
            USER_ACCESSIBLE_DIRS.append(p)
        except Exception as e:
            print(f"Warning: Could not resolve {d}: {e}")

    # The full list of allowed directories includes the user-accessible ones
    # and the system's temporary directory for internal review sessions.
    ALLOWED_DIRS.extend(USER_ACCESSIBLE_DIRS)
    ALLOWED_DIRS.append(Path(tempfile.gettempdir()).resolve())

    if not USER_ACCESSIBLE_DIRS:
        print("Warning: No valid user directories. Defaulting to CWD.")
        cwd = Path.cwd()
        USER_ACCESSIBLE_DIRS.append(cwd)
        if cwd not in ALLOWED_DIRS:
            ALLOWED_DIRS.append(cwd)
            
    return USER_ACCESSIBLE_DIRS

def validate_path(requested_path: str) -> Path:
    """
    Security barrier: Ensures path is within ALLOWED_DIRS.
    Handles both absolute and relative paths. Relative paths are resolved 
    against the first directory in ALLOWED_DIRS.
    """
    
    # an 'empty' path should always resolve to the primary allowed directory
    if not requested_path or requested_path == ".":
        return ALLOWED_DIRS[0]

    
    p = Path(requested_path).expanduser()
    
    # If the path is relative, resolve it against the primary allowed directory.
    if not p.is_absolute():
        # Ensure the base directory for relative paths is always the first one.
        base_dir = ALLOWED_DIRS[0]
        p = base_dir / p

    # --- Security Check: Resolve the final path and verify it's within bounds ---
    try:
        # .resolve() is crucial for security as it canonicalizes the path,
        # removing any ".." components and resolving symlinks.
        path_obj = p.resolve()
    except Exception:
        # Fallback for paths that might not exist yet but are being created.
        path_obj = p.absolute()

    is_allowed = any(
        str(path_obj).startswith(str(allowed)) 
        for allowed in ALLOWED_DIRS
    )

    # If the path is in the temp directory, apply extra security checks.
    temp_dir = Path(tempfile.gettempdir()).resolve()
    if is_allowed and str(path_obj).startswith(str(temp_dir)):
        # Allow access to the temp directory itself, but apply stricter checks for its contents.
        if path_obj != temp_dir:
            path_str = str(path_obj)
            is_review_dir = "mcp_review_" in path_str
            is_pytest_dir = "pytest-" in path_str

            if not (is_review_dir or is_pytest_dir):
                is_allowed = False
            # For review directories, apply stricter checks.
            elif is_review_dir and not (path_obj.name.startswith("current_") or path_obj.name.startswith("future_")):
                is_allowed = False
            
    if not is_allowed:
        raise ValueError(f"Access denied: {requested_path} is outside allowed directories: {ALLOWED_DIRS}")
        
    return path_obj

def format_size(size_bytes: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

# --- Tools ---

@mcp.tool()
def list_allowed_directories() -> str:
    """List the directories this server is allowed to access."""
    return "\n".join(str(d) for d in USER_ACCESSIBLE_DIRS)

@mcp.tool()
def read_files(files: List[FileReadRequest], large_file_passthrough: bool = False) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    Prefer relative paths.

    **Workflow Synergy with `grep_content`:**
    This tool is the second step in the efficient "grep -> read" workflow. After using `grep_content`
    to find relevant files and line numbers, use this tool to perform a targeted read of only
    those specific sections. This is highly efficient for exploring large codebases.

    **Example `grep -> read` workflow:**
    ```
    # Step 1: Find where 'FastMCP' is defined.
    grep_content(pattern="class FastMCP")

    # Output might be: File: src/fs_mcp/server.py, Line: 20

    # Step 2: Read the relevant section of that file using start_line and end_line.
    read_files([{"path": "src/fs_mcp/server.py", "start_line": 15, "end_line": 25}])
    ```

    **LARGE FILE HANDLING:**
    If you encounter errors like "response too large", "token limit exceeded", or "context overflow":
    1. FIRST: Call `get_file_info(path)` to understand file dimensions (line count, token estimate, structure)
    2. THEN: Use the `head` or `tail` parameters to read in manageable chunks
    3. STRATEGY: Start with a small sample (e.g., head=50), then read iteratively based on the 
       recommended chunk size from `get_file_info`
    
    **Example - Reading a large JSON file:**
    ```
    # Step 1: Get file info
    get_file_info("manifest_slim.json")
    # Returns: "... Total Lines: 15000, Estimated Tokens: 300000, Recommended chunk: 500 lines ..."
    
    # Step 2: Read first chunk
    read_files([{"path": "manifest_slim.json", "head": 500}])
    
    # Step 3: Continue reading in chunks (lines 500-1000, 1000-1500, etc.)
    # Note: To skip to a specific section, calculate offset based on line numbers
    ```
    Args:
        files: A list of file read requests.
        large_file_passthrough: If False (default), blocks reading JSON/YAML files >100k tokens and suggests using query_json/query_yaml instead. Set to True to read anyway.
    """
    results = []
    for file_request_data in files:
        if isinstance(file_request_data, dict):
            file_request = FileReadRequest(**file_request_data)
        else:
            file_request = file_request_data
            
        try:
            path_obj = validate_path(file_request.path)

            # Large file check for JSON/YAML
            if not large_file_passthrough and path_obj.exists() and not path_obj.is_dir():
                file_ext = path_obj.suffix.lower()
                if file_ext in ['.json', '.yaml', '.yml']:
                    file_size = os.path.getsize(path_obj)
                    tokens = file_size / 4  # Approximate token count
                    if tokens > 5000:
                        query_tool = "n/a ignore this line"
                        file_type = "n/a ignore this line"
                        if file_ext in ['.json','.yaml', '.yml']:
                            file_type = "JSON" if file_ext == '.json' else "YAML"
                            query_tool = "query_json" if file_type == "JSON" else "query_yaml"
                        error_message = (
                            f"Error: {file_request.path} is a large {file_type} file (~{tokens:,.0f} tokens).\n\n"
                            f"Reading the entire file may overflow your context window. Consider using these if the file is json / yaml:\n"
                            f"- {query_tool}(\"{file_request.path}\", \"keys\") to explore structure\n"
                            f"- {query_tool}(\"{file_request.path}\", \".items[0:10]\") to preview data\n"
                            f"- {query_tool}(\"{file_request.path}\", \".items[] | select(.field == 'value')\") to filter\n\n"
                            f"- Or use grep_content to explore the file structure"
                            f"- As a last resort, set large_file_passthrough=True to read anyway."
                        )
                        results.append(f"File: {file_request.path}\n{error_message}")
                        continue

            if (file_request.head is not None or file_request.tail is not None) and \
               (file_request.start_line is not None or file_request.end_line is not None):
                raise ValueError("Cannot mix start_line/end_line with head/tail.")

            if path_obj.is_dir():
                content = "Error: Is a directory"
            else:
                try:
                    with open(path_obj, 'r', encoding='utf-8') as f:
                        if file_request.start_line is not None or file_request.end_line is not None:
                            lines = f.readlines()
                            start = (file_request.start_line or 1) - 1
                            end = file_request.end_line or len(lines)
                            content = "".join(lines[start:end])
                        elif file_request.head is not None:
                            content = "".join([next(f) for _ in range(file_request.head)])
                        elif file_request.tail is not None:
                            content = "".join(f.readlines()[-file_request.tail:])
                        else:
                            content = f.read()
                except UnicodeDecodeError:
                    content = "Error: Binary file. Use read_media_file."
            
            results.append(f"File: {file_request.path}\n{content}")
        except Exception as e:
            results.append(f"File: {file_request.path}\nError: {e}")
            
    return "\n\n---\n\n".join(results)

@mcp.tool()
def read_media_file(path: str) -> dict:
    """Read an image or audio file as base64. Prefer relative paths."""
    path_obj = validate_path(path)
    mime_type, _ = mimetypes.guess_type(path_obj)
    if not mime_type: mime_type = "application/octet-stream"
        
    try:
        with open(path_obj, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        
        type_category = "image" if mime_type.startswith("image/") else "audio" if mime_type.startswith("audio/") else "blob"
        return {"type": type_category, "data": data, "mimeType": mime_type}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create a new file or completely overwrite an existing file. Prefer relative paths."""
    path_obj = validate_path(path)
    with open(path_obj, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully wrote to {path}"

@mcp.tool()
def create_directory(path: str) -> str:
    """Create a new directory or ensure it exists. Prefer relative paths."""
    path_obj = validate_path(path)
    os.makedirs(path_obj, exist_ok=True)
    return f"Successfully created directory {path}"

@mcp.tool()
def list_directory(path: str) -> str:
    """Get a detailed listing of all files and directories. Prefer relative paths."""
    path_obj = validate_path(path)
    if not path_obj.is_dir(): return f"Error: {path} is not a directory"
    
    entries = []
    for entry in path_obj.iterdir():
        prefix = "[DIR]" if entry.is_dir() else "[FILE]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(sorted(entries))

@mcp.tool()
def list_directory_with_sizes(path: str) -> str:
    """Get listing with file sizes. Prefer relative paths."""
    path_obj = validate_path(path)
    if not path_obj.is_dir(): return f"Error: Not a directory"
    
    output = []
    for entry in path_obj.iterdir():
        try:
            s = entry.stat().st_size if not entry.is_dir() else 0
            prefix = "[DIR]" if entry.is_dir() else "[FILE]"
            size_str = "" if entry.is_dir() else format_size(s)
            output.append(f"{prefix} {entry.name.ljust(30)} {size_str}")
        except: continue
    return "\n".join(sorted(output))

@mcp.tool()
def move_file(source: str, destination: str) -> str:
    """Move or rename files. Prefer relative paths."""
    src = validate_path(source)
    dst = validate_path(destination)
    if dst.exists(): raise ValueError(f"Destination {destination} already exists")
    src.rename(dst)
    return f"Moved {source} to {destination}"

@mcp.tool()
def search_files(path: str, pattern: str) -> str:
    """Recursively search for files matching a glob pattern. Prefer relative paths."""
    root = validate_path(path)
    try:
        results = [str(p.relative_to(root)) for p in root.rglob(pattern) if p.is_file()]
        return "\n".join(results) or "No matches found."
    except Exception as e:
        return f"Error during search: {e}"


@mcp.tool()
def get_file_info(path: str) -> str:
    """
    Retrieve detailed metadata about a file, including size, structure analysis, and 
    recommended chunking strategy for large files. This tool is CRITICAL before reading 
    large files to avoid context overflow errors.
    
    Returns:
    - Basic metadata (path, type, size, modified time)
    - Line count (for text files)
    - Estimated token count
    - File type-specific analysis (JSON structure, CSV columns, etc.)
    - Recommended chunk size for iterative reading with read_files
    
    Prefer relative paths.
    """
    p = validate_path(path)
    
    if not p.exists():
        return f"Error: File not found at {path}"
    
    s = p.stat()
    is_dir = p.is_dir()
    
    # Basic info
    info_lines = [
        f"Path: {p}",
        f"Type: {'Directory' if is_dir else 'File'}",
        f"Size: {format_size(s.st_size)} ({s.st_size:,} bytes)",
        f"Modified: {datetime.fromtimestamp(s.st_mtime)}"
    ]
    
    if is_dir:
        return "\n".join(info_lines)
    
    # For files, add detailed analysis
    try:
        # Detect file type
        suffix = p.suffix.lower()
        mime_type, _ = mimetypes.guess_type(p)
        
        # Try to read as text
        try:
            content = p.read_text(encoding='utf-8')
            char_count = len(content)
            line_count = content.count('\n') + 1
            estimated_tokens = char_count // 4  # Rough approximation
            
            info_lines.append(f"\n--- Text File Analysis ---")
            info_lines.append(f"Total Lines: {line_count:,}")
            info_lines.append(f"Total Characters: {char_count:,}")
            info_lines.append(f"Estimated Tokens: {estimated_tokens:,} (rough estimate: chars ÷ 4)")
            
            # Adaptive chunk size recommendation
            chunk_recommendation = _calculate_adaptive_chunk_size(estimated_tokens, line_count, p)
            info_lines.append(f"\n--- Chunking Strategy ---")
            info_lines.append(chunk_recommendation)
            
            # File type-specific analysis
            if suffix == '.json' and char_count < 10_000_000:  # Don't parse huge files
                type_specific = _analyze_json_structure(content)
                if type_specific:
                    info_lines.append(f"\n--- JSON Structure Preview ---")
                    info_lines.append(type_specific)
            
            elif suffix == '.csv' and line_count > 1:
                type_specific = _analyze_csv_structure(content)
                if type_specific:
                    info_lines.append(f"\n--- CSV Structure ---")
                    info_lines.append(type_specific)
            
            elif suffix in ['.txt', '.md', '.log']:
                lines = content.split('\n')
                preview_lines = []
                if len(lines) > 0:
                    preview_lines.append(f"First line: {lines[0][:100]}")
                if len(lines) > 1:
                    preview_lines.append(f"Last line: {lines[-1][:100]}")
                if preview_lines:
                    info_lines.append(f"\n--- Content Preview ---")
                    info_lines.extend(preview_lines)
                    
        except UnicodeDecodeError:
            info_lines.append(f"\n--- Binary File ---")
            info_lines.append(f"MIME Type: {mime_type or 'application/octet-stream'}")
            info_lines.append(f"Note: Use read_media_file() for binary content")
    
    except Exception as e:
        info_lines.append(f"\nWarning: Could not analyze file content: {e}")
    
    return "\n".join(info_lines)


def _calculate_adaptive_chunk_size(estimated_tokens: int, line_count: int, p: Path) -> str:
    """
    Calculate recommended chunk size based on file size and token limits.
    Strategy: Start small for sampling, then scale up adaptively.
    """
    # Target: Keep each chunk under 30k tokens to leave room for context
    TARGET_TOKENS_PER_CHUNK = 5000
    SAFE_FIRST_SAMPLE = 50  # lines
    
    if estimated_tokens <= TARGET_TOKENS_PER_CHUNK:
        return "✅ File is small enough to read in one call (no chunking needed)"
    
    # Calculate tokens per line average
    tokens_per_line = estimated_tokens / line_count if line_count > 0 else 1
    
    # Calculate safe chunk size in lines
    recommended_lines = int(TARGET_TOKENS_PER_CHUNK / tokens_per_line) if tokens_per_line > 0 else 1000
    
    # Ensure minimum chunk size
    recommended_lines = max(100, recommended_lines)
    
    num_chunks = (line_count + recommended_lines - 1) // recommended_lines  # Ceiling division
    
    strategy = [
        f"⚠️  LARGE FILE WARNING: This file requires chunked reading",
        f"",
        f"Recommended Strategy:",
        f"  1. First sample: read_files([{{'path': '{p.name}', 'head': {SAFE_FIRST_SAMPLE}}}])",
        f"     (Start with {SAFE_FIRST_SAMPLE} lines to understand structure)",
        f"",
        f"  2. Then read in chunks of ~{recommended_lines:,} lines",
        f"     (Estimated {num_chunks} chunks total)",
        f"",
        f"  3. Example progression:",
        f"     - Chunk 1: head={recommended_lines}",
        f"     - Chunk 2: Use line numbers {recommended_lines}-{recommended_lines*2}",
        f"       (Note: read_files doesn't support offset+limit yet, so you may need",
        f"        to read overlapping chunks or work with the maintainer to add this)",
        f"",
        f"Estimated tokens per chunk: ~{int(recommended_lines * tokens_per_line):,}"
    ]
    
    return "\n".join(strategy)


def _analyze_json_structure(content: str) -> Optional[str]:
    """Analyze JSON structure and return a preview of keys and array lengths."""
    try:
        data = json.loads(content)
        lines = []
        
        if isinstance(data, dict):
            lines.append(f"Type: JSON Object")
            lines.append(f"Top-level keys ({len(data)}): {', '.join(list(data.keys())[:10])}")
            
            # Show array lengths for top-level arrays
            for key, value in list(data.items())[:5]:
                if isinstance(value, list):
                    lines.append(f"  - '{key}': Array with {len(value)} items")
                elif isinstance(value, dict):
                    lines.append(f"  - '{key}': Object with {len(value)} keys")
                else:
                    lines.append(f"  - '{key}': {type(value).__name__}")
        
        elif isinstance(data, list):
            lines.append(f"Type: JSON Array")
            lines.append(f"Total items: {len(data)}")
            if len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, dict):
                    lines.append(f"First item keys: {', '.join(list(first_item.keys())[:10])}")
        
        return "\n".join(lines)
    except json.JSONDecodeError:
        return "⚠️  Invalid JSON (parse error)"
    except Exception as e:
        return f"⚠️  Could not analyze JSON: {e}"


def _analyze_csv_structure(content: str) -> Optional[str]:
    """Analyze CSV structure and return column information."""
    try:
        lines = content.split('\n')
        if len(lines) < 1:
            return None
        
        # Assume first line is header
        header = lines[0]
        columns = header.split(',')
        
        result_lines = [
            f"Detected columns ({len(columns)}): {', '.join(col.strip() for col in columns[:10])}",
            f"Estimated rows: {len(lines) - 1:,}"
        ]
        
        if len(columns) > 10:
            result_lines.append(f"  ... and {len(columns) - 10} more columns")
        
        return "\n".join(result_lines)
    except Exception:
        return None

@mcp.tool()
def directory_tree(path: str, max_depth: int = 4, exclude_dirs: Optional[List[str]] = None) -> str:
    """Get recursive JSON tree with depth limit and default excludes."""
    root = validate_path(path)
    
    # Use provided excludes or our new smart defaults
    default_excludes = ['.git', '.venv', '__pycache__', 'node_modules', '.pytest_cache']
    excluded = exclude_dirs if exclude_dirs is not None else default_excludes
    max_depth = 3 if isinstance(max_depth,str) else max_depth

    def build(current: Path, depth: int) -> Optional[Dict]:
        if depth > max_depth or current.name in excluded:
            return None
        
        node: Dict[str, object] = {"name": current.name, "type": "directory" if current.is_dir() else "file"}
        
        if current.is_dir():
            children: List[Dict] = []
            try:
                for entry in sorted(current.iterdir(), key=lambda x: x.name):
                    child = build(entry, depth + 1)
                    if child:
                        children.append(child)
                if children:
                    node["children"] = children
            except PermissionError:
                node["error"] = "Permission Denied"
        return node
        
    tree = build(root, 0)
    return json.dumps(tree, indent=2)


# --- Interactive Human-in-the-Loop Tools ---
APPROVAL_KEYWORD = "##APPROVE##"




@mcp.tool()
async def propose_and_review(path: str, new_string: str, old_string: str = "", expected_replacements: int = 1, session_path: Optional[str] = None, edits: Optional[list] = None) -> str:
    """
    Starts or continues an interactive review session using a VS Code diff view. This smart tool adapts its behavior based on the arguments provided.

    **BEST PRACTICE - MINIMAL CONTEXT:**
    When using Intent 1 (Patch), do NOT provide the full file content in `old_string`.
    Instead, provide only the specific lines you want to change, plus just enough
    surrounding lines (1-2) to ensure uniqueness. This prevents context errors and
    improves performance on large files.

    **BEST PRACTICE - BATCH MULTIPLE CHANGES:**
    When you need to make multiple edits to the same file, use the `edits` parameter
    to batch them into a single review call. Break down your changes into manageable
    old_string/new_string pairs — each pair should be minimal (only the lines that change
    plus 1-2 lines of context for uniqueness). This gives the user one combined diff to
    review instead of multiple sequential approvals.

    Example `edits` value (list of dicts):
    [
      {"old_string": "def foo():\n    return 1", "new_string": "def foo():\n    return 2"},
      {"old_string": "x = 10", "new_string": "x = 20"}
    ]

    Intents:

    1.  **Start New Review (Patch):** Provide `path`, `old_string`, `new_string`. Validates the patch against the original file.
    2.  **Start New Review (Multi-Patch):** Provide `path` and `edits` (list of {old_string, new_string} dicts). All patches are applied sequentially and presented as one combined diff.
    3.  **Start New Review (Full Rewrite):** Provide `path`, `new_string`, and leave `old_string` empty.
    4.  **Continue Review (Contextual Patch):** Provide `path`, `session_path`, `old_string`, and `new_string`.
        *   **CRITICAL: STATE RECONSTRUCTION PROTOCOL**
            1.  **Analyze the Diff:** If `user_action` was 'REVIEW', the user has manually edited the file. The `user_feedback_diff` is the ABSOLUTE TRUTH.
            2.  **Reconstruct Current State:** You must mentally apply the `user_feedback_diff` to your previous `new_string` to calculate the current file content.
            3.  **Match Exactly:** Your `old_string` MUST match this reconstructed content character-for-character, *including* any comments or temporary notes the user typed (e.g., `# hey remove this`).
            4.  **Execute Instructions:** If the user wrote instructions in the code, your `new_string` must perform those edits (e.g., removing the comment, fixing the line). Do not ignore them to add new features. **always remove the identified user review comment from the new_string.**
    5.  **Continue Review (Full Rewrite / Recovery):** Provide `path`, `session_path`, `new_string`, and the full content of the file as `old_string`.

    Note: `path` is always required to identify the file being edited, even when continuing a session.

    It blocks and waits for the user to save the file, then returns their action ('APPROVE' or 'REVIEW').
    """
    return await propose_and_review_logic(
        validate_path,
        IS_VSCODE_CLI_AVAILABLE,
        path,
        new_string,
        old_string,
        expected_replacements,
        session_path,
        edits
    )

@mcp.tool()
def commit_review(session_path: str, original_path: str) -> str:
    """Finalizes an interactive review session by committing the approved changes."""
    session_dir = Path(session_path)
    original_file = validate_path(original_path)
    if not session_dir.is_dir():
        raise ValueError(f"Invalid session path: {session_path}")
    future_file = session_dir / f"future_{original_file.name}"
    if not future_file.exists():
        raise FileNotFoundError(f"Approved file not found in session: {future_file}")
    approved_content = future_file.read_text(encoding='utf-8')
    final_content = approved_content.rstrip('\n')
    try:
        original_file.write_text(final_content, encoding='utf-8')
    except Exception as e:
        raise IOError(f"Failed to write final content to {original_path}: {e}")
    try:
        shutil.rmtree(session_dir)
    except Exception as e:
        return f"Successfully committed changes to {original_path}, but failed to clean up session dir {session_path}: {e}"
    return f"Successfully committed changes to '{original_path}' and cleaned up the review session."
@mcp.tool()
def grounding_search(query: str) -> str:
    """[NEW] A custom search tool. Accepts a natural language query and returns a grounded response."""
    # This is a placeholder for a future RAG or other search implementation.
    print(f"Received grounding search query: {query}")
    return "DEVELOPER PLEASE UPDATE THIS WITH ACTUAL CONTENT"


@mcp.tool()
def grep_content(pattern: str, search_path: str = '.', case_insensitive: bool = False, context_lines: int = 2) -> str:
    """
    Search for a pattern in file contents using ripgrep.

    **Workflow:**
    Mandatory File Interaction Protocol: The "Grep -> Hint -> Read" Workflow

    1.  **`grep_content`**: Use this tool with a specific pattern to find *which files* are relevant and *where* in those files the relevant code is (line numbers). Its primary purpose is to **locate file paths and line numbers**, not to read full file contents.
    2.  Hint: Critically inspect the grep output for the (section end hint: ...) metadata. This hint defines the full boundary of the relevant content.
    3.  **`read_files`**: Use the file path and line numbers from the output of this tool to perform a targeted read of only the relevant file sections.
    4.  NEVER assume a single grep match represents the full context. The purpose of this protocol is to replace assumption with evidence.


    **Example:**
    ```
    # Step 1: Find where 'FastMCP' is defined.
    grep_content(pattern="class FastMCP")

    # Output might be: File: src/fs_mcp/server.py, Line: 20

    # Step 2: Read the relevant section of that file.
    read_files([{"path": "src/fs_mcp/server.py", "start_line": 15, "end_line": 25}])
    ```
    """
    if not IS_RIPGREP_AVAILABLE:
        _, msg = check_ripgrep()
        return f"Error: ripgrep is not available. {msg}"

    validated_path = validate_path(search_path)
    
    command = [
        'rg',
        '--json',
        '--max-count=100',
        f'--context={context_lines}',
    ]
    if case_insensitive:
        command.append('--ignore-case')
    
    command.extend([pattern, str(validated_path)])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False  # Don't raise exception for non-zero exit codes
        )
    except FileNotFoundError:
        return "Error: 'rg' command not found. Please ensure ripgrep is installed and in your PATH."
    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 10 seconds. Please try a more specific pattern."

    if result.returncode != 0 and result.returncode != 1:
        # ripgrep exits with 1 for no matches, which is not an error for us.
        # Other non-zero exit codes indicate a real error.
        return f"Error executing ripgrep: {result.stderr}"

    output_lines = []
    matches_found = False
    for line in result.stdout.strip().split('\n'):
        try:
            message = json.loads(line)
            if message['type'] == 'match':
                matches_found = True
                data = message['data']
                path = data['path']['text']
                line_number = data['line_number']
                text = data['lines']['text']
                output_lines.append(f"File: {path}, Line: {line_number}\n---\n{text.strip()}\n---")
        except (json.JSONDecodeError, KeyError):
            # Ignore non-match lines or lines with unexpected structure
            continue

    if not matches_found:
        return "No matches found."

    return "\n\n".join(output_lines)




@mcp.tool()
def query_json(file_path: str, jq_expression: str, timeout: int = 30) -> str:
    """
    Query a JSON file using jq expressions. Use this to efficiently explore large JSON files
    without reading the entire content into memory.

    **Common Query Patterns:**
    - Get specific field: '.field_name'
    - Array iteration: '.items[]'
    - Filter array: '.items[] | select(.active == true)'
    - Select fields: '.items[] | {name, id}'
    - Array slice: '.items[0:100]' (first 100 items)
    - Count items: '.items | length'

    **Multiline Queries (with comments):**
    query_json("data.json", '''
    # Filter active items
    .items[] | select(.active == true)
    ''')

    **Workflow Example:**
    1. Get structure overview: query_json("data.json", "keys")
    2. Count array items: query_json("data.json", ".items | length")
    3. Explore first few: query_json("data.json", ".items[0:5]")
    4. Filter specific: query_json("data.json", ".items[] | select(.status == 'active')")

    **Result Limit:** Returns first 100 results. For more, use slicing: .items[100:200]

    Args:
        file_path: Path to JSON file (relative or absolute)
        jq_expression: jq query expression (see https://jqlang.github.io/jq/manual/)
        timeout: Query timeout in seconds (default: 30)

    Returns:
        Compact JSON results (one per line), or error message
    """
    if not IS_JQ_AVAILABLE:
        _, msg = check_jq()
        return f"Error: jq is not available. {msg}"

    validated_path = validate_path(file_path)

    # Create temp file for query expression to avoid command-line escaping issues
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jq', delete=False)
        temp_file.write(jq_expression)
        temp_file.close()

        command = ['jq', '-c', '-f', temp_file.name, str(validated_path)]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
        except FileNotFoundError:
            return "Error: 'jq' command not found. Please ensure jq is installed and in your PATH."
        except subprocess.TimeoutExpired:
            return f"Error: Query timed out after {timeout} seconds. Please simplify your query."

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            return f"jq syntax error: {error_msg}. Check your query for common issues (unclosed brackets, missing semicolons, undefined functions)."

        output = result.stdout.strip()
        if not output or output == 'null':
            return "No results found."

        lines = output.split('\n')

        if len(lines) > 100:
            truncated_output = "\n".join(lines[:100])
            return f"{truncated_output}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use jq slicing: .items[100:200]"

        return output
    finally:
        # Clean up temp file
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass



@mcp.tool()
def query_yaml(file_path: str, yq_expression: str, timeout: int = 30) -> str:
    """
    Query a YAML file using yq expressions (mikefarah/yq with jq-like syntax). Use this to efficiently explore large YAML files without reading the entire content into memory.

    **Common Query Patterns:**
    - Get specific field: '.field_name'
    - Array iteration: '.items[]'
    - Filter array: '.items[] | select(.active == true)'
    - Select fields: '.items[] | {name, id}'
    - Array slice: '.items[0:100]' (first 100 items)
    - Count items: '.items | length'

    **Multiline Queries (with comments):**
    query_yaml("config.yaml", '''
    # Filter active services
    .services[] | select(.active == true)
    ''')

    **Workflow Example:**
    1. Get structure overview: query_yaml("config.yaml", "keys")
    2. Count array items: query_yaml("config.yaml", ".services | length")
    3. Explore first few: query_yaml("config.yaml", ".services[0:5]")
    4. Filter specific: query_yaml("config.yaml", ".services[] | select(.enabled == true)")

    **Result Limit:** Returns first 100 results. For more, use slicing: .items[100:200]

    Args:
        file_path: Path to YAML file (relative or absolute)
        yq_expression: yq query expression (jq-like syntax, see mikefarah.gitbook.io/yq)
        timeout: Query timeout in seconds (default: 30)

    Returns:
        Compact JSON results (one per line), or error message
    """
    if not IS_YQ_AVAILABLE:
        _, msg = check_yq()
        return f"Error: yq is not available. {msg}"

    validated_path = validate_path(file_path)

    # Create temp file for query expression to avoid command-line escaping issues
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yq', delete=False)
        temp_file.write(yq_expression)
        temp_file.close()

        command = ['yq', '-o', 'json', '-I', '0', '--from-file', temp_file.name, str(validated_path)]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
        except FileNotFoundError:
            return "Error: 'yq' command not found. Please ensure yq is installed and in your PATH."
        except subprocess.TimeoutExpired:
            return f"Error: Query timed out after {timeout} seconds. Please simplify your query."

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            return f"yq syntax error: {error_msg}. Check your query for common issues (unclosed brackets, missing semicolons, undefined functions)."

        output = result.stdout.strip()
        if not output or output == 'null':
            return "No results found."

        lines = output.split('\n')

        if len(lines) > 100:
            truncated_output = "\n".join(lines[:100])
            return f"{truncated_output}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use yq slicing: .items[100:200]"

        return output
    finally:
        # Clean up temp file
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


@mcp.tool()
def append_text(path: str, content: str) -> str:
    """
    Append text to the end of a file. If the file does not exist, it will be created.
    Use this as a fallback if edit_file fails to find a match.
    Prefer relative paths.
    """
    p = validate_path(path)
    
    # Ensure there is a newline at the start of the append if the file doesn't have one
    # to avoid clashing with the existing last line.
    with open(p, 'a', encoding='utf-8') as f:
        # Check if we need a leading newline
        if p.exists() and p.stat().st_size > 0:
            f.write("\n")
        f.write(content)
        
    return f"Successfully appended content to '{path}'."