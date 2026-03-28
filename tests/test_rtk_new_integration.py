"""
Tests for new RTK integration features:
1. _rtk_compress_content with -l minimal flag and file path language detection
2. _rtk_rewrite_command for smart run_command compression
3. _rtk_auto_update for keeping RTK current
4. run_command integration with rtk rewrite
5. IS_RTK_AVAILABLE guard checks
"""
import pytest
import subprocess
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from fs_mcp import server


@pytest.fixture
def temp_env(tmp_path):
    """Sets up a safe temporary directory environment for testing."""
    server.initialize([str(tmp_path)], use_all_tools=True)
    return tmp_path


@pytest.fixture
def sample_python_file(temp_env):
    """Create a sample Python file for testing."""
    content = '''"""Module docstring."""

def calculate_total(items):
    """Calculate the total price of items."""
    # Sum all item prices
    total = 0
    for item in items:
        total += item.price  # Add each price
    return total
'''
    file_path = temp_env / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def sample_js_file(temp_env):
    """Create a sample JavaScript file for testing."""
    content = '''// Main entry point
const express = require("express");

/* Multi-line comment
   that should be stripped */
function startServer(port) {
    // Start listening
    const app = express();
    app.listen(port);
    return app;
}
'''
    file_path = temp_env / "app.js"
    file_path.write_text(content)
    return file_path


class TestRTKCompressContentMinimalFlag:
    """Tests that _rtk_compress_content passes -l minimal flag."""

    def test_stdin_mode_passes_minimal_flag(self):
        """When file_path is '-', should use stdin with -l minimal."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="compressed")
            server.IS_RTK_AVAILABLE = True

            content, warning = server._rtk_compress_content("original", "-")

            assert content == "compressed"
            assert warning is None
            # Verify -l minimal was passed
            cmd = mock_run.call_args[0][0]
            assert cmd[0].endswith("rtk")
            assert cmd[1:] == ["read", "-", "-l", "minimal"]
            # Verify content was piped via stdin
            assert mock_run.call_args[1].get("input") == "original"

    def test_file_path_mode_reads_directly(self, sample_python_file):
        """When a real file path is given, RTK should read the file directly."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="compressed")
            server.IS_RTK_AVAILABLE = True

            content, warning = server._rtk_compress_content(
                "ignored content",
                str(sample_python_file)
            )

            assert content == "compressed"
            cmd = mock_run.call_args[0][0]
            # Should pass file path directly (not stdin)
            assert cmd[0].endswith("rtk")
            assert cmd[1:] == ["read", str(sample_python_file), "-l", "minimal"]
            # Should NOT pipe via stdin
            assert mock_run.call_args[1].get("input") is None

    def test_nonexistent_file_falls_back_to_stdin(self):
        """When file path doesn't exist, should fall back to stdin mode."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="compressed")
            server.IS_RTK_AVAILABLE = True

            content, warning = server._rtk_compress_content(
                "original", "/nonexistent/file.py"
            )

            cmd = mock_run.call_args[0][0]
            assert cmd[0].endswith("rtk")
            assert cmd[1:] == ["read", "-", "-l", "minimal"]
            assert mock_run.call_args[1].get("input") == "original"

    def test_skips_when_rtk_unavailable(self):
        """When IS_RTK_AVAILABLE is False, should return content unchanged."""
        with patch('subprocess.run') as mock_run:
            server.IS_RTK_AVAILABLE = False

            content, warning = server._rtk_compress_content("original")

            mock_run.assert_not_called()
            assert content == "original"
            assert warning is None


class TestRTKRewriteCommand:
    """Tests for _rtk_rewrite_command."""

    def test_rewrite_supported_command(self):
        """RTK should rewrite supported commands."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="rtk git status"
            )
            server.IS_RTK_AVAILABLE = True

            result = server._rtk_rewrite_command("git status")

            assert result == "rtk git status"
            cmd = mock_run.call_args[0][0]
            assert cmd[0].endswith("rtk")
            assert cmd[1:] == ["rewrite", "git status"]

    def test_rewrite_unsupported_command(self):
        """RTK should return None for unsupported commands."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            server.IS_RTK_AVAILABLE = True

            result = server._rtk_rewrite_command("echo hello")

            assert result is None

    def test_rewrite_timeout(self):
        """Should return None on timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="rtk", timeout=5)
            server.IS_RTK_AVAILABLE = True

            result = server._rtk_rewrite_command("git status")

            assert result is None

    def test_rewrite_skips_when_unavailable(self):
        """Should skip when RTK is not available."""
        with patch('subprocess.run') as mock_run:
            server.IS_RTK_AVAILABLE = False

            result = server._rtk_rewrite_command("git status")

            mock_run.assert_not_called()
            assert result is None

    def test_rewrite_empty_output(self):
        """Should return None if RTK returns empty stdout."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            server.IS_RTK_AVAILABLE = True

            result = server._rtk_rewrite_command("git status")

            assert result is None


class TestRTKAutoUpdate:
    """Tests for _rtk_auto_update."""

    def test_auto_update_installs_newer_version(self):
        """Should detect and report version change."""
        with patch('subprocess.run') as mock_run, \
             patch.object(server, '_resolve_rtk_path', return_value="/home/ubuntu/.local/bin/rtk"):
            # Sequence: current version, install, new version
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="rtk 0.28.0"),  # current
                MagicMock(returncode=0, stdout="installed"),     # install
                MagicMock(returncode=0, stdout="rtk 0.29.0"),  # new
            ]
            server._rtk_last_update_check = None
            server._RTK_PATH = "/home/ubuntu/.local/bin/rtk"
            server._RTK_MANAGED = True

            result = server._rtk_auto_update()

            assert "updated" in result.lower() or "->" in result
            assert "0.28.0" in result
            assert "0.29.0" in result

    def test_auto_update_skips_when_recent(self):
        """Should skip if checked recently."""
        server._rtk_last_update_check = time.time()  # Just checked

        with patch('subprocess.run') as mock_run:
            result = server._rtk_auto_update()

            mock_run.assert_not_called()
            assert result is None

    def test_auto_update_already_latest(self):
        """Should return None if already at latest version."""
        with patch('subprocess.run') as mock_run, \
             patch.object(server, '_resolve_rtk_path', return_value="/home/ubuntu/.local/bin/rtk"):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="rtk 0.29.0"),  # current
                MagicMock(returncode=0, stdout="installed"),     # install
                MagicMock(returncode=0, stdout="rtk 0.29.0"),  # same
            ]
            server._rtk_last_update_check = None
            server._RTK_PATH = "/home/ubuntu/.local/bin/rtk"
            server._RTK_MANAGED = True

            result = server._rtk_auto_update()

            assert result is None  # No change

    def test_auto_update_handles_failure(self):
        """Should handle install failure gracefully."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="rtk 0.29.0"),  # current
                MagicMock(returncode=1, stdout="", stderr="error"),  # install fails
            ]
            server._rtk_last_update_check = None
            server._RTK_PATH = "/home/ubuntu/.local/bin/rtk"
            server._RTK_MANAGED = True

            result = server._rtk_auto_update()

            assert result is not None
            assert "skipped" in result.lower() or "failed" in result.lower()


