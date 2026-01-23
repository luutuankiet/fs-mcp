from dataclasses import dataclass
from typing import Optional
import difflib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

# The new structure for returning detailed results from the edit tool.
@dataclass
class EditResult:
    success: bool
    message: str
    diff: Optional[str] = None
    error_type: Optional[str] = None
    original_content: Optional[str] = None
    new_content: Optional[str] = None


class RooStyleEditTool:
    """A robust, agent-friendly file editing tool."""
    def __init__(self, validate_path_func):
        self.validate_path = validate_path_func

    def count_occurrences(self, content: str, substr: str) -> int:
        return content.count(substr) if substr else 0
    def normalize_line_endings(self, content: str) -> str:
        return content.replace('\r\n', '\n').replace('\r', '\n')


    def _prepare_edit(self, file_path: str, old_string: str, new_string: str, expected_replacements: int) -> EditResult:
        p = self.validate_path(file_path)
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

            # If old_string is empty, it's a full rewrite of an existing file.
            if not old_string:
                new_content = new_string
            else:
                occurrences = self.count_occurrences(normalized_content, normalized_old)
                if occurrences == 0:
                    return EditResult(success=False, message="No match found for 'old_string'.", error_type="validation_error")
                if occurrences != expected_replacements:
                    return EditResult(success=False, message=f"Expected {expected_replacements} occurrences but found {occurrences}.", error_type="validation_error")
                new_content = normalized_content.replace(normalized_old, new_string)
        else:
            new_content = new_string

        return EditResult(success=True, message="Edit prepared.", original_content=original_content, new_content=new_content)


def propose_and_review_logic(
    validate_path,
    IS_VSCODE_CLI_AVAILABLE,
    path: str,
    new_string: str,
    old_string: str = "",
    expected_replacements: int = 1,
    session_path: Optional[str] = None
) -> str:
    # --- GSD-Lite Auto-Approve ---
    if 'gsd-lite' in Path(path).parts:
        tool = RooStyleEditTool(validate_path)
        prep_result = tool._prepare_edit(path, old_string, new_string, expected_replacements)
        if not prep_result.success:
            error_response = {
                "error": True,
                "error_type": prep_result.error_type,
                "message": f"Edit preparation failed: {prep_result.message}",
            }
            if prep_result.error_type == "validation_error":
                p = Path(path)
                if p.exists():
                    content = p.read_text(encoding='utf-8')
                    line_count = content.count('\n') + 1
                    if line_count < 5000:
                        error_response["file_content"] = content
                        error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your old_string."
                    else:
                        error_response["hint"] = f"File has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
            raise ValueError(json.dumps(error_response, indent=2))
        
        if prep_result.new_content is not None:
            p = validate_path(path)
            p.write_text(prep_result.new_content, encoding='utf-8')
        
        response = {
            "user_action": "AUTO_APPROVED",
            "message": f"Auto-approved and committed changes to '{path}' because it is in the 'gsd_lite' directory.",
            "session_path": None # No session needed for auto-commit
        }
        return json.dumps(response, indent=2)

    tool = RooStyleEditTool(validate_path)
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
            error_response = {
                "error": True,
                "error_type": "validation_error",
                "message": f"Contextual patch failed. The provided 'old_string' anchor was found {occurrences} times in the user's last version, but expected exactly 1.",
            }
            line_count = staged_content.count('\n') + 1
            if line_count < 5000:
                error_response["file_content"] = staged_content
                error_response["hint"] = f"Session file has {line_count} lines. Content included above — use it to correct your old_string."
            else:
                error_response["hint"] = f"Session file has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
            raise ValueError(json.dumps(error_response, indent=2))

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
            error_response = {
                "error": True,
                "error_type": prep_result.error_type,
                "message": f"Edit preparation failed: {prep_result.message}",
            }
            if prep_result.error_type == "validation_error" and original_path_obj.exists():
                content = original_path_obj.read_text(encoding='utf-8')
                line_count = content.count('\n') + 1
                if line_count < 5000:
                    error_response["file_content"] = content
                    error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your old_string."
                else:
                    error_response["hint"] = f"File has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
            raise ValueError(json.dumps(error_response, indent=2))

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
        
        try:
            future_file_path.write_text(clean_content, encoding='utf-8')
            print("✅ Approval detected. You can safely close the diff view.")
        except Exception as e:
            print(f"⚠️ Could not auto-remove keyword from review file: {e}")
        response["user_action"] = "APPROVE"
        response["message"] = "User has approved the changes. Call 'commit_review' to finalize."
    else:
        current_file_path.write_text(user_edited_content, encoding='utf-8')
        
        proposal_text = active_proposal_content if active_proposal_content is not None else ""

        user_feedback_diff = "".join(difflib.unified_diff(
            proposal_text.splitlines(keepends=True),
            user_edited_content.splitlines(keepends=True),
            fromfile=f"a/{future_file_path.name} (agent proposal)",
            tofile=f"b/{future_file_path.name} (user feedback)"
        ))
        response["user_action"] = "REVIEW"
        response["message"] = "User provided feedback. A diff is included. Propose a new edit against the updated content."
        response["user_feedback_diff"] = user_feedback_diff
        
    return json.dumps(response, indent=2)
