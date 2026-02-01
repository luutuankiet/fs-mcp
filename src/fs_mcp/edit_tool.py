from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import asyncio
import difflib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

# --- Configuration Constants ---
MATCH_TEXT_MAX_LENGTH = 2000
# Token-efficient error hint threshold - we NEVER dump full file content
# Instead, we provide fuzzy suggestions and file outlines
ERROR_HINT_FUZZY_THRESHOLD = 0.6  # Minimum similarity for fuzzy suggestions
ERROR_HINT_MAX_SUGGESTIONS = 3    # Max fuzzy match suggestions to return
ERROR_HINT_PREVIEW_LENGTH = 200   # Max chars for preview snippets


def find_similar_blocks(match_text: str, file_content: str, cutoff: float = ERROR_HINT_FUZZY_THRESHOLD) -> List[Dict[str, Any]]:
    """
    Find text blocks in file that are similar to match_text using difflib.
    Returns top matches with line numbers and previews for token-efficient hints.
    """
    if not match_text or not file_content:
        return []

    lines = file_content.split('\n')
    match_lines = match_text.split('\n')
    match_len = len(match_lines)

    candidates = []
    for i in range(max(1, len(lines) - match_len + 1)):
        block = '\n'.join(lines[i:i + match_len])
        ratio = difflib.SequenceMatcher(None, match_text, block).ratio()
        if ratio >= cutoff:
            preview = block[:ERROR_HINT_PREVIEW_LENGTH]
            if len(block) > ERROR_HINT_PREVIEW_LENGTH:
                preview += '...'
            candidates.append({
                'line_start': i + 1,
                'line_end': i + match_len,
                'similarity': round(ratio * 100),  # Percentage for readability
                'preview': preview
            })

    # Return top matches sorted by similarity
    return sorted(candidates, key=lambda x: x['similarity'], reverse=True)[:ERROR_HINT_MAX_SUGGESTIONS]


def extract_file_outline(content: str, file_path: str = "") -> List[Dict[str, Any]]:
    """
    Extract structural outline of a file (classes, functions, methods).
    Uses regex patterns that work across common languages.
    Returns symbols with line numbers for navigation hints.
    """
    if not content:
        return []

    lines = content.split('\n')
    outline = []

    # Determine language from extension
    suffix = Path(file_path).suffix.lower() if file_path else ""

    # Language-specific patterns
    patterns = []
    if suffix in ('.py', ''):
        patterns = [
            (r'^class\s+(\w+)', 'class'),
            (r'^async\s+def\s+(\w+)', 'async function'),
            (r'^def\s+(\w+)', 'function'),
            (r'^(\s+)async\s+def\s+(\w+)', 'async method'),
            (r'^(\s+)def\s+(\w+)', 'method'),
        ]
    elif suffix in ('.js', '.ts', '.jsx', '.tsx', '.mjs'):
        patterns = [
            (r'^class\s+(\w+)', 'class'),
            (r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)', 'function'),
            (r'^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(', 'arrow function'),
            (r'^\s+(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{', 'method'),
        ]
    elif suffix in ('.go',):
        patterns = [
            (r'^func\s+(\w+)', 'function'),
            (r'^func\s+\([^)]+\)\s+(\w+)', 'method'),
            (r'^type\s+(\w+)\s+struct', 'struct'),
            (r'^type\s+(\w+)\s+interface', 'interface'),
        ]
    elif suffix in ('.rs',):
        patterns = [
            (r'^(?:pub\s+)?fn\s+(\w+)', 'function'),
            (r'^(?:pub\s+)?struct\s+(\w+)', 'struct'),
            (r'^(?:pub\s+)?impl\s+(\w+)', 'impl'),
            (r'^(?:pub\s+)?trait\s+(\w+)', 'trait'),
        ]
    elif suffix in ('.java', '.kt', '.scala'):
        patterns = [
            (r'^(?:public|private|protected)?\s*class\s+(\w+)', 'class'),
            (r'^(?:public|private|protected)?\s*interface\s+(\w+)', 'interface'),
            (r'^\s+(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)?(\w+)\s*\(', 'method'),
        ]
    else:
        # Generic fallback patterns
        patterns = [
            (r'^class\s+(\w+)', 'class'),
            (r'^(?:def|function|func)\s+(\w+)', 'function'),
            (r'^\s+(?:def|function)\s+(\w+)', 'method'),
        ]

    for i, line in enumerate(lines, 1):
        for pattern, symbol_type in patterns:
            match = re.match(pattern, line)
            if match:
                name = match.group(1) if match.lastindex else match.group(0)
                # For methods, extract actual name (might be in group 2)
                if symbol_type == 'method' and match.lastindex and match.lastindex >= 2:
                    name = match.group(2)
                signature = line.strip()[:100]  # Truncate long signatures
                outline.append({
                    'type': symbol_type,
                    'name': name,
                    'line': i,
                    'signature': signature
                })
                if len(outline) >= 500:  # Cap the number of symbols
                    return outline
                break  # Only match one pattern per line

    return outline


def _extract_grep_keywords(match_text: str) -> List[str]:
    """Extract distinctive keywords from match_text for grep suggestions."""
    # Look for function/class names, distinctive identifiers
    keywords = []

    # Function/method names
    func_match = re.search(r'(?:def|function|func|fn)\s+(\w+)', match_text)
    if func_match:
        keywords.append(func_match.group(1))

    # Class names
    class_match = re.search(r'class\s+(\w+)', match_text)
    if class_match:
        keywords.append(class_match.group(1))

    # Variable assignments with distinctive names
    var_matches = re.findall(r'(\w{4,})\s*[=:]', match_text)
    keywords.extend(var_matches[:2])

    # String literals (useful for error messages, etc.)
    string_matches = re.findall(r'["\']([^"\']{10,40})["\']', match_text)
    keywords.extend(string_matches[:1])

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique.append(kw)

    return unique[:3]  # Return top 3 keywords


