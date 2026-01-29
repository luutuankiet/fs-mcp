import json
import re
import itertools
import os
import base64
import mimetypes
import fnmatch
from pathlib import Path
from typing import List, Optional, Literal, Dict, Annotated
from datetime import datetime
from dataclasses import dataclass
from pydantic import BaseModel, Field
from fastmcp import FastMCP
import tempfile
import time
import shutil
import subprocess

from .edit_tool import EditResult, RooStyleEditTool, propose_and_review_logic, MATCH_TEXT_MAX_LENGTH
from .utils import check_ripgrep, check_jq, check_yq

# --- Token threshold for large file warnings (conservative to enforce grep->read workflow) ---
LARGE_FILE_TOKEN_THRESHOLD = 2000

# --- Dynamic Field Descriptions (using imported constants) ---
MATCH_TEXT_DESCRIPTION = f"""The EXACT text to find and replace (LITERAL, not regex).

WORKFLOW: Read file → Copy exact text → Paste here.

Whitespace matters. Multi-line: use \\n between lines.
Example: "def foo():\\n    return 1"

SPECIAL: "" = new file, "OVERWRITE_FILE" = replace all.

If no match, error tells you why - just re-read and retry.
Max {MATCH_TEXT_MAX_LENGTH} chars."""

EDITS_DESCRIPTION = f"""Batch multiple DIFFERENT edits in one call. More efficient than multiple tool calls.

EXAMPLE:
edits=[
  {{"match_text": "old_name", "new_string": "new_name"}},
  {{"match_text": "x = 1", "new_string": "x = 2"}}
]

RULES:
- Each match_text must appear exactly ONCE in file
- Edits apply in order (first edit runs, then second on the result, etc.)
- Do NOT use for overlapping regions - split into separate calls instead
- Max {MATCH_TEXT_MAX_LENGTH} chars per match_text

WHEN TO USE: Renaming something + updating its references in same file."""

EDIT_PAIR_MATCH_TEXT_DESCRIPTION = f"""Exact text to find. Must appear exactly once. Copy character-for-character including whitespace. Max {MATCH_TEXT_MAX_LENGTH} chars."""

LARGE_FILE_PASSTHROUGH_DESCRIPTION = f"Set True to read large JSON/YAML files (>{LARGE_FILE_TOKEN_THRESHOLD} tokens). Default False suggests using query_json/query_yaml instead."

BYPASS_MATCH_TEXT_LIMIT_DESCRIPTION = f"Set True to allow match_text over {MATCH_TEXT_MAX_LENGTH} chars. Try using 'edits' to split into smaller chunks first."

# --- Pydantic Models for Tool Arguments ---

class FileReadRequest(BaseModel):
    """A request to read a file with various reading modes. Modes are mutually exclusive."""
    path: str = Field(description="The path to the file to read. Prefer relative paths.")
    head: Optional[int] = Field(default=None, description="Number of lines to read from the beginning of the file. Cannot be mixed with start_line/end_line.")
    tail: Optional[int] = Field(default=None, description="Number of lines to read from the end of the file. Cannot be mixed with start_line/end_line.")
    start_line: Optional[int] = Field(default=None, description="The 1-based line number to start reading from. Use with end_line for a range, or with read_to_next_pattern for section-aware reading.")
    end_line: Optional[int] = Field(default=None, description="The 1-based line number to stop reading at (inclusive). Cannot be used with read_to_next_pattern.")
    read_to_next_pattern: Optional[str] = Field(
        default=None,
        description="A regex pattern for section-aware reading. Reads from start_line until a line matching this pattern is found (exclusive). Useful for reading entire functions/classes. REQUIRES start_line. Cannot be used with end_line."
    )


