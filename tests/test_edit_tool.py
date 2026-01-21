import pytest
import shutil
import tempfile
from pathlib import Path

from fs_mcp.edit_tool import RooStyleEditTool

# Fixture to set up a temporary directory with a copy of the src code
@pytest.fixture
def temp_src_dir(request):
    """
    Copies the './src' directory into a temporary directory so that
    tests can be run on them without affecting the original files.
    """
    # Create a temporary directory
    temp_dir = Path(tempfile.mkdtemp(prefix="test_fs_mcp_"))
    
    # Path to the original src directory
    src_path = Path(__file__).parent.parent / 'src'
    
    # Path to the destination in the temp directory
    dest_path = temp_dir / 'src'
    
    # Copy the directory
    shutil.copytree(src_path, dest_path)
    
    # Provide the path to the temporary src directory to the tests
    yield dest_path
    
    # Teardown: remove the temporary directory
    shutil.rmtree(temp_dir)

# A mock validation function that works with the temp directory
def create_mock_validator(base_path: Path):
    def validate(path_str: str) -> Path:
        return base_path.parent / path_str
    return validate

@pytest.fixture
def edit_tool(temp_src_dir):
    """
    Returns an instance of RooStyleEditTool configured to work with
    the temporary test directory.
    """
    return RooStyleEditTool(validate_path_func=create_mock_validator(temp_src_dir))


@pytest.mark.parametrize("test_string", [
    "hello world",
    "hello\nworld",
    "hello\\nworld",
    "hello\\\nworld",
    "C:\\Users\\Test",
    "a string with \n and \\n and \\\n mixed",
    "",
    "\\",
    "\n",
    "\\n"
])
def test_sanitize_desanitize_cycle(edit_tool, test_string):
    """
    Tests that sanitizing and then desanitizing a string returns the
    original string.
    """
    sanitized = edit_tool.sanitize_content(test_string)
    desanitized = edit_tool.desanitize_content(sanitized)
    
    if any(c in test_string for c in ['\\', '\n', '\r']):
        assert sanitized != test_string, "Sanitization should have changed the string"
    
    assert desanitized == test_string, "Desanitization should restore the original string"

def test_identity_edit_on_real_file(edit_tool, temp_src_dir):
    """
    Tests that performing an 'identity' edit (replacing a string with itself)
    on a real file results in no changes. This is the core test for the user's concern.
    """
    # We'll use the edit_tool.py file itself for the test
    file_to_test = temp_src_dir / 'fs_mcp' / 'edit_tool.py'
    
    # Read the content of the file
    original_content = file_to_test.read_text(encoding='utf-8')
    
    # Choose a chunk of the file to use as our "old" and "new" string.
    # Let's pick a chunk that contains some interesting characters.
    # The sanitize_content method is a good candidate.
    string_to_replace = "return content.replace('\\\\', '_ROO_PLACEHOLDER_BS_').replace('\\n', '_ROO_PLACEHOLDER_NL_').replace('\\r', '_ROO_PLACEHOLDER_CR_')"
    
    # Ensure the chosen string is actually in the file
    assert string_to_replace in original_content
    
    # Use the edit tool to prepare an identity replacement
    result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        old_string=string_to_replace,
        new_string=string_to_replace,
        expected_replacements=1
    )
    
    # The tool should report no changes are needed
    assert not result.success
    assert result.error_type == "validation_error"
    assert "No changes to apply" in result.message
    
    # Now, let's try a replacement that *should* work, but is still an identity edit
    # by replacing the content with itself after reading it.
    
    # Let's pick a different chunk to be safe
    chunk_to_replace = "def normalize_line_endings(self, content: str) -> str:"
    
    result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        old_string=chunk_to_replace,
        new_string=chunk_to_replace,
        expected_replacements=1
    )
    
    # The tool should again report no changes are needed, because old_string == new_string
    assert not result.success
    assert result.error_type == "validation_error"
    assert "No changes to apply" in result.message
    
    # The ultimate test: does _prepare_edit corrupt the file if we feed it the whole file?
    # This simulates a user providing the full file content to recover.
    full_file_result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        old_string=original_content,
        new_string=original_content,
        expected_replacements=1
    )
    
    # Again, should detect no changes
    assert not full_file_result.success
    assert full_file_result.error_type == "validation_error"
    assert "No changes to apply" in full_file_result.message