def generate_token_efficient_hint(
    match_text: str,
    file_content: str,
    file_path: str,
    error_context: str = ""
) -> Dict[str, Any]:
    """
    Generate token-efficient error hints instead of dumping full file content.

    Returns a dict with:
    - 'hint': Human-readable guidance message
    - 'suggestions': Fuzzy match suggestions with line numbers (if found)
    - 'outline': File structure outline (if no good fuzzy matches)
    - 'line_count': Total lines in file
    - 'recovery_steps': Concrete steps to recover from error
    """
    line_count = file_content.count('\n') + 1
    result = {'line_count': line_count}

    # Strategy 1: Find fuzzy matches
    suggestions = find_similar_blocks(match_text, file_content)

    if suggestions:
        best_match = suggestions[0]
        result['suggestions'] = suggestions
        # Add warning about preview limitations (per intern test feedback)
        result['preview_warning'] = "Previews may hide whitespace differences (tabs/spaces/line endings). Always verify with read_files."

        if best_match['similarity'] >= 90:
            result['hint'] = (
                f"Found very similar text ({best_match['similarity']}% character match) at lines {best_match['line_start']}-{best_match['line_end']}. "
                f"Likely a whitespace or minor difference.{error_context}"
            )
            result['recovery_steps'] = [
                f"1. Call read_files with path='{file_path}', start_line={best_match['line_start']}, end_line={best_match['line_end']}",
                "2. Compare output character-by-character with your match_text (check tabs vs spaces, trailing whitespace)",
                "3. Copy the EXACT text from read_files output as your new match_text",
                "4. Retry propose_and_review with corrected match_text"
            ]
        else:
            result['hint'] = (
                f"Found {len(suggestions)} similar block(s). Best: {best_match['similarity']}% at lines {best_match['line_start']}-{best_match['line_end']}.{error_context}"
            )
            result['recovery_steps'] = [
                f"1. Call read_files with path='{file_path}', start_line={best_match['line_start']}, end_line={best_match['line_end']}",
                "2. Verify this is the correct code section you intended to edit",
                "3. Copy the EXACT text from read_files output as your new match_text",
                "4. Retry propose_and_review with corrected match_text"
            ]
    else:
        # Strategy 2: Provide file outline when no fuzzy matches found
        outline = extract_file_outline(file_content, file_path)
        grep_keywords = _extract_grep_keywords(match_text)

        if outline:
            result['outline'] = outline
            if grep_keywords:
                result['suggested_grep_keywords'] = grep_keywords
                result['hint'] = (
                    f"No similar text found in {line_count}-line file. "
                    f"Try grep_content with keywords: {', '.join(repr(k) for k in grep_keywords)}.{error_context}"
                )
                result['recovery_steps'] = [
                    f"1. Call grep_content with pattern='{grep_keywords[0]}' to locate the code",
                    "2. Note the line numbers from grep results",
                    f"3. Call read_files with path='{file_path}' and the line range from grep",
                    "4. Copy the EXACT text and retry propose_and_review"
                ]
            else:
                result['hint'] = (
                    f"No similar text found in {line_count}-line file. File structure shown in 'outline'. "
                    f"Use grep_content to locate the target code.{error_context}"
                )
                result['recovery_steps'] = [
                    "1. Review the 'outline' to identify which function/class contains your target",
                    "2. Call grep_content with a distinctive keyword from your match_text",
                    f"3. Call read_files with path='{file_path}' and the line range",
                    "4. Copy the EXACT text and retry propose_and_review"
                ]
        else:
            result['hint'] = (
                f"No match found in {line_count}-line file. The match_text may be outdated or from a different file.{error_context}"
            )
            if grep_keywords:
                result['suggested_grep_keywords'] = grep_keywords
            result['recovery_steps'] = [
                "1. Verify you're editing the correct file path",
                f"2. Call grep_content to search for keywords from your match_text",
                "3. Call read_files to get the current content",
                "4. Update match_text to reflect current file state"
            ]

    return result


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
                    hint_info = generate_token_efficient_hint(mt, content, path, f" (edit {i})")
                    error_response.update(hint_info)
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
                        hint_info = generate_token_efficient_hint(match_text, content, path)
                        error_response.update(hint_info)
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
                        hint_info = generate_token_efficient_hint(mt, staged_content, path, f" (session edit {i})")
                        error_response.update(hint_info)
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
                hint_info = generate_token_efficient_hint(match_text, staged_content, path, " (session)")
                error_response.update(hint_info)
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
                        hint_info = generate_token_efficient_hint(mt, original_content, path, f" (edit {i})")
                        error_response.update(hint_info)
                        raise ValueError(json.dumps(error_response, indent=2))
                    if occurrences != 1:
                        if temp_dir.exists(): shutil.rmtree(temp_dir)
                        error_response = {
                            "error": True,
                            "error_type": "validation_error",
                            "message": f"Edit {i}: Expected 1 occurrence but found {occurrences}. Provide more context in match_text to ensure uniqueness.",
                        }
                        hint_info = generate_token_efficient_hint(mt, original_content, path, f" (edit {i})")
                        error_response.update(hint_info)
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
                    hint_info = generate_token_efficient_hint(match_text, content, path)
                    error_response.update(hint_info)
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