class EditPair(BaseModel):
    """A single edit operation for batch editing. Provide the exact text to find (match_text) and its replacement (new_string)."""
    match_text: str = Field(description=EDIT_PAIR_MATCH_TEXT_DESCRIPTION)
    new_string: str = Field(description="The replacement text that will replace match_text.")


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
def read_files(
    files: Annotated[
        List[FileReadRequest],
        Field(description="A list of file read requests. WORKFLOW: Use grep_content FIRST to find line numbers and section boundaries, then use read_files for targeted reading of only the relevant sections. This preserves context. Reading modes: full file (path only), head/tail (first/last N lines), line range (start_line/end_line), or section-aware (start_line + read_to_next_pattern for reading until next function/class).")
    ],
    large_file_passthrough: Annotated[
        bool,
        Field(default=False, description=LARGE_FILE_PASSTHROUGH_DESCRIPTION)
    ] = False
) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    Prefer relative paths.

    **Reading Modes:**
    1.  **Full File:** Provide just the `path`.
    2.  **Head/Tail:** Use `head` or `tail` to read the beginning or end of a file.
    3.  **Line Range:** Use `start_line` and `end_line` to read a specific slice.
    4.  **Section-Aware (New):** Use `start_line` and `read_to_next_pattern` to read from a starting point until a regex pattern is found. This is useful for reading entire functions or classes without knowing the exact end line.

    **Section-Aware Reading Example:**
    To read a Python function definition:
    ```
    read_files([{
        "path": "src/fs_mcp/server.py",
        "start_line": 90,
        "read_to_next_pattern": "^def "
    }])
    ```
    This reads from line 90 until the *next* line that starts with "def ", effectively capturing the whole function. The pattern search starts on the line *after* `start_line`. If the pattern is not found, it reads to the end of the file.

    **Parameter mutual exclusivity:**
    - `head`/`tail` cannot be mixed with `start_line`/`end_line`.
    - `end_line` cannot be used with `read_to_next_pattern`.

    **Workflow Synergy with `grep_content`:**
    This tool is the second step in the efficient "grep -> read" workflow. After using `grep_content`
    to find relevant files and line numbers, use this tool to perform a targeted read of only
    those specific sections.
    """
    results = []
    for file_request_data in files:
        if isinstance(file_request_data, dict):
            file_request = FileReadRequest(**file_request_data)
        else:
            file_request = file_request_data
            
        try:
            path_obj = validate_path(file_request.path)

            # --- Parameter Validation ---
            if file_request.end_line and file_request.read_to_next_pattern:
                error_message = (
                    "Error: Mutually exclusive parameters provided.\n\n"
                    f"You provided: end_line={file_request.end_line}, read_to_next_pattern='{file_request.read_to_next_pattern}'\n"
                    "Problem: `end_line` and `read_to_next_pattern` cannot be used together.\n"
                    "Fix: Choose one method for defining the read boundary."
                )
                results.append(f"File: {file_request.path}\n{error_message}")
                continue

            if file_request.read_to_next_pattern and not file_request.start_line:
                error_message = (
                    "Error: Missing required parameter.\n\n"
                    f"You provided: read_to_next_pattern='{file_request.read_to_next_pattern}' without `start_line`.\n"
                    "Problem: `read_to_next_pattern` requires a `start_line` to know where to begin scanning.\n"
                    "Fix: Provide a `start_line`."
                )
                results.append(f"File: {file_request.path}\n{error_message}")
                continue

            # Large file check for JSON/YAML - conservative threshold to enforce grep->read workflow
            if not large_file_passthrough and path_obj.exists() and not path_obj.is_dir():
                file_ext = path_obj.suffix.lower()
                if file_ext in ['.json', '.yaml', '.yml']:
                    file_size = os.path.getsize(path_obj)
                    tokens = file_size / 4  # Approximate token count (4 chars per token)
                    if tokens > LARGE_FILE_TOKEN_THRESHOLD:
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
                        if file_request.read_to_next_pattern:
                            start_line = file_request.start_line
                            if start_line is None:
                                # This case should ideally be caught by earlier validation, but for safety:
                                results.append(f"File: {file_request.path}\nError: start_line is required for read_to_next_pattern.")
                                continue
                            pattern = file_request.read_to_next_pattern
                            
                            lines_to_read = []
                            pattern_found = False
                            
                            # islice uses 0-based indexing, so subtract 1
                            line_iterator = itertools.islice(f, start_line - 1, None)
                            
                            try:
                                first_line = next(line_iterator)
                                lines_to_read.append(first_line)
                            except StopIteration:
                                # To get total lines, we need to read the file again unfortunately
                                with open(path_obj, 'r', encoding='utf-8') as count_f:
                                    total_lines = sum(1 for _ in count_f)

                                error_message = (
                                    f"Error: Invalid start_line.\n\n"
                                    f"You provided: start_line={start_line}\n"
                                    f"Problem: The file '{file_request.path}' only has {total_lines} lines.\n"
                                    f"Fix: Choose a start_line between 1 and {total_lines}.\n"
                                    f"Tip: Use grep_content to find valid line numbers first."
                                )
                                results.append(f"File: {file_request.path}\n{error_message}")
                                continue

                            # Scan subsequent lines for the pattern
                            for line in line_iterator:
                                if re.search(pattern, line):
                                    pattern_found = True
                                    break
                                lines_to_read.append(line)
                            
                            content = "".join(lines_to_read)
                            if not pattern_found:
                                note = f"Note: Pattern '{pattern}' not found after line {start_line}. Read to end of file."
                                content = f"{content.rstrip()}\n{note}\n"

                        elif file_request.start_line is not None or file_request.end_line is not None:
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
async def propose_and_review(
    path: Annotated[
        str,
        Field(description="Path to the file to edit. Relative paths (e.g., 'src/main.py') or absolute paths both work.")
    ],
    new_string: Annotated[
        str,
        Field(default="", description="The replacement text.")
    ] = "",
    match_text: Annotated[
        str,
        Field(default="", description=MATCH_TEXT_DESCRIPTION)
    ] = "",
    expected_replacements: Annotated[
        int,
        Field(default=1, description="How many times match_text should appear. Default 1 = must be unique (ERRORS if found 0 or 2+ times). Set to N to replace all N occurrences.")
    ] = 1,
    session_path: Annotated[
        Optional[str],
        Field(default=None, description="ONLY for continuing after 'REVIEW' response. When user modifies your proposal, pass session_path here and set match_text to the USER's edited text (from user_feedback_diff), then new_string to your next proposal. Or call commit_review to accept user's version as-is.")
    ] = None,
    edits: Annotated[
        Optional[List[EditPair]],
        Field(default=None, description=EDITS_DESCRIPTION)
    ] = None,
    bypass_match_text_limit: Annotated[
        bool,
        Field(default=False, description=BYPASS_MATCH_TEXT_LIMIT_DESCRIPTION)
    ] = False
) -> str:
    """
    Edit a file with human review. Returns APPROVE or REVIEW response.

    ════════════════════════════════════════════════════════════════════
    QUICK REFERENCE (copy these patterns)
    ════════════════════════════════════════════════════════════════════

    EDIT FILE:    propose_and_review(path="file.py", match_text="old", new_string="new")
    NEW FILE:     propose_and_review(path="new.py", match_text="", new_string="content")
    BATCH EDIT:   propose_and_review(path="file.py", edits=[{"match_text":"a","new_string":"b"}])
    SAVE CHANGES: commit_review(session_path="/tmp/xyz", original_path="file.py")

    ════════════════════════════════════════════════════════════════════
    WORKFLOW: READ FILE → COPY EXACT TEXT → PASTE AS match_text
    ════════════════════════════════════════════════════════════════════

    match_text must be LITERAL and EXACT (not regex). Whitespace matters.

    ERRORS ARE HELPFUL: "No match found" or "found N matches, expected 1"
    tells you exactly what went wrong. Just re-read file and fix match_text.

    Multi-line example (file has "def foo():" on one line, "    return 1" on next):
      match_text="def foo():\\n    return 1"

    ════════════════════════════════════════════════════════════════════
    RESPONSE HANDLING
    ════════════════════════════════════════════════════════════════════

    IF "APPROVE": Call commit_review(session_path, path) to save.

    IF "REVIEW": User edited your proposal. Response contains:
      - session_path: Pass in your next call
      - user_feedback_diff: Shows what user changed
      Next call: match_text = user's edited version (not yours)

    ════════════════════════════════════════════════════════════════════
    SPECIAL VALUES FOR match_text
    ════════════════════════════════════════════════════════════════════
    ""              = Create new file (file must not exist)
    "OVERWRITE_FILE" = Replace entire file content

    ════════════════════════════════════════════════════════════════════
    NOTES
    ════════════════════════════════════════════════════════════════════
    - Paths: relative ("src/main.py") or absolute both work
    - expected_replacements=1 means match must be unique (errors if 0 or 2+ found)
    - Sessions stay valid until server restarts
    - user_feedback_diff is a unified diff showing exactly what user changed
    """
    return await propose_and_review_logic(
        validate_path,
        IS_VSCODE_CLI_AVAILABLE,
        path,
        new_string,
        match_text,
        expected_replacements,
        session_path,
        edits,
        bypass_match_text_limit
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
def grep_content(
    pattern: Annotated[
        str,
        Field(description="The regex pattern to search for in file contents. WORKFLOW: Use grep_content FIRST to locate files and line numbers, then read_files for targeted reading. This preserves context by avoiding full file reads. Output includes 'section end hint' to show where functions/classes end.")
    ],
    search_path: Annotated[
        str,
        Field(default='.', description="The directory or file to search in. Defaults to current directory. Prefer relative paths.")
    ] = '.',
    case_insensitive: Annotated[
        bool,
        Field(default=False, description="If True, perform case-insensitive matching (rg -i flag).")
    ] = False,
    context_lines: Annotated[
        int,
        Field(default=2, description="Number of lines of context to show before and after each match (rg --context flag).")
    ] = 2,
    section_patterns: Annotated[
        Optional[List[str]],
        Field(default=None, description="Regex patterns for section boundary detection to generate 'section end hint' metadata. Default: Python patterns ['^def ', '^class ']. Custom: provide your own patterns. Disable: pass empty list []. Use the hint to know exactly which lines to read with read_files.")
    ] = None
) -> str:
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

    # Output might be: File: src/fs_mcp/server.py, Line: 20 (section end hint: L42)

    # Step 2: Read the relevant section of that file.
    read_files([{"path": "src/fs_mcp/server.py", "start_line": 20, "end_line": 42}])
    ```

    **Section End Hinting:**
    - The tool can optionally provide a `section_end_hint` to suggest where a logical block (like a function or class) ends.
    - This is enabled by default with patterns for Python (`def`, `class`).
    - To use custom patterns, provide `section_patterns=["^\\s*custom_pattern"]`.
    - To disable, pass `section_patterns=[]`.
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
    
    # --- Section End Hinting Configuration ---
    active_patterns = []
    if section_patterns is None:
        # Default Python patterns
        active_patterns = [r'^\\s*def ', r'^\\s*class ']
    elif section_patterns: # Not an empty list
        active_patterns = section_patterns

    for line in result.stdout.strip().split('\n'):
        try:
            message = json.loads(line)
            if message['type'] == 'match':
                matches_found = True
                data = message['data']
                path_str = data['path']['text']
                line_number = data['line_number']
                text = data['lines']['text']
                
                hint = ""
                # --- Generate Hint if Enabled ---
                if active_patterns:
                    try:
                        result_file_path = validate_path(path_str)
                        with open(result_file_path, 'r', encoding='utf-8') as f:
                            # Use islice to efficiently seek to the line after the match
                            line_iterator = itertools.islice(f, line_number, None)
                            
                            end_line_num = -1
                            # Scan subsequent lines for a pattern match
                            for i, subsequent_line in enumerate(line_iterator, start=line_number + 1):
                                if any(re.search(p, subsequent_line) for p in active_patterns):
                                    end_line_num = i
                                    break
                            
                            if end_line_num != -1:
                                hint = f" (section end hint: L{end_line_num})"
                            else:
                                hint = " (section end hint: EOF)"

                    except Exception:
                        # If hint generation fails for any reason, just don't add it.
                        pass

                output_lines.append(f"File: {path_str}, Line: {line_number}{hint}\n---\n{text.strip()}\n---")
        except (json.JSONDecodeError, KeyError):
            # Ignore non-match lines or lines with unexpected structure
            continue

    if not matches_found:
        return "No matches found."

    return "\n\n".join(output_lines)




@mcp.tool()
def query_json(
    file_path: Annotated[
        str,
        Field(description="Path to the JSON file to query. Supports relative or absolute paths.")
    ],
    jq_expression: Annotated[
        str,
        Field(description="The jq query expression. Examples: '.field_name' (get field), '.items[]' (iterate array), '.items[] | select(.active == true)' (filter), '.items | length' (count). See https://jqlang.github.io/jq/manual/")
    ],
    timeout: Annotated[
        int,
        Field(default=30, description="Query timeout in seconds. Default is 30. Increase for complex queries on large files.")
    ] = 30
) -> str:
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
def query_yaml(
    file_path: Annotated[
        str,
        Field(description="Path to the YAML file to query. Supports relative or absolute paths.")
    ],
    yq_expression: Annotated[
        str,
        Field(description="The yq query expression (jq-like syntax). Examples: '.field_name' (get field), '.items[]' (iterate array), '.items[] | select(.active == true)' (filter), '.items | length' (count). See mikefarah.gitbook.io/yq")
    ],
    timeout: Annotated[
        int,
        Field(default=30, description="Query timeout in seconds. Default is 30. Increase for complex queries on large files.")
    ] = 30
) -> str:
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
