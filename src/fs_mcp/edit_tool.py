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

    def sanitize_content(self, content: str) -> str:
        return content.replace('\\', '_ROO_PLACEHOLDER_BS_').replace('\n', '_ROO_PLACEHOLDER_NL_').replace('\r', '_ROO_PLACEHOLDER_CR_')

    def desanitize_content(self, content: str) -> str:
        return content.replace('_ROO_PLACEHOLDER_CR_', '\r').replace('_ROO_PLACEHOLDER_NL_', '\n').replace('_ROO_PLACEHOLDER_BS_', '\\')

    def _prepare_edit(self, file_path: str, old_string: str, new_string: str, expected_replacements: int) -> EditResult:
        p = self.validate_path(file_path)
        file_exists = p.exists()
        is_new_file = not file_exists and old_string == ""
        if not file_exists and not is_new_file:
            return EditResult(success=False, message=f"File not found: {file_path}", error_type="file_not_found")
        if file_exists and is_new_file:
            return EditResult(success=False, message=f"File '{file_path}' already exists.", error_type="file_exists")
        original_content = p.read_text(encoding='utf-8') if file_exists else ""

        # Escape literal `\n` before processing
        sanitized_original_content = self.sanitize_content(original_content)
        sanitized_old_string = self.sanitize_content(old_string)
        sanitized_new_string = self.sanitize_content(new_string)

        normalized_content = self.normalize_line_endings(sanitized_original_content)
        normalized_old = self.normalize_line_endings(sanitized_old_string)

        if not is_new_file:
            if old_string == new_string:
                return EditResult(success=False, message="No changes to apply.", error_type="validation_error")
            
            # If old_string is empty, it's a full rewrite of an existing file.
            if not old_string:
                replaced_content = sanitized_new_string
            else:
                occurrences = self.count_occurrences(normalized_content, normalized_old)
                if occurrences == 0:
                    return EditResult(success=False, message="No match found for 'old_string'.", error_type="validation_error")
                if occurrences != expected_replacements:
                    return EditResult(success=False, message=f"Expected {expected_replacements} occurrences but found {occurrences}.", error_type="validation_error")
                replaced_content = normalized_content.replace(normalized_old, sanitized_new_string)
        else:
            replaced_content = sanitized_new_string

        # Unescape before returning the final content
        new_content = self.desanitize_content(replaced_content)

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
        
        staged_content = tool.sanitize_content(current_file_path.read_text(encoding='utf-8'))
        
        # The `old_string` is the "contextual anchor". We try to apply it as a patch.
        occurrences = tool.count_occurrences(staged_content, tool.sanitize_content(old_string))
        
        if occurrences != 1:
            # SAFETY VALVE: The patch is ambiguous or invalid. Fail gracefully.
            raise ValueError(f"Contextual patch failed. The provided 'old_string' anchor was found {occurrences} times in the user's last version, but expected exactly 1. Please provide the full file content as 'old_string' to recover.")
            
        # Patch successfully applied.
        active_proposal_content = staged_content.replace(tool.sanitize_content(old_string), tool.sanitize_content(new_string), 1)
        future_file_path.write_text(tool.desanitize_content(active_proposal_content), encoding='utf-8')
        

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
        
        try:
            future_file_path.write_text(clean_content, encoding='utf-8')
            print("✅ Approval detected. You can safely close the diff view.")
        except Exception as e:
            print(f"⚠️ Could not auto-remove keyword from review file: {e}")
        response["user_action"] = "APPROVE"
        response["message"] = "User has approved the changes. Call 'commit_review' to finalize."
    else:
        current_file_path.write_text(user_edited_content, encoding='utf-8')
        
        # Escape content before diffing
        sanitized_proposal = tool.sanitize_content(active_proposal_content) if active_proposal_content is not None else ""
        sanitized_user_content = tool.sanitize_content(user_edited_content)

        user_feedback_diff = "".join(difflib.unified_diff(
            sanitized_proposal.splitlines(keepends=True),
            sanitized_user_content.splitlines(keepends=True),
            fromfile=f"a/{future_file_path.name} (agent proposal)",
            tofile=f"b/{future_file_path.name} (user feedback)"
        ))
        response["user_action"] = "REVIEW"
        response["message"] = "User provided feedback. A diff is included. Propose a new edit against the updated content."
        response["user_feedback_diff"] = tool.desanitize_content(user_feedback_diff)
        
    return json.dumps(response, indent=2)
