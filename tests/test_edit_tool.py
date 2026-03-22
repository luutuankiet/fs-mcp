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

from fs_mcp.edit_tool import _try_fuzzy_recover, _apply_edits_to_content


# --- Unicode Confusable Recovery Tests ---

class TestFuzzyRecover:
    """Tests for _try_fuzzy_recover: auto-recovery from Unicode confusables."""

    def test_curly_quote_recovery(self):
        """LLM sends curly quote, file has straight quote -> should recover."""
        file_content = "The key UX element -- it's what teaches agents the workflow.\n"
        # LLM produces curly right single quotation mark (U+2019)
        match_text = "The key UX element -- it\u2019s what teaches agents the workflow."
        result = _try_fuzzy_recover(match_text, file_content)
        assert result is not None
        assert "it's" in result  # straight quote
        assert result in file_content  # must be exact file text

    def test_smart_double_quotes_recovery(self):
        """LLM sends smart double quotes, file has straight -> should recover."""
        file_content = "She said \"hello world\" to everyone.\n"
        # LLM produces left/right double quotation marks (U+201C, U+201D)
        match_text = "She said \u201chello world\u201d to everyone."
        result = _try_fuzzy_recover(match_text, file_content)
        assert result is not None
        assert result in file_content

    def test_no_recovery_when_genuinely_different(self):
        """When text is genuinely different, should NOT recover."""
        file_content = "def calculate_total(items):\n    return sum(items)\n"
        match_text = "def compute_sum(entries):\n    return sum(entries)"
        result = _try_fuzzy_recover(match_text, file_content)
        assert result is None

    def test_ellipsis_recovery(self):
        """LLM sends Unicode ellipsis, file has three dots -> should recover."""
        file_content = "Loading... please wait\n"
        match_text = "Loading\u2026 please wait"
        result = _try_fuzzy_recover(match_text, file_content)
        assert result is not None
        assert result in file_content


class TestFuzzyRecoverIntegration:
    """Integration tests: fuzzy recovery through the full edit pipeline."""

    def test_edit_succeeds_with_curly_quotes(self, edit_tool, temp_src_dir):
        """Full edit_files pipeline should auto-recover from curly quotes."""
        test_file = temp_src_dir / 'fs_mcp' / 'test_unicode.py'
        test_file.write_text("# it's a test file\nx = 1\n", encoding='utf-8')

        # Simulate LLM sending curly quote in match_text
        result = edit_tool._prepare_edit(
            file_path=str(test_file),
            match_text="# it\u2019s a test file",
            new_string="# it is a test file",
            expected_replacements=1
        )
        assert result.success
        assert "# it is a test file" in result.new_content

    def test_batch_edit_succeeds_with_curly_quotes(self, edit_tool, temp_src_dir):
        """Batch edits via _apply_edits_to_content should also auto-recover."""
        content = "# it's a test\ndef foo():\n    pass\n"

        result = _apply_edits_to_content(
            tool=edit_tool,
            content=content,
            edit_pairs=[{
                'match_text': "# it\u2019s a test",
                'new_string': "# it is a test"
            }],
            path="test.py"
        )
        assert "# it is a test" in result
        assert "def foo():" in result  # rest preserved
