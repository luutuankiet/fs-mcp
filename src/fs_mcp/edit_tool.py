from dataclasses import dataclass
from typing import Optional
import asyncio
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


async def propose_and_review_logic(
    validate_path,
    IS_VSCODE_CLI_AVAILABLE,
    path: str,
    new_string: str,
    old_string: str = "",
    expected_replacements: int = 1,
    session_path: Optional[str] = None,
    edits: Optional[list] = None
) -> str:
    # --- Validate multi-edit parameter ---
    edit_pairs = None
    if edits:
        if not isinstance(edits, list) or len(edits) == 0:
            raise ValueError("'edits' must be a non-empty list.")
        for i, pair in enumerate(edits):
            if not isinstance(pair, dict) or 'old_string' not in pair or 'new_string' not in pair:
                raise ValueError(f"Edit at index {i} must have 'old_string' and 'new_string' keys.")
        edit_pairs = edits

    # --- Validation: Prevent accidental file overwrite ---
    # If old_string is blank but file has content, require explicit OVERWRITE_FILE sentinel
    OVERWRITE_SENTINEL = "OVERWRITE_FILE"
    OLD_STRING_MAX_LENGTH = 500

    # Get all old_strings to validate (from edits or single old_string)
    old_strings_to_validate = []
    if edit_pairs:
        old_strings_to_validate = [pair['old_string'] for pair in edit_pairs]
    else:
        old_strings_to_validate = [old_string]

    # Check for blank old_string on non-blank files
    for idx, os_val in enumerate(old_strings_to_validate):
        if os_val == "" or (os_val is not None and os_val.strip() == ""):
            # old_string is blank - check if file exists and has content
            p = validate_path(path)
            if p.exists():
                file_content = p.read_text(encoding='utf-8')
                if file_content.strip() != "":
                    # File is not blank - reject unless user explicitly wants to overwrite
                    error_msg = (
                        "WARN: you are trying to overwrite a file, which could be a mistake if you are not aware of the file content. "
                        "Either use grep_text + read_files to do surgical update if this is a mistake, "
                        f"or pass in old_string this exact string '{OVERWRITE_SENTINEL}' if the user agrees to overwrite."
                    )
                    if edit_pairs:
                        error_msg = f"Edit {idx}: {error_msg}"
                    raise ValueError(error_msg)
        elif os_val == OVERWRITE_SENTINEL:
            # User explicitly wants to overwrite - convert sentinel to empty string for processing
            if edit_pairs:
                edit_pairs[idx]['old_string'] = ""
            else:
                old_string = ""

    # Check for old_string that is too long (>500 characters)
    for idx, os_val in enumerate(old_strings_to_validate):
        if os_val and os_val != OVERWRITE_SENTINEL and len(os_val) > OLD_STRING_MAX_LENGTH:
            error_msg = (
                f"ERROR: old_string is too long and brittle (over {OLD_STRING_MAX_LENGTH} characters) which does not follow best practice. "
                "You might be over eager proposing changes to parts that do not need change at all. "
                "Consider do send the list of surgical edits with smaller tokens per edit instead of doing a big rewrite."
            )
            if edit_pairs:
                error_msg = f"Edit {idx}: {error_msg}"
            raise ValueError(error_msg)

    # --- GSD-Lite Auto-Approve ---
    if 'gsd-lite' in Path(path).parts:
        tool = RooStyleEditTool(validate_path)
        if edit_pairs:
            p = validate_path(path)
            content = p.read_text(encoding='utf-8') if p.exists() else ""
            normalized = tool.normalize_line_endings(content)
            for i, pair in enumerate(edit_pairs):
                old_s = tool.normalize_line_endings(pair['old_string'])
                new_s = pair['new_string']
                if old_s and normalized.count(old_s) != 1:
                    error_response = {
                        "error": True,
                        "error_type": "validation_error",
                        "message": f"Edit {i}: old_string found {normalized.count(old_s)} times, expected 1.",
                    }
                    line_count = content.count('\n') + 1
                    if line_count < 5000:
                        error_response["file_content"] = content
                        error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your old_string for edit {i}."
                    raise ValueError(json.dumps(error_response, indent=2))
                normalized = normalized.replace(old_s, new_s, 1) if old_s else new_s
            p.write_text(normalized, encoding='utf-8')
            response = {
                "user_action": "AUTO_APPROVED",
                "message": f"Auto-approved and committed {len(edit_pairs)} edits to '{path}' because it is in the 'gsd_lite' directory.",
                "session_path": None
            }
            return json.dumps(response, indent=2)
        else:
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
                "session_path": None
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

        if edit_pairs:
            # --- MULTI-EDIT CONTINUATION ---
            normalized = tool.normalize_line_endings(staged_content)
            for i, pair in enumerate(edit_pairs):
                old_s = tool.normalize_line_endings(pair['old_string'])
                new_s = pair['new_string']
                if old_s:
                    occurrences = tool.count_occurrences(normalized, old_s)
                    if occurrences != 1:
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: old_string found {occurrences} times in session content, expected 1.",
                        }
                        line_count = staged_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = staged_content
                            error_response["hint"] = f"Session file has {line_count} lines. Content included above — use it to correct your old_string for edit {i}."
                        raise ValueError(json.dumps(error_response, indent=2))
                    normalized = normalized.replace(old_s, new_s, 1)
                else:
                    normalized = new_s
            active_proposal_content = normalized
            future_file_path.write_text(active_proposal_content, encoding='utf-8')
        else:
            # --- SINGLE-EDIT CONTINUATION ---
            occurrences = tool.count_occurrences(staged_content, old_string)

            if occurrences != 1:
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

            active_proposal_content = staged_content.replace(old_string, new_string, 1)
            future_file_path.write_text(active_proposal_content, encoding='utf-8')
        

    else:
        # --- INTENT: STARTING A NEW SESSION ---
        temp_dir = Path(tempfile.mkdtemp(prefix="mcp_review_"))
        current_file_path = temp_dir / f"current_{original_path_obj.name}"
        future_file_path = temp_dir / f"future_{original_path_obj.name}"

        if edit_pairs:
            # --- MULTI-EDIT MODE ---
            p = validate_path(path)
            if not p.exists():
                if temp_dir.exists(): shutil.rmtree(temp_dir)
                raise ValueError(f"File not found: {path}")
            original_content = p.read_text(encoding='utf-8')
            normalized = tool.normalize_line_endings(original_content)

            for i, pair in enumerate(edit_pairs):
                old_s = tool.normalize_line_endings(pair['old_string'])
                new_s = pair['new_string']
                if old_s:
                    occurrences = tool.count_occurrences(normalized, old_s)
                    if occurrences == 0:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: No match found for 'old_string'.",
                        }
                        line_count = original_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = original_content
                            error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your old_string for edit {i}."
                        else:
                            error_response["hint"] = f"File has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
                        raise ValueError(json.dumps(error_response, indent=2))
                    if occurrences != 1:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: Expected 1 occurrence but found {occurrences}. Provide more context in old_string to ensure uniqueness.",
                        }
                        line_count = original_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = original_content
                            error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your old_string for edit {i}."
                        raise ValueError(json.dumps(error_response, indent=2))
                    normalized = normalized.replace(old_s, new_s, 1)
                else:
                    # Empty old_string in a multi-edit means full rewrite (only valid as sole edit)
                    if len(edit_pairs) > 1:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        raise ValueError("Edit with empty old_string (full rewrite) cannot be combined with other edits.")
                    normalized = new_s

            current_file_path.write_text(original_content, encoding='utf-8')
            active_proposal_content = normalized
            future_file_path.write_text(active_proposal_content, encoding='utf-8')
        else:
            # --- SINGLE-EDIT MODE (original behavior) ---
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
        await asyncio.sleep(1)
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
