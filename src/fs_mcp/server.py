import json
from pydantic import BaseModel
from typing import Optional

class FileReadRequest(BaseModel):
    path: str
    head: Optional[int] = None
    tail: Optional[int] = None


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
import difflib

# The new structure for returning detailed results from the edit tool.
@dataclass
class EditResult:
    success: bool
    message: str
    diff: Optional[str] = None
    error_type: Optional[str] = None
    original_content: Optional[str] = None
    new_content: Optional[str] = None


# --- Global Configuration ---
ALLOWED_DIRS: List[Path] = []
mcp = FastMCP("filesystem")
IS_VSCODE_CLI_AVAILABLE = False


def initialize(directories: List[str]):
    """Initialize the allowed directories and check for VS Code CLI."""
    global ALLOWED_DIRS, IS_VSCODE_CLI_AVAILABLE
    ALLOWED_DIRS.clear()
    
    IS_VSCODE_CLI_AVAILABLE = shutil.which('code') is not None
    # if IS_VSCODE_CLI_AVAILABLE:
    #     print("✅ VS Code CLI detected. Diff windows will open automatically.")
    # else:
    #     print("ℹ️ VS Code CLI ('code') not found in PATH. Please open diff views manually.")

    # a CWD, and the system's temporary directory for review sessions.
    raw_dirs = directories or [str(Path.cwd())]
    
    # Add the system's temp directory to the list of raw directories
    # to allow access to review session files.
    raw_dirs.append(tempfile.gettempdir())
    
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
        # It must be inside a directory created by our review tool or by pytest.
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
    return "\n".join(str(d) for d in ALLOWED_DIRS)

