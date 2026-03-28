"""
Tests for RTK (Rust Token Killer) integration in fs-mcp.

These tests verify:
1. RTK binary check at startup
2. read_files compact parameter behavior
3. grep_content compact parameter behavior
4. Graceful fallback when RTK fails
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from fs_mcp import server
from fs_mcp.utils import check_rtk


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


def calculate_tax(amount, rate=0.1):
    """Calculate tax on an amount."""
    # Apply tax rate
    return amount * rate


class ShoppingCart:
    """A shopping cart class."""
    
    def __init__(self):
        # Initialize empty items list
        self.items = []
    
    def add_item(self, item):
        """Add an item to the cart."""
        self.items.append(item)
'''
    file_path = temp_env / "sample.py"
    file_path.write_text(content)
    return file_path


class TestRTKBinaryCheck:
    """Tests for RTK binary availability check."""

    def test_check_rtk_installed(self):
        """Test check_rtk when RTK is installed."""
        with patch('shutil.which', return_value='/usr/local/bin/rtk'):
            available, msg = check_rtk()
            assert available is True
            assert "installed" in msg.lower()

    def test_check_rtk_not_installed(self):
        """Test check_rtk when RTK is not installed."""
        with patch('shutil.which', return_value=None):
            available, msg = check_rtk()
            assert available is False
            assert "install" in msg.lower()


class TestReadFilesCompact:
    """Tests for read_files compact parameter."""

    def test_read_files_compact_true_calls_rtk(self, sample_python_file, temp_env):
        """Test that compact=True (default) calls RTK."""
        with patch.object(server, '_rtk_compress_content') as mock_rtk:
            mock_rtk.return_value = ("compressed content", None)
            
            result = server.read_files.fn(
                files=[{"path": str(sample_python_file)}],
                compact=True
            )
            
            mock_rtk.assert_called_once()
            assert "compressed content" in result

    def test_read_files_compact_false_skips_rtk(self, sample_python_file, temp_env):
        """Test that compact=False returns verbatim content."""
        with patch.object(server, '_rtk_compress_content') as mock_rtk:
            result = server.read_files.fn(
                files=[{"path": str(sample_python_file)}],
                compact=False
            )
            
            mock_rtk.assert_not_called()
            # Should contain original content including comments
            assert "# Sum all item prices" in result
            assert "Module docstring" in result

    def test_read_files_default_is_compact(self, sample_python_file, temp_env):
        """Test that default behavior is compact=True."""
        with patch.object(server, '_rtk_compress_content') as mock_rtk:
            mock_rtk.return_value = ("compressed", None)
            
            # Call without explicit compact parameter
            result = server.read_files.fn(
                files=[{"path": str(sample_python_file)}]
            )
            
            mock_rtk.assert_called_once()

    def test_read_files_rtk_failure_fallback(self, sample_python_file, temp_env):
        """Test graceful fallback when RTK fails."""
        with patch.object(server, '_rtk_compress_content') as mock_rtk:
            original_content = sample_python_file.read_text()
            mock_rtk.return_value = (original_content, "[RTK compression failed]")
            
            result = server.read_files.fn(
                files=[{"path": str(sample_python_file)}],
                compact=True
            )
            
            # Should contain warning and original content
            assert "[RTK compression failed]" in result
            assert "def calculate_total" in result


class TestGrepContentCompact:
    """Tests for grep_content compact parameter."""

    def test_grep_content_compact_true_calls_rtk(self, sample_python_file, temp_env):
        """Test that compact=True (default) calls RTK grep."""
        with patch.object(server, '_rtk_grep') as mock_rtk:
            mock_rtk.return_value = ("🔍 2 in 1F:\n\n📄 sample.py (2):", None)
            
            result = server.grep_content.fn(
                pattern="calculate",
                search_path=str(temp_env),
                compact=True
            )
            
            mock_rtk.assert_called_once()
            assert "🔍" in result or "sample.py" in result

    def test_grep_content_compact_false_uses_ripgrep(self, sample_python_file, temp_env):
        """Test that compact=False uses ripgrep with section hints."""
        with patch.object(server, '_rtk_grep') as mock_rtk:
            result = server.grep_content.fn(
                pattern="calculate_total",
                search_path=str(temp_env),
                compact=False
            )
            
            mock_rtk.assert_not_called()
            # Should have section hints from ripgrep
            assert "sample.py" in result

    def test_grep_content_rtk_failure_fallback(self, sample_python_file, temp_env):
        """Test fallback to ripgrep when RTK grep fails."""
        with patch.object(server, '_rtk_grep') as mock_rtk:
            mock_rtk.return_value = (None, "RTK grep failed")
            
            result = server.grep_content.fn(
                pattern="calculate",
                search_path=str(temp_env),
                compact=True
            )
            
            # Should contain fallback message and ripgrep results
            assert "RTK grep failed" in result or "sample.py" in result


class TestRTKHelperFunctions:
    """Tests for RTK helper functions."""

    def test_rtk_compress_content_success(self):
        """Test _rtk_compress_content with successful RTK call."""
        server.IS_RTK_AVAILABLE = True
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="compressed output"
            )
            
            content, warning = server._rtk_compress_content("original content")
            
            assert content == "compressed output"
            assert warning is None

    def test_rtk_compress_content_failure(self):
        """Test _rtk_compress_content with RTK failure."""
        server.IS_RTK_AVAILABLE = True
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="error"
            )
            
            content, warning = server._rtk_compress_content("original content")
            
            assert content == "original content"  # Fallback to original
            assert warning is not None
            assert "failed" in warning.lower()

    def test_rtk_compress_content_timeout(self):
        """Test _rtk_compress_content with timeout."""
        server.IS_RTK_AVAILABLE = True
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="rtk", timeout=30)
            
            content, warning = server._rtk_compress_content("original content")
            
            assert content == "original content"  # Fallback to original
            assert warning is not None
            assert "timeout" in warning.lower()

    def test_rtk_grep_success(self):
        """Test _rtk_grep with successful call."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="🔍 5 in 2F:\n\n📄 file.py (3):"
            )
            
            output, error = server._rtk_grep("pattern", ".")
            
            assert "🔍" in output
            assert error is None

    def test_rtk_grep_no_matches(self):
        """Test _rtk_grep with no matches (exit code 1)."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="🔍 0 for 'pattern'"
            )
            
            output, error = server._rtk_grep("pattern", ".")
            
            # Exit code 1 = no matches, not an error
            assert error is None

class TestRTKTreeHelperFunctions:
    """Tests for RTK tree helper function."""

    def test_rtk_tree_success(self):
        """Test _rtk_tree with successful RTK call."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="project/\n\\-- src/\n"
            )

            output, error = server._rtk_tree("/tmp/project", 3, [".git", "node_modules"])

            assert error is None
            assert "project/" in output

            cmd = mock_run.call_args[0][0]
            assert cmd[0].endswith("rtk")
            assert cmd[1] == "tree"
            assert "-L" in cmd
            assert "3" in cmd
            assert "-I" in cmd
            assert ".git|node_modules" in cmd

    def test_rtk_tree_failure(self):
        """Test _rtk_tree when RTK tree returns an error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2,
                stderr="tree command not found"
            )

            output, error = server._rtk_tree("/tmp/project", 3, [".git"])

            assert output is None
            assert error is not None
            assert "failed" in error.lower()


class TestDirectoryTreeCompact:
    """Tests for directory_tree compact output modes."""

    def test_directory_tree_compact_true_calls_rtk_tree(self, temp_env):
        """compact=True should call RTK tree and return compact text output."""
        project_dir = temp_env / "project"
        project_dir.mkdir()

        with patch.object(server, "_rtk_tree") as mock_tree:
            mock_tree.return_value = ("project/\n\\-- src/\n", None)

            result = server.directory_tree.fn(path=str(project_dir), compact=True)

            mock_tree.assert_called_once()
            assert "[path_context:" in result
            assert "project/\n\\-- src/\n" in result

    def test_directory_tree_compact_false_returns_json(self, temp_env):
        """compact=False should return JSON with path_context and tree keys."""
        project_dir = temp_env / "project"
        project_dir.mkdir()
        (project_dir / "src").mkdir()
        (project_dir / "src" / "main.py").write_text("print('hi')\n")

        with patch.object(server, "_rtk_tree") as mock_tree:
            result = server.directory_tree.fn(path=str(project_dir), compact=False)

            mock_tree.assert_not_called()
            import json
            parsed = json.loads(result)
            assert "path_context" in parsed
            assert "allowed_dirs" in parsed
            assert "tree" in parsed
            assert parsed["tree"]["name"] == "project"
            assert parsed["tree"]["type"] == "directory"
            assert "children" in parsed["tree"]

    def test_directory_tree_compact_rtk_failure_fallback(self, temp_env):
        """compact=True falls back to built-in compact tree if RTK fails."""
        project_dir = temp_env / "project"
        project_dir.mkdir()
        (project_dir / "src").mkdir()
        (project_dir / "src" / "main.py").write_text("print('hi')\n")

        with patch.object(server, "_rtk_tree") as mock_tree:
            mock_tree.return_value = (None, "RTK tree failed")

            result = server.directory_tree.fn(path=str(project_dir), compact=True)

            mock_tree.assert_called_once()
            assert "[path_context:" in result
            assert "using built-in compact tree" in result
            assert "project/" in result
            assert "src/" in result
            assert "main.py" in result