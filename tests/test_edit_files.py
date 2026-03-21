"""
Tests for edit_files tool and apply_file_edits logic:
1. Single-file single-edit
2. Single-file batch edits
3. Multi-file edits
4. Sentinel modes (create, overwrite, append)
5. Error cases (no match, multiple matches, file not found)
6. Per-file independence (file 1 succeeds, file 2 fails)
"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fs_mcp.edit_tool import apply_file_edits


@pytest.fixture
def temp_env():
    """Sets up a temporary directory with test files."""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_edit_files_"))

    file_a = temp_dir / "a.py"
    file_a.write_text("def hello():\n    return 'world'\n", encoding='utf-8')

    file_b = temp_dir / "b.py"
    file_b.write_text("x = 1\ny = 2\nz = 3\n", encoding='utf-8')

    def validate_path(path_str: str) -> Path:
        return Path(path_str)

    yield {
        "temp_dir": temp_dir,
        "file_a": file_a,
        "file_b": file_b,
        "validate_path": validate_path,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


class TestSingleFileEdit:
    """Basic single-file, single-edit operations."""

    def test_simple_replace(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "return 'world'", "new_string": "return 'hello'"}],
        )
        assert result["status"] == "ok"
        assert result["edits_applied"] == 1
        content = temp_env["file_a"].read_text()
        assert "return 'hello'" in content
        assert "return 'world'" not in content

    def test_batch_edits_same_file(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_b"]),
            [
                {"match_text": "x = 1", "new_string": "x = 10"},
                {"match_text": "y = 2", "new_string": "y = 20"},
            ],
        )
        assert result["status"] == "ok"
        assert result["edits_applied"] == 2
        content = temp_env["file_b"].read_text()
        assert "x = 10" in content
        assert "y = 20" in content
        assert "z = 3" in content


class TestSentinelModes:
    """Tests for special match_text sentinel values."""

    def test_create_new_file(self, temp_env):
        new_file = temp_env["temp_dir"] / "new.py"
        result = apply_file_edits(
            temp_env["validate_path"],
            str(new_file),
            [{"match_text": "", "new_string": "print('hello')"}],
        )
        assert result["status"] == "created"
        assert new_file.exists()
        assert new_file.read_text() == "print('hello')"

    def test_overwrite_file(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "OVERWRITE_FILE", "new_string": "completely new content"}],
        )
        assert result["status"] == "ok"
        content = temp_env["file_a"].read_text()
        # Original file had trailing \n, so newline preservation adds one
        assert content.strip() == "completely new content"

    def test_append_to_file(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_b"]),
            [{"match_text": "APPEND_TO_FILE", "new_string": "\nw = 4\n"}],
        )
        assert result["status"] == "ok"
        content = temp_env["file_b"].read_text()
        assert "w = 4" in content
        assert "x = 1" in content  # original content preserved


class TestErrorCases:
    """Tests for error handling."""

    def test_no_match_returns_error(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "nonexistent text", "new_string": "replacement"}],
        )
        assert result["status"] == "error"
        assert "No match found" in result.get("message", result.get("error", ""))

    def test_multiple_matches_returns_error(self, temp_env):
        # Create a file with duplicate text
        dup_file = temp_env["temp_dir"] / "dup.py"
        dup_file.write_text("a = 1\na = 1\n", encoding='utf-8')
        result = apply_file_edits(
            temp_env["validate_path"],
            str(dup_file),
            [{"match_text": "a = 1", "new_string": "a = 2"}],
        )
        assert result["status"] == "error"
        assert "Expected 1 occurrence but found 2" in result.get("message", result.get("error", ""))

    def test_file_not_found(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["temp_dir"] / "nonexistent.py"),
            [{"match_text": "something", "new_string": "else"}],
        )
        assert result["status"] == "error"
        assert "not found" in result.get("error", "").lower() or "not found" in result.get("message", "").lower()

    def test_blank_match_on_existing_file_rejected(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "", "new_string": "overwrite attempt"}],
        )
        assert result["status"] == "error"
        assert "match_text is empty but file has content" in result.get("error", "")

    def test_empty_edits_list(self, temp_env):
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [],
        )
        assert result["status"] == "error"

    def test_match_text_too_long(self, temp_env):
        long_text = "a" * 2001
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": long_text, "new_string": "short"}],
        )
        assert result["status"] == "error"
        assert "too long" in result.get("error", "").lower()

    def test_fuzzy_hints_on_near_match(self, temp_env):
        """When match_text is close but not exact, error should include suggestions."""
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "def hello():\n    return 'worl'", "new_string": "new"}],
        )
        assert result["status"] == "error"
        # Should have suggestions from fuzzy matching
        assert "suggestions" in result or "hint" in result


class TestSafetyChecks:
    """Tests for safety features: binary detection, size limits, atomic writes, newline preservation."""

    def test_binary_file_rejected(self, temp_env):
        """Binary files should be rejected with clear error."""
        bin_file = temp_env["temp_dir"] / "image.png"
        bin_file.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
        result = apply_file_edits(
            temp_env["validate_path"],
            str(bin_file),
            [{"match_text": "PNG", "new_string": "JPG"}],
        )
        assert result["status"] == "error"
        assert "binary" in result["error"].lower()

    def test_noop_edit_detected(self, temp_env):
        """Replacing text with itself should be detected as no-op."""
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "return 'world'", "new_string": "return 'world'"}],
        )
        assert result["status"] == "ok"
        assert result["edits_applied"] == 0

    def test_new_string_too_large(self, temp_env):
        """new_string exceeding 5MB should be rejected."""
        from fs_mcp.edit_tool import NEW_STRING_MAX_LENGTH
        huge = "x" * (NEW_STRING_MAX_LENGTH + 1)
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "return 'world'", "new_string": huge}],
        )
        assert result["status"] == "error"
        assert "too large" in result["error"].lower()

    def test_trailing_newline_preserved(self, temp_env):
        """Files ending with newline should keep that newline after edit."""
        # file_a ends with \n
        original = temp_env["file_a"].read_text()
        assert original.endswith('\n')
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_a"]),
            [{"match_text": "return 'world'", "new_string": "return 'hello'"}],
        )
        assert result["status"] == "ok"
        edited = temp_env["file_a"].read_text()
        assert edited.endswith('\n'), "Trailing newline should be preserved"

    def test_no_trailing_newline_preserved(self, temp_env):
        """Files without trailing newline should stay that way after edit."""
        no_nl_file = temp_env["temp_dir"] / "no_nl.py"
        no_nl_file.write_text("x = 1", encoding='utf-8')  # no trailing \n
        result = apply_file_edits(
            temp_env["validate_path"],
            str(no_nl_file),
            [{"match_text": "x = 1", "new_string": "x = 2"}],
        )
        assert result["status"] == "ok"
        edited = no_nl_file.read_text()
        assert not edited.endswith('\n'), "Should not add trailing newline"

    


class TestPerFileAtomicity:
    """Tests that edits are atomic per file but independent across files."""

    def test_second_edit_fails_first_not_written(self, temp_env):
        """If edit 2 of 2 fails on a file, edit 1 should NOT be written."""
        original = temp_env["file_b"].read_text()
        result = apply_file_edits(
            temp_env["validate_path"],
            str(temp_env["file_b"]),
            [
                {"match_text": "x = 1", "new_string": "x = 10"},
                {"match_text": "nonexistent", "new_string": "fail"},
            ],
        )
        assert result["status"] == "error"
        # File should be unchanged because the whole batch failed
        # Note: _apply_edits_to_content raises before writing
        content = temp_env["file_b"].read_text()
        assert content == original


class TestCreateFileSubdirectory:
    """Test creating files in subdirectories."""

    def test_create_file_in_new_subdir(self, temp_env):
        new_file = temp_env["temp_dir"] / "sub" / "dir" / "new.py"
        result = apply_file_edits(
            temp_env["validate_path"],
            str(new_file),
            [{"match_text": "", "new_string": "# new file\n"}],
        )
        assert result["status"] == "created"
        assert new_file.exists()
        assert new_file.read_text() == "# new file\n"
