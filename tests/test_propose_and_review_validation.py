"""
Tests for propose_and_review validation logic:
1. Blank match_text on non-blank files should be rejected
2. OVERWRITE_FILE sentinel allows explicit overwrites
3. match_text > 2000 characters should be rejected
"""

import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fs_mcp.edit_tool import propose_and_review_logic


@pytest.fixture
def temp_env():
    """Sets up a temporary directory with a non-blank file."""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_validation_"))
    test_file = temp_dir / "existing_file.py"
    test_file.write_text("def hello():\n    return 'world'\n", encoding='utf-8')

    # Simple validator that just returns the Path
    def validate_path(path_str: str) -> Path:
        return Path(path_str)

    yield {
        "temp_dir": temp_dir,
        "test_file": test_file,
        "validate_path": validate_path
    }

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def empty_file_env():
    """Sets up a temporary directory with an empty file."""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_validation_empty_"))
    test_file = temp_dir / "empty_file.py"
    test_file.write_text("", encoding='utf-8')

    def validate_path(path_str: str) -> Path:
        return Path(path_str)

    yield {
        "temp_dir": temp_dir,
        "test_file": test_file,
        "validate_path": validate_path
    }

    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestBlankMatchTextValidation:
    """Tests for blank match_text on non-blank files."""

    @pytest.mark.asyncio
    async def test_blank_match_text_on_non_blank_file_raises_error(self, temp_env):
        """Blank match_text on a non-blank file should raise ValueError with warning."""
        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="completely new content",
                match_text="",  # Blank - trying to overwrite
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "match_text is empty but file has content" in error_message
        assert "OVERWRITE_FILE" in error_message

    @pytest.mark.asyncio
    async def test_whitespace_match_text_on_non_blank_file_raises_error(self, temp_env):
        """Whitespace-only match_text on a non-blank file should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="completely new content",
                match_text="   ",  # Just whitespace
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "match_text is empty but file has content" in error_message

    @pytest.mark.asyncio
    async def test_blank_match_text_on_empty_file_is_allowed(self, empty_file_env):
        """Blank match_text on an empty file should be allowed (creating new content)."""
        # This should NOT raise an error - we're just checking it doesn't block
        # It will block waiting for user input, so we can't fully test without mocking
        # But we can at least verify the validation passes by checking for a different error
        # or by checking the file was processed correctly

        # For now, we just verify it doesn't raise the overwrite warning
        # The actual file operations would require mocking the user review flow
        pass  # This test demonstrates the intent - see integration tests below

    @pytest.mark.asyncio
    async def test_overwrite_sentinel_allows_overwrite(self, temp_env):
        """Using 'OVERWRITE_FILE' as match_text should allow overwriting."""
        # This won't raise the overwrite warning, but will block on user review
        # We just verify it doesn't raise the specific overwrite error
        # We can't fully run this without mocking the file modification wait
        pass  # See integration test below


class TestMatchTextLengthValidation:
    """Tests for match_text length limit."""

    @pytest.mark.asyncio
    async def test_match_text_over_2000_chars_raises_error(self, temp_env):
        """match_text over 2000 characters should raise ValueError."""
        long_match_text = "x" * 2001  # 2001 characters

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="new content",
                match_text=long_match_text,
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "ERROR: match_text is too long" in error_message
        assert "edits" in error_message.lower()  # Suggests using edits parameter
        assert "bypass_match_text_limit=True" in error_message  # Suggests bypass as last resort

    @pytest.mark.asyncio
    async def test_match_text_exactly_2000_chars_is_allowed(self, temp_env):
        """match_text of exactly 2000 characters should be allowed."""
        # 2000 chars is at the boundary, should not raise the length error
        # It may raise a different error (no match found), but NOT the length error
        match_text_2000 = "x" * 2000

        try:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="new content",
                match_text=match_text_2000,
                expected_replacements=1
            )
        except ValueError as e:
            # It's okay if it fails for a different reason (like no match)
            # But it should NOT be the "too long" error
            assert "ERROR: match_text is too long" not in str(e)

    @pytest.mark.asyncio
    async def test_match_text_under_2000_chars_allowed(self, temp_env):
        """match_text under 2000 characters should be allowed (validation passes)."""
        # This will fail at a later stage (no match found), but not at length validation
        short_match_text = "x" * 100

        try:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="new content",
                match_text=short_match_text,
                expected_replacements=1
            )
        except ValueError as e:
            # Should fail for "no match" not "too long"
            assert "ERROR: match_text is too long" not in str(e)


class TestEditsParameterValidation:
    """Tests for validation with the edits parameter (multi-edit mode)."""

    @pytest.mark.asyncio
    async def test_edits_with_blank_match_text_raises_error(self, temp_env):
        """Blank match_text in edits should raise ValueError with edit index."""
        edits = [
            {"match_text": "", "new_string": "new content"}  # Blank match_text
        ]

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="",
                match_text="",
                edits=edits,
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "Edit 0:" in error_message
        assert "match_text is empty but file has content" in error_message

    @pytest.mark.asyncio
    async def test_edits_with_long_match_text_raises_error(self, temp_env):
        """match_text over 2000 chars in edits should raise ValueError with edit index."""
        edits = [
            {"match_text": "x" * 2001, "new_string": "new content"}
        ]

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="",
                match_text="",
                edits=edits,
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "Edit 0:" in error_message
        assert "ERROR: match_text is too long" in error_message

    @pytest.mark.asyncio
    async def test_multiple_edits_validates_all(self, temp_env):
        """Multiple edits should validate all match_texts."""
        edits = [
            {"match_text": "valid_short", "new_string": "new1"},
            {"match_text": "y" * 2001, "new_string": "new2"}  # This one is too long (over 2000)
        ]

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="",
                match_text="",
                edits=edits,
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        assert "Edit 1:" in error_message  # Second edit (index 1) is the problem
        assert "ERROR: match_text is too long" in error_message


class TestOverwriteSentinel:
    """Tests for the OVERWRITE_FILE sentinel functionality."""

    @pytest.mark.asyncio
    async def test_overwrite_sentinel_bypasses_blank_check(self, temp_env):
        """OVERWRITE_FILE sentinel should bypass the blank match_text check."""
        import asyncio
        # This should NOT raise the overwrite warning
        # It will proceed to file processing and eventually block on user input
        # We use a timeout to ensure we don't hang forever
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="completely new content",
                    match_text="OVERWRITE_FILE",  # Explicit overwrite sentinel
                    expected_replacements=1
                ),
                timeout=2.0  # Short timeout - we just want to verify validation passes
            )
        except asyncio.TimeoutError:
            # Timeout is expected - it means validation passed and we reached the user wait loop
            pass
        except Exception as e:
            # Any other exception should NOT be the overwrite warning
            assert "match_text is empty but file has content" not in str(e)

    @pytest.mark.asyncio
    async def test_overwrite_sentinel_is_not_length_checked(self, temp_env):
        """OVERWRITE_FILE sentinel should not trigger length validation."""
        import asyncio
        # OVERWRITE_FILE is 14 chars, well under 500, so this is more of a sanity check
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="new content",
                    match_text="OVERWRITE_FILE",
                    expected_replacements=1
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            pass  # Expected - validation passed
        except Exception as e:
            assert "ERROR: match_text is too long" not in str(e)


class TestMultiPatchModeWithoutNewString:
    """Tests for multi-patch mode (edits parameter) without requiring new_string."""

    @pytest.mark.asyncio
    async def test_edits_mode_does_not_require_new_string(self, temp_env):
        """Using edits parameter should not require new_string at top level."""
        import asyncio

        # Write a file with content we can match
        temp_env["test_file"].write_text("line1\nline2\nline3\n", encoding='utf-8')

        edits = [
            {"match_text": "line1", "new_string": "LINE1"},
            {"match_text": "line3", "new_string": "LINE3"}
        ]

        # This should NOT raise "new_string is a missing required argument"
        # It will timeout waiting for user input, which is expected behavior
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="",  # Empty string, not missing
                    match_text="",
                    edits=edits,
                    expected_replacements=1
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            # Timeout is expected - validation passed and we reached user wait
            pass
        except ValueError as e:
            # Should not fail with validation error about edits structure
            assert "must have 'match_text' and 'new_string' keys" not in str(e)


class TestBypassMatchTextLimit:
    """Tests for bypass_match_text_limit parameter functionality."""

    @pytest.mark.asyncio
    async def test_long_match_text_rejected_without_bypass(self, temp_env):
        """match_text over 2000 characters should be rejected when bypass is False (default)."""
        long_match_text = "x" * 2001  # 2001 characters

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="new content",
                match_text=long_match_text,
                expected_replacements=1,
                bypass_match_text_limit=False  # Default behavior
            )

        error_message = str(exc_info.value)
        assert "ERROR: match_text is too long" in error_message
        assert "bypass_match_text_limit=True" in error_message

    @pytest.mark.asyncio
    async def test_long_match_text_allowed_with_bypass(self, temp_env):
        """match_text over 2000 characters should be allowed when bypass is True."""
        import asyncio

        # Write a file with content that includes the long match_text
        long_content = "x" * 2500  # 2500 characters
        temp_env["test_file"].write_text(long_content, encoding='utf-8')

        # This should NOT raise the "too long" error because bypass is True
        # It will proceed to validation and timeout waiting for user input
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="replaced content",
                    match_text=long_content,  # Over 2000 chars
                    expected_replacements=1,
                    bypass_match_text_limit=True  # Bypass the limit
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            # Timeout is expected - validation passed and we reached user wait
            pass
        except ValueError as e:
            # Should NOT be the "too long" error
            assert "ERROR: match_text is too long" not in str(e)

    @pytest.mark.asyncio
    async def test_bypass_does_not_affect_under_limit_match_text(self, temp_env):
        """bypass_match_text_limit should have no effect on match_texts under 2000 chars."""
        import asyncio

        short_content = "short content"
        temp_env["test_file"].write_text(short_content, encoding='utf-8')

        # Both should behave the same for short content
        for bypass_value in [True, False]:
            try:
                await asyncio.wait_for(
                    propose_and_review_logic(
                        validate_path=temp_env["validate_path"],
                        IS_VSCODE_CLI_AVAILABLE=False,
                        path=str(temp_env["test_file"]),
                        new_string="new content",
                        match_text=short_content,
                        expected_replacements=1,
                        bypass_match_text_limit=bypass_value
                    ),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                # Timeout is expected - validation passed
                pass
            except ValueError as e:
                # Should not be the "too long" error
                assert "ERROR: match_text is too long" not in str(e)

    @pytest.mark.asyncio
    async def test_bypass_with_edits_parameter(self, temp_env):
        """bypass_match_text_limit should work with the edits parameter."""
        import asyncio

        # Write a file with large content
        long_section = "y" * 2500
        temp_env["test_file"].write_text(f"header\n{long_section}\nfooter\n", encoding='utf-8')

        edits = [
            {"match_text": long_section, "new_string": "replaced section"}
        ]

        # Without bypass, should raise error
        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="",
                match_text="",
                edits=edits,
                expected_replacements=1,
                bypass_match_text_limit=False
            )

        error_message = str(exc_info.value)
        assert "Edit 0:" in error_message
        assert "ERROR: match_text is too long" in error_message

        # With bypass, should proceed past validation
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="",
                    match_text="",
                    edits=edits,
                    expected_replacements=1,
                    bypass_match_text_limit=True  # Bypass the limit
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            # Timeout is expected - validation passed
            pass
        except ValueError as e:
            # Should NOT be the "too long" error
            assert "ERROR: match_text is too long" not in str(e)

    @pytest.mark.asyncio
    async def test_bypass_multiple_edits_all_long(self, temp_env):
        """bypass should allow multiple edits that all exceed the limit."""
        import asyncio

        # Write a file with multiple large sections
        section1 = "a" * 2500
        section2 = "b" * 3000
        temp_env["test_file"].write_text(f"{section1}\nmiddle\n{section2}\n", encoding='utf-8')

        edits = [
            {"match_text": section1, "new_string": "replaced1"},
            {"match_text": section2, "new_string": "replaced2"}
        ]

        # With bypass, should proceed past validation for both edits
        try:
            await asyncio.wait_for(
                propose_and_review_logic(
                    validate_path=temp_env["validate_path"],
                    IS_VSCODE_CLI_AVAILABLE=False,
                    path=str(temp_env["test_file"]),
                    new_string="",
                    match_text="",
                    edits=edits,
                    expected_replacements=1,
                    bypass_match_text_limit=True
                ),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            # Timeout is expected - validation passed for both
            pass
        except ValueError as e:
            # Should NOT be the "too long" error for either edit
            assert "ERROR: match_text is too long" not in str(e)

    @pytest.mark.asyncio
    async def test_error_message_suggests_bypass(self, temp_env):
        """Error message should suggest using bypass_match_text_limit=True."""
        long_match_text = "z" * 2001

        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                validate_path=temp_env["validate_path"],
                IS_VSCODE_CLI_AVAILABLE=False,
                path=str(temp_env["test_file"]),
                new_string="new content",
                match_text=long_match_text,
                expected_replacements=1
            )

        error_message = str(exc_info.value)
        # Should mention both the edits parameter workaround AND the bypass as last resort
        assert "edits" in error_message.lower() or "break" in error_message.lower()
        assert "bypass_match_text_limit=True" in error_message
        assert "LAST RESORT" in error_message
