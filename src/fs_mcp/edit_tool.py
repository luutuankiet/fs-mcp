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

# --- Configuration Constants ---
MATCH_TEXT_MAX_LENGTH = 2000
OVERWRITE_SENTINEL = "OVERWRITE_FILE"

# Backward compatibility alias
OLD_STRING_MAX_LENGTH = MATCH_TEXT_MAX_LENGTH

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


    def _prepare_edit(self, file_path: str, match_text: str, new_string: str, expected_replacements: int) -> EditResult:
        p = self.validate_path(file_path)
        file_exists = p.exists()
        is_new_file = not file_exists and match_text == ""
        if not file_exists and not is_new_file:
            return EditResult(success=False, message=f"File not found: {file_path}", error_type="file_not_found")
        if file_exists and is_new_file:
            return EditResult(success=False, message=f"File '{file_path}' already exists.", error_type="file_exists")
        original_content = p.read_text(encoding='utf-8') if file_exists else ""

        normalized_content = self.normalize_line_endings(original_content)
        normalized_match = self.normalize_line_endings(match_text)

        if not is_new_file:
            if match_text == new_string:
                return EditResult(success=False, message="No changes to apply.", error_type="validation_error")

            # If match_text is empty, it's a full rewrite of an existing file.
            if not match_text:
                new_content = new_string
            else:
                occurrences = self.count_occurrences(normalized_content, normalized_match)
                if occurrences == 0:
                    return EditResult(success=False, message="No match found for 'match_text'.", error_type="validation_error")
                if occurrences != expected_replacements:
                    return EditResult(success=False, message=f"Expected {expected_replacements} occurrences but found {occurrences}.", error_type="validation_error")
                new_content = normalized_content.replace(normalized_match, new_string)
        else:
            new_content = new_string

        return EditResult(success=True, message="Edit prepared.", original_content=original_content, new_content=new_content)