class TestRunCommandRTKRewrite:
    """Tests for run_command integration with rtk rewrite."""

    @pytest.mark.asyncio
    async def test_run_command_uses_rtk_rewrite_when_compact(self, temp_env):
        """compact=True should try rtk rewrite before running."""
        with patch.object(server, '_rtk_rewrite_command') as mock_rewrite, \
             patch('subprocess.run') as mock_run:

            mock_rewrite.return_value = "rtk git status"
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="## main...origin/main\n",
                stderr=""
            )

            result = await server.run_command.fn(
                command="git status",
                working_dir=str(temp_env),
                compact=True
            )

            mock_rewrite.assert_called_once_with("git status")
            # The actual subprocess should run the rewritten command
            run_call = mock_run.call_args
            assert run_call[0][0] == "rtk git status"

    @pytest.mark.asyncio
    async def test_run_command_falls_back_for_unsupported(self, temp_env):
        """When rtk rewrite returns None, should run original + post-process."""
        with patch.object(server, '_rtk_rewrite_command') as mock_rewrite, \
             patch.object(server, '_rtk_compress_content') as mock_compress, \
             patch('subprocess.run') as mock_run:

            mock_rewrite.return_value = None  # No RTK equivalent
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="hello world\n",
                stderr=""
            )
            mock_compress.return_value = ("hello world\n", None)

            result = await server.run_command.fn(
                command="echo hello",
                working_dir=str(temp_env),
                compact=True
            )

            mock_rewrite.assert_called_once_with("echo hello")
            # Original command should be executed
            run_call = mock_run.call_args
            assert run_call[0][0] == "echo hello"
            # Should fall back to rtk compress
            mock_compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_command_skips_rtk_when_compact_false(self, temp_env):
        """compact=False should skip RTK entirely."""
        with patch.object(server, '_rtk_rewrite_command') as mock_rewrite, \
             patch.object(server, '_rtk_compress_content') as mock_compress, \
             patch('subprocess.run') as mock_run:

            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="raw output\n",
                stderr=""
            )

            result = await server.run_command.fn(
                command="git status",
                working_dir=str(temp_env),
                compact=False
            )

            mock_rewrite.assert_not_called()
            mock_compress.assert_not_called()
            assert "raw output" in result


class TestISRTKAvailableGuard:
    """Tests that IS_RTK_AVAILABLE is checked before subprocess calls."""

    def test_compress_content_no_subprocess_when_unavailable(self):
        """_rtk_compress_content should not spawn subprocess when RTK unavailable."""
        server.IS_RTK_AVAILABLE = False
        with patch('subprocess.run') as mock_run:
            content, warning = server._rtk_compress_content("test content")
            mock_run.assert_not_called()
            assert content == "test content"

    def test_rewrite_command_no_subprocess_when_unavailable(self):
        """_rtk_rewrite_command should not spawn subprocess when RTK unavailable."""
        server.IS_RTK_AVAILABLE = False
        with patch('subprocess.run') as mock_run:
            result = server._rtk_rewrite_command("git status")
            mock_run.assert_not_called()
            assert result is None
