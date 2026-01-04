from pydantic import BaseModel
import os
import base64
import mimetypes
import fnmatch
from pathlib import Path
from typing import List, Optional, Literal, Dict
from datetime import datetime
from fastmcp import FastMCP

# --- Global Configuration ---
ALLOWED_DIRS: List[Path] = []
mcp = FastMCP("filesystem")

class EditOperation(BaseModel):
    oldText: str
    newText: str

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
def search_files(path: str, pattern: str, exclude_patterns: List[str] = []) -> str:
    """Recursively search for files matching glob pattern."""
    root = validate_path(path)
    results = []
    for r, d, f in os.walk(root):
        d[:] = [x for x in d if not any(fnmatch.fnmatch(x, p) for p in exclude_patterns)]
        for name in f:
            if any(fnmatch.fnmatch(name, p) for p in exclude_patterns): continue
            if fnmatch.fnmatch(name, pattern):
                results.append(str(Path(r) / name))
    return "\n".join(results) or "No matches found"

@mcp.tool()
def get_file_info(path: str) -> str:
    """Retrieve detailed metadata."""
    p = validate_path(path)
    s = p.stat()
    return f"Path: {p}\nType: {'Dir' if p.is_dir() else 'File'}\nSize: {format_size(s.st_size)}\nModified: {datetime.fromtimestamp(s.st_mtime)}"

@mcp.tool()
def directory_tree(path: str, exclude_patterns: List[str] = []) -> str:
    """Get recursive JSON tree."""
    import json
    root = validate_path(path)
    def build(current: Path) -> Dict:
        name = current.name or str(current)
        if any(fnmatch.fnmatch(name, p) for p in exclude_patterns): return None
        node = {"name": name, "type": "directory" if current.is_dir() else "file"}
        if current.is_dir():
            node["children"] = [c for c in [build(e) for e in sorted(current.iterdir(), key=lambda x: x.name)] if c]
        return node
    return json.dumps(build(root), indent=2)

@mcp.tool()
def edit_file(path: str, edits: List[EditOperation], dry_run: bool = False) -> str:
    """Line-based file editing with diff preview."""
    import difflib
    p = validate_path(path)
    
    # Read the original file content and split into lines
    with open(p, 'r', encoding='utf-8') as f:
        original_content = f.read()
    
    original_lines = original_content.splitlines()
    modified_lines = original_lines[:] # Create a mutable copy

    # Process each edit operation on the list of lines
    for edit_op in edits:
        # The input from the agent is a dict, not a Pydantic model instance yet
        old_text = edit_op['oldText']
        new_text = edit_op['newText']
        
        try:
            # Find the index of the exact line to replace
            index_to_replace = modified_lines.index(old_text)
            modified_lines[index_to_replace] = new_text
        except ValueError:
            # This error is raised if .index() doesn't find the item
            raise ValueError(f"Line not found or already modified: '{old_text}'")

    # Join the modified lines back into a single string for saving and diffing
    modified_content = "\n".join(modified_lines)
    
    # Generate the diff between the original and modified content
    diff = "\n".join(difflib.unified_diff(
        original_content.splitlines(), modified_content.splitlines(), 
        fromfile="original", tofile="modified", lineterm=""
    ))
    
    if not dry_run:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(modified_content)
    return diff