async def propose_and_review_logic(
    validate_path,
    IS_VSCODE_CLI_AVAILABLE,
    path: str,
    new_string: str,
    match_text: str = "",
    expected_replacements: int = 1,
    session_path: Optional[str] = None,
    edits: Optional[list] = None,
    bypass_match_text_limit: bool = False
) -> str:
    # --- Validate multi-edit parameter ---
    edit_pairs = None
    if edits:
        if not isinstance(edits, list) or len(edits) == 0:
            raise ValueError("'edits' must be a non-empty list.")

        # Normalize EditPair objects to dicts for consistent handling
        normalized_edits = []
        for pair in edits:
            if hasattr(pair, 'model_dump'):  # Pydantic v2
                normalized_edits.append(pair.model_dump())
            elif hasattr(pair, 'dict'):  # Pydantic v1
                normalized_edits.append(pair.dict())
            elif isinstance(pair, dict):
                normalized_edits.append(pair)
            else:
                raise ValueError(f"Edit must be a dict or EditPair, got {type(pair)}")
        edits = normalized_edits

        for i, pair in enumerate(edits):
            if not isinstance(pair, dict) or 'match_text' not in pair or 'new_string' not in pair:
                raise ValueError(f"Edit at index {i} must have 'match_text' and 'new_string' keys.")
        edit_pairs = edits

    # --- Validation: Prevent accidental file overwrite ---
    # If match_text is blank but file has content, require explicit OVERWRITE_FILE sentinel
    # Note: OVERWRITE_SENTINEL and MATCH_TEXT_MAX_LENGTH are module-level constants

    # Get all match_texts to validate (from edits or single match_text)
    match_texts_to_validate = []
    if edit_pairs:
        match_texts_to_validate = [pair['match_text'] for pair in edit_pairs]
    else:
        match_texts_to_validate = [match_text]

    # Check for blank match_text on non-blank files
    for idx, mt_val in enumerate(match_texts_to_validate):
        if mt_val == "" or (mt_val is not None and mt_val.strip() == ""):
            # match_text is blank - check if file exists and has content
            p = validate_path(path)
            if p.exists():
                file_content = p.read_text(encoding='utf-8')
                if file_content.strip() != "":
                    # File is not blank - reject unless user explicitly wants to overwrite
                    error_msg = (
                        "ERROR: match_text is empty but file has content. "
                        "You MUST provide the exact text you want to replace. "
                        "Use read_files or grep_content first to get the current content, then provide "
                        "the EXACT lines you want to change in match_text. "
                        f"For intentional full-file overwrites, pass match_text='{OVERWRITE_SENTINEL}'."
                    )
                    if edit_pairs:
                        error_msg = f"Edit {idx}: {error_msg}"
                    raise ValueError(error_msg)
        elif mt_val == OVERWRITE_SENTINEL:
            # User explicitly wants to overwrite - convert sentinel to empty string for processing
            if edit_pairs:
                edit_pairs[idx]['match_text'] = ""
            else:
                match_text = ""

    # Check for match_text that is too long (>2000 characters)
    # Can be bypassed with bypass_match_text_limit=True for legitimate large section edits
    for idx, mt_val in enumerate(match_texts_to_validate):
        if mt_val and mt_val != OVERWRITE_SENTINEL and len(mt_val) > MATCH_TEXT_MAX_LENGTH:
            if bypass_match_text_limit:
                # User has explicitly opted to bypass the limit - this is a last resort
                # Log a warning but allow the operation to proceed
                continue
            error_msg = (
                f"ERROR: match_text is too long (over {MATCH_TEXT_MAX_LENGTH} characters). "
                "RECOMMENDED: Break your change into multiple smaller edits using the 'edits' parameter, "
                f"each match_text under {MATCH_TEXT_MAX_LENGTH} chars. "
                "LAST RESORT: If you genuinely need to replace a large contiguous section (e.g., updating a large markdown block), "
                "set bypass_match_text_limit=True to override this limit."
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
                mt = tool.normalize_line_endings(pair['match_text'])
                new_s = pair['new_string']
                if mt and normalized.count(mt) != 1:
                    error_response = {
                        "error": True,
                        "error_type": "validation_error",
                        "message": f"Edit {i}: match_text found {normalized.count(mt)} times, expected 1.",
                    }
                    line_count = content.count('\n') + 1
                    if line_count < 5000:
                        error_response["file_content"] = content
                        error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your match_text for edit {i}."
                    raise ValueError(json.dumps(error_response, indent=2))
                normalized = normalized.replace(mt, new_s, 1) if mt else new_s
            p.write_text(normalized, encoding='utf-8')
            response = {
                "user_action": "AUTO_APPROVED",
                "message": f"Auto-approved and committed {len(edit_pairs)} edits to '{path}' because it is in the 'gsd_lite' directory.",
                "session_path": None
            }
            return json.dumps(response, indent=2)
        else:
            prep_result = tool._prepare_edit(path, match_text, new_string, expected_replacements)
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
                            error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your match_text."
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
                mt = tool.normalize_line_endings(pair['match_text'])
                new_s = pair['new_string']
                if mt:
                    occurrences = tool.count_occurrences(normalized, mt)
                    if occurrences != 1:
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: match_text found {occurrences} times in session content, expected 1.",
                        }
                        line_count = staged_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = staged_content
                            error_response["hint"] = f"Session file has {line_count} lines. Content included above — use it to correct your match_text for edit {i}."
                        raise ValueError(json.dumps(error_response, indent=2))
                    normalized = normalized.replace(mt, new_s, 1)
                else:
                    normalized = new_s
            active_proposal_content = normalized
            future_file_path.write_text(active_proposal_content, encoding='utf-8')
        else:
            # --- SINGLE-EDIT CONTINUATION ---
            occurrences = tool.count_occurrences(staged_content, match_text)

            if occurrences != 1:
                error_response = {
                    "error": True,
                    "error_type": "validation_error",
                    "message": f"Contextual patch failed. The provided 'match_text' was found {occurrences} times in the user's last version, but expected exactly 1.",
                }
                line_count = staged_content.count('\n') + 1
                if line_count < 5000:
                    error_response["file_content"] = staged_content
                    error_response["hint"] = f"Session file has {line_count} lines. Content included above — use it to correct your match_text."
                else:
                    error_response["hint"] = f"Session file has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
                raise ValueError(json.dumps(error_response, indent=2))

            active_proposal_content = staged_content.replace(match_text, new_string, 1)
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
                mt = tool.normalize_line_endings(pair['match_text'])
                new_s = pair['new_string']
                if mt:
                    occurrences = tool.count_occurrences(normalized, mt)
                    if occurrences == 0:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: No match found for 'match_text'.",
                        }
                        line_count = original_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = original_content
                            error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your match_text for edit {i}."
                        else:
                            error_response["hint"] = f"File has {line_count} lines (too large to include). Re-read the file to get the current content before retrying."
                        raise ValueError(json.dumps(error_response, indent=2))
                    if occurrences != 1:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: Expected 1 occurrence but found {occurrences}. Provide more context in match_text to ensure uniqueness.",
                        }
                        line_count = original_content.count('\n') + 1
                        if line_count < 5000:
                            error_response["file_content"] = original_content
                            error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your match_text for edit {i}."
                        raise ValueError(json.dumps(error_response, indent=2))
                    normalized = normalized.replace(mt, new_s, 1)
                else:
                    # Empty match_text in a multi-edit means full rewrite (only valid as sole edit)
                    if len(edit_pairs) > 1:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        raise ValueError("Edit with empty match_text (full rewrite) cannot be combined with other edits.")
                    normalized = new_s

            current_file_path.write_text(original_content, encoding='utf-8')
            active_proposal_content = normalized
            future_file_path.write_text(active_proposal_content, encoding='utf-8')
        else:
            # --- SINGLE-EDIT MODE (original behavior) ---
            prep_result = tool._prepare_edit(path, match_text, new_string, expected_replacements)
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
                        error_response["hint"] = f"File has {line_count} lines. Content included above — use it to correct your match_text."
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
