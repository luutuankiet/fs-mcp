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


def test_identity_edit_on_real_file(edit_tool, temp_src_dir):
    """
    Tests that performing an 'identity' edit (replacing a string with itself)
    on a real file results in no changes.
    """
    file_to_test = temp_src_dir / 'fs_mcp' / 'edit_tool.py'
    original_content = file_to_test.read_text(encoding='utf-8')

    chunk_to_replace = "def normalize_line_endings(self, content: str) -> str:"

    result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        match_text=chunk_to_replace,
        new_string=chunk_to_replace,
        expected_replacements=1
    )

    assert not result.success
    assert result.error_type == "validation_error"
    assert "No changes to apply" in result.message

    # Full file identity edit should also detect no changes
    full_file_result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        match_text=original_content,
        new_string=original_content,
        expected_replacements=1
    )

    assert not full_file_result.success
    assert result.error_type == "validation_error"


def test_edit_preserves_literal_escape_sequences(edit_tool, temp_src_dir):
    """
    Tests that editing a file containing literal \\n sequences preserves them
    correctly without any corruption.
    """
    file_to_test = temp_src_dir / 'fs_mcp' / 'test_escapes.py'
    original_content = 'line1\nprint("Hello\\nWorld")\nline3\n'
    file_to_test.write_text(original_content, encoding='utf-8')

    # Replace the print line, keeping the literal \n intact
    result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        match_text='print("Hello\\nWorld")',
        new_string='print("Hi\\nUniverse")',
        expected_replacements=1
    )

    assert result.success
    assert result.new_content == 'line1\nprint("Hi\\nUniverse")\nline3\n'

    # Write it back and verify
    file_to_test.write_text(result.new_content, encoding='utf-8')
    roundtripped = file_to_test.read_text(encoding='utf-8')
    assert roundtripped == 'line1\nprint("Hi\\nUniverse")\nline3\n'