@mcp.tool()
def read_files(files: List[FileReadRequest]) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    Prefer relative paths.
    """
    results = []
    for file_request_data in files:
        if isinstance(file_request_data, dict):
            file_request = FileReadRequest(**file_request_data)
        else:
            file_request = file_request_data
            
        try:
            path_obj = validate_path(file_request.path)
            if file_request.head is not None and file_request.tail is not None:
                raise ValueError("Cannot specify both head and tail for a single file.")
            
            if path_obj.is_dir():
                content = "Error: Is a directory"
            else:
                try:
                    with open(path_obj, 'r', encoding='utf-8') as f:
                        if file_request.head is not None:
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
    """Retrieve detailed metadata. Prefer relative paths."""
    p = validate_path(path)
    s = p.stat()
    return f"Path: {p}\nType: {'Dir' if p.is_dir() else 'File'}\nSize: {format_size(s.st_size)}\nModified: {datetime.fromtimestamp(s.st_mtime)}"

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

class RooStyleEditTool:
    """A robust, agent-friendly file editing tool."""
    def count_occurrences(self, content: str, substr: str) -> int:
        return content.count(substr) if substr else 0
    def normalize_line_endings(self, content: str) -> str:
        return content.replace('\r\n', '\n').replace('\r', '\n')
    
    def _prepare_edit(self, file_path: str, old_string: str, new_string: str, expected_replacements: int) -> EditResult:
        p = validate_path(file_path)
        file_exists = p.exists()
        is_new_file = not file_exists and old_string == ""
        if not file_exists and not is_new_file:
            return EditResult(success=False, message=f"File not found: {file_path}", error_type="file_not_found")
        if file_exists and is_new_file:
            return EditResult(success=False, message=f"File '{file_path}' already exists.", error_type="file_exists")
        original_content = p.read_text(encoding='utf-8') if file_exists else ""
        normalized_content = self.normalize_line_endings(original_content)
        normalized_old = self.normalize_line_endings(old_string)
        if not is_new_file:
            if old_string == new_string:
                return EditResult(success=False, message="No changes to apply.", error_type="validation_error")
            occurrences = self.count_occurrences(normalized_content, normalized_old)
            if occurrences == 0:
                return EditResult(success=False, message="No match found for 'old_string'.", error_type="validation_error")
            if occurrences != expected_replacements:
                return EditResult(success=False, message=f"Expected {expected_replacements} occurrences but found {occurrences}.", error_type="validation_error")
        new_content = new_string if is_new_file else normalized_content.replace(normalized_old, new_string)
        return EditResult(success=True, message="Edit prepared.", original_content=original_content, new_content=new_content)

# --- Interactive Human-in-the-Loop Tools ---
APPROVAL_KEYWORD = "##APPROVE##"




@mcp.tool()
def propose_and_review(path: str, new_string: str, old_string: str = "", expected_replacements: int = 1, session_path: Optional[str] = None) -> str:
    """
    Starts or continues an interactive review session using a VS Code diff view.
    This smart tool adapts its behavior based on the arguments provided.

    Intents:
    1.  **Start New Review (Patch):** Provide `path`, `old_string`, `new_string`. Validates the patch against the original file.
    2.  **Start New Review (Full Rewrite):** Provide `path`, `new_string`, and leave `old_string` empty.
    3.  **Continue Review (Contextual Patch):** Provide `path`, `session_path`, `old_string`, and `new_string`.
    4.  **Continue Review (Full Rewrite / Recovery):** Provide `path`, `session_path`, `new_string`, and the full content of the file as `old_string`.

    Note: `path` is always required to identify the file being edited, even when continuing a session.

    It blocks and waits for the user to save the file, then returns their action ('APPROVE' or 'REVIEW').
    """
    tool = RooStyleEditTool()
    original_path_obj = Path(path)
    active_proposal_content = ""

    # --- Step 1: Determine Intent and Prepare Session ---
    if session_path:
        # --- INTENT: CONTINUING AN EXISTING SESSION ---
        temp_dir = Path(session_path)
        if not temp_dir.is_dir():
            raise ValueError(f"Session path {session_path} does not exist.")
        
        current_file_path = temp_dir / f"current_{original_path_obj.name}"
        future_file_path = temp_dir / f"future_{original_path_obj.name}"
        
        staged_content = current_file_path.read_text(encoding='utf-8')
        
        # The `old_string` is the "contextual anchor". We try to apply it as a patch.
        occurrences = tool.count_occurrences(staged_content, old_string)
        
        if occurrences != 1:
            # SAFETY VALVE: The patch is ambiguous or invalid. Fail gracefully.
            raise ValueError(f"Contextual patch failed. The provided 'old_string' anchor was found {occurrences} times in the user's last version, but expected exactly 1. Please provide the full file content as 'old_string' to recover.")
            
        # Patch successfully applied.
        active_proposal_content = staged_content.replace(old_string, new_string, 1)
        future_file_path.write_text(active_proposal_content, encoding='utf-8')

    else:
        # --- INTENT: STARTING A NEW SESSION ---
        temp_dir = Path(tempfile.mkdtemp(prefix="mcp_review_"))
        current_file_path = temp_dir / f"current_{original_path_obj.name}"
        future_file_path = temp_dir / f"future_{original_path_obj.name}"
        
        prep_result = tool._prepare_edit(path, old_string, new_string, expected_replacements)
        if not prep_result.success:
            if temp_dir.exists(): shutil.rmtree(temp_dir)
            raise ValueError(f"Edit preparation failed: {prep_result.message} (Error type: {prep_result.error_type})")

        if prep_result.original_content is not None:
            current_file_path.write_text(prep_result.original_content, encoding='utf-8')
        active_proposal_content = prep_result.new_content
        if active_proposal_content is not None:
            future_file_path.write_text(active_proposal_content, encoding='utf-8')

    # --- Step 2: Display, Launch, and Wait for Human ---
    vscode_command = f'code --diff "{current_file_path}" "{future_file_path}"'
    
    print(f"\n--- WAITING FOR HUMAN REVIEW ---\nPlease review the proposed changes in VS Code:\n\n{vscode_command}\n")
    print(f'To approve, add a double newline to the end of the file before saving.')
    if IS_VSCODE_CLI_AVAILABLE:
        try:
            subprocess.Popen(vscode_command, shell=True)
            print("✅ Automatically launched VS Code diff view.")
        except Exception as e:
            print(f"⚠️ Failed to launch VS Code automatically: {e}")

    initial_mod_time = future_file_path.stat().st_mtime
    while True:
        time.sleep(1)
        if future_file_path.stat().st_mtime > initial_mod_time: break
    
    # --- Step 3: Interpret User's Action ---
    user_edited_content = future_file_path.read_text(encoding='utf-8')
    response = {"session_path": str(temp_dir)}

    if user_edited_content.endswith("\n\n"):
        # Remove trailing newlines
        clean_content = user_edited_content.rstrip('\n')
        # hey roo confirm if this triggers ONLY IF the user manually appends 2 newline in their review. otherwise we'll have false positive. 
        try:
            future_file_path.write_text(clean_content, encoding='utf-8')
            print("✅ Approval detected. You can safely close the diff view.")
        except Exception as e:
            print(f"⚠️ Could not auto-remove keyword from review file: {e}")
        response["user_action"] = "APPROVE"
        response["message"] = "User has approved the changes. Call 'commit_review' to finalize."
    else:
        current_file_path.write_text(user_edited_content, encoding='utf-8')
        user_feedback_diff = "".join(difflib.unified_diff(
            active_proposal_content.splitlines(keepends=True) if active_proposal_content is not None else [],
            user_edited_content.splitlines(keepends=True),
            fromfile=f"a/{future_file_path.name} (agent proposal)",
            tofile=f"b/{future_file_path.name} (user feedback)"
        ))
        response["user_action"] = "REVIEW"
        response["message"] = "User provided feedback. A diff is included. Propose a new edit against the updated content."
        response["user_feedback_diff"] = user_feedback_diff
        
    return json.dumps(response, indent=2)

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
def append_text(path: str, content: str) -> str:
    """
    Append text to the end of a file. 
    Use this as a fallback if edit_file fails to find a match.
    Prefer relative paths.
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