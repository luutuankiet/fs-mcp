import json
from pydantic import BaseModel
import os
import base64
import mimetypes
import fnmatch
from pathlib import Path
from typing import List, Optional, Literal, Dict
from datetime import datetime
from fastmcp import FastMCP

from dataclasses import dataclass
import difflib

# The new structure for returning detailed results from the edit tool.
@dataclass
class EditResult:
    success: bool
    message: str
    diff: Optional[str] = None
    error_type: Optional[str] = None

# --- Global Configuration ---
ALLOWED_DIRS: List[Path] = []
mcp = FastMCP("filesystem")


def initialize(directories: List[str]):
    """Initialize the allowed directories configuration."""
    global ALLOWED_DIRS
    ALLOWED_DIRS.clear()
    
    # Resolve all paths to absolute
    # If no paths provided, default to CWD
    raw_dirs = directories or [str(Path.cwd())]
    
    for d in raw_dirs:
        try:
            p = Path(d).expanduser().resolve()
            if not p.exists() or not p.is_dir():
                print(f"Warning: Skipping invalid directory: {p}")
                continue
            ALLOWED_DIRS.append(p)
        except Exception as e:
            print(f"Warning: Could not resolve {d}: {e}")

    if not ALLOWED_DIRS:
        print("Warning: No valid directories allowed. Defaulting to CWD.")
        ALLOWED_DIRS.append(Path.cwd())
            
    return ALLOWED_DIRS

def validate_path(requested_path: str) -> Path:
    """Security barrier: Ensures path is within ALLOWED_DIRS."""
    try:
        path_obj = Path(requested_path).expanduser().resolve()
    except Exception:
        # Handle new files (write ops)
        path_obj = Path(requested_path).expanduser().absolute()
    
    # Check strict containment
    is_allowed = any(
        str(path_obj).startswith(str(allowed)) 
        for allowed in ALLOWED_DIRS
    )
    
    if not is_allowed:
        raise ValueError(f"Access denied: {requested_path} is outside allowed directories.")
    
    return path_obj

def format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

# --- Tools ---

@mcp.tool()
def list_allowed_directories() -> str:
    """List the directories this server is allowed to access."""
    return "\n".join(str(d) for d in ALLOWED_DIRS)

@mcp.tool()
def read_text_file(path: str, head: Optional[int] = None, tail: Optional[int] = None) -> str:
    """Read text file contents."""
    if head is not None and tail is not None:
        raise ValueError("Cannot specify both head and tail")

    path_obj = validate_path(path)
    
    try:
        with open(path_obj, 'r', encoding='utf-8') as f:
            if head is not None:
                return "".join([next(f) for _ in range(head)])
            elif tail is not None:
                return "".join(f.readlines()[-tail:])
            else:
                return f.read()
    except UnicodeDecodeError:
        return f"Error: File {path} appears to be binary. Use read_media_file instead."
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
def read_multiple_files(paths: List[str]) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    """
    results = []
    for p_str in paths:
        try:
            path_obj = validate_path(p_str)
            # Check if it's binary or directory before reading
            if path_obj.is_dir():
                content = "Error: Is a directory"
            else:
                try:
                    content = path_obj.read_text(encoding='utf-8')
                except UnicodeDecodeError:
                    content = "Error: Binary file. Use read_media_file."
            
            results.append(f"File: {p_str}\n{content}")
        except Exception as e:
            results.append(f"File: {p_str}\nError: {e}")
            
    return "\n\n---\n\n".join(results)

@mcp.tool()
def read_media_file(path: str) -> dict:
    """Read an image or audio file as base64."""
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
    """Create a new file or completely overwrite an existing file."""
    path_obj = validate_path(path)
    with open(path_obj, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully wrote to {path}"

@mcp.tool()
def create_directory(path: str) -> str:
    """Create a new directory or ensure it exists."""
    path_obj = validate_path(path)
    os.makedirs(path_obj, exist_ok=True)
    return f"Successfully created directory {path}"

@mcp.tool()
def list_directory(path: str) -> str:
    """Get a detailed listing of all files and directories."""
    path_obj = validate_path(path)
    if not path_obj.is_dir(): return f"Error: {path} is not a directory"
    
    entries = []
    for entry in path_obj.iterdir():
        prefix = "[DIR]" if entry.is_dir() else "[FILE]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(sorted(entries))

@mcp.tool()
def list_directory_with_sizes(path: str) -> str:
    """Get listing with file sizes."""
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
    """Move or rename files."""
    src = validate_path(source)
    dst = validate_path(destination)
    if dst.exists(): raise ValueError(f"Destination {destination} already exists")
    src.rename(dst)
    return f"Moved {source} to {destination}"

@mcp.tool()
def search_files(path: str, pattern: str) -> str:
    """Recursively search for files matching a glob pattern."""
    root = validate_path(path)
    try:
        results = [str(p.relative_to(root)) for p in root.rglob(pattern) if p.is_file()]
        return "\n".join(results) or "No matches found."
    except Exception as e:
        return f"Error during search: {e}"


@mcp.tool()
def get_file_info(path: str) -> str:
    """Retrieve detailed metadata."""
    p = validate_path(path)
    s = p.stat()
    return f"Path: {p}\nType: {'Dir' if p.is_dir() else 'File'}\nSize: {format_size(s.st_size)}\nModified: {datetime.fromtimestamp(s.st_mtime)}"

@mcp.tool()
def directory_tree(path: str, max_depth: int = 3, exclude_dirs: Optional[List[str]] = None) -> str:
    """Get recursive JSON tree with depth limit and default excludes."""
    root = validate_path(path)
    
    # Use provided excludes or our new smart defaults
    default_excludes = ['.git', '.venv', '__pycache__', 'node_modules', '.pytest_cache']
    excluded = exclude_dirs if exclude_dirs is not None else default_excludes

    def build(current: Path, depth: int) -> Optional[Dict]:
        if depth > max_depth or current.name in excluded:
            return None
        
        node = {"name": current.name, "type": "directory" if current.is_dir() else "file"}
        
        if current.is_dir():
            children = []
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

class RooStyleEditTool:
    """
    A robust, agent-friendly file editing tool that validates operations
    before making changes to prevent common errors.
    """
    def count_occurrences(self, content: str, substr: str) -> int:
        if substr == "": return 0
        return content.count(substr)

    def normalize_line_endings(self, content: str) -> str:
        return content.replace('\r\n', '\n').replace('\r', '\n')
    
    def edit_file(self, file_path: str, old_string: str, new_string: str, 
                  expected_replacements: int = 1, dry_run: bool = False) -> EditResult:
        
        p = validate_path(file_path)
        
        file_exists = p.exists()
        is_new_file = not file_exists and old_string == ""

        if not file_exists and not is_new_file:
            return EditResult(success=False, message=f"File not found: {file_path}. To create a new file, old_string must be empty.", error_type="file_not_found")
        
        if file_exists and is_new_file:
            return EditResult(success=False, message=f"File '{file_path}' already exists. Cannot create a new file when one already exists.", error_type="file_exists")
        
        original_content = ""
        if file_exists:
            try:
                original_content = p.read_text(encoding='utf-8')
            except Exception as e:
                return EditResult(success=False, message=f"Failed to read file: {e}", error_type="read_error")

        normalized_content = self.normalize_line_endings(original_content)
        normalized_old = self.normalize_line_endings(old_string)
        
        if not is_new_file:
            if old_string == new_string:
                return EditResult(success=False, message="No changes to apply. The old_string and new_string are identical.", error_type="validation_error")
            
            occurrences = self.count_occurrences(normalized_content, normalized_old)
            
            if occurrences == 0:
                return EditResult(success=False, message="No match found for the specified 'old_string'. Please ensure it matches exactly.", error_type="validation_error")
            
            if occurrences != expected_replacements:
                return EditResult(success=False, message=f"Expected {expected_replacements} occurrence(s) but found {occurrences}. Please adjust your 'old_string' or 'expected_replacements' value.", error_type="validation_error")
        
        if is_new_file:
            new_content = new_string
        else:
            # Note: This is a global replace, not line-by-line.
            new_content = normalized_content.replace(normalized_old, new_string)
        
        diff_str = "\n".join(difflib.unified_diff(
            original_content.splitlines(), new_content.splitlines(), 
            fromfile=f"a/{file_path}", tofile=f"b/{file_path}", lineterm=""
        ))
        
        if not dry_run:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(new_content, encoding='utf-8')
            except Exception as e:
                return EditResult(success=False, message=f"Failed to write to file: {e}", error_type="write_error")

        return EditResult(success=True, message=f"Successfully edited '{file_path}'.", diff=diff_str)

@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str, 
              expected_replacements: int = 1, dry_run: bool = False) -> str:
    """
    [UPGRADED] A robust tool for editing files. It can replace text, create new files,
    and provides detailed, agent-friendly error messages to prevent mistakes.
    - To create a new file, set `old_string` to "" and provide the full content in `new_string`.
    - To replace text, provide the exact `old_string` to be replaced.
    - `expected_replacements` ensures you don't accidentally edit more lines than intended.
    """
    tool = RooStyleEditTool()
    result = tool.edit_file(path, old_string, new_string, expected_replacements, dry_run)
    
    if result.success:
        output = result.message
        if result.diff:
            output += f"\n\n--- DIFF ---\n{result.diff}"
        return output
    else:
        # Raising an exception is the correct way to signal a tool error.
        raise ValueError(f"Edit failed: {result.message} (Error type: {result.error_type})")


@mcp.tool()
def grounding_search(query: str) -> str:
    """[NEW] A custom search tool. Accepts a natural language query and returns a grounded response."""
    # This is a placeholder for a future RAG or other search implementation.
    print(f"Received grounding search query: {query}")
    return "DEVELOPER PLEASE UPDATE THIS WITH ACTUAL CONTENT"


@mcp.tool()
def append_text(path: str, content: str) -> str:
    """
    Append text to the end of a file. 
    Use this as a fallback if edit_file fails to find a match.
    """
    p = validate_path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}. Cannot append to a non-existent file.")
    
    # Ensure there is a newline at the start of the append if the file doesn't have one
    # to avoid clashing with the existing last line.
    with open(p, 'a', encoding='utf-8') as f:
        # Check if we need a leading newline
        if p.stat().st_size > 0:
            f.write("\n")
        f.write(content)
        
    return f"Successfully appended content to '{path}'."

