import pytest
from unittest.mock import patch, MagicMock
import subprocess
import json
from pathlib import Path
import tempfile
from fs_mcp import server

# Fixture to set up a temporary directory with a test file
@pytest.fixture
def temp_search_dir(tmp_path):
    d = tmp_path / "search"
    d.mkdir()
    p = d / "test_file.txt"
    p.write_text("hello world\nsecond line with content\nhello again")
    return d

@patch('subprocess.run')
def test_grep_content_success(mock_run, temp_search_dir):
    """Test a successful search with matches."""
    server.IS_RIPGREP_AVAILABLE = True
    server.ALLOWED_DIRS = [temp_search_dir.resolve()]
    
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        '{"type":"match","data":{"path":{"text":"search/test_file.txt"},"line_number":1,"lines":{"text":"hello world\\n"}}}\n'
        '{"type":"match","data":{"path":{"text":"search/test_file.txt"},"line_number":3,"lines":{"text":"hello again\\n"}}}'
    )
    mock_result.stderr = ""
    mock_run.return_value = mock_result
    
    result = server.grep_content.fn("hello", search_path=str(temp_search_dir))
    
    assert "File: search/test_file.txt" in result
    assert "Line: 1" in result
    assert "hello world" in result
    assert "Line: 3" in result
    assert "hello again" in result

@patch('subprocess.run')
def test_grep_content_no_matches(mock_run, temp_search_dir):
    """Test a search with no matches."""
    server.IS_RIPGREP_AVAILABLE = True
    server.ALLOWED_DIRS = [temp_search_dir.resolve()]

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = ""
    mock_run.return_value = mock_result
    
    result = server.grep_content.fn("nonexistent", search_path=str(temp_search_dir))
    
    assert "No matches found." in result

def test_grep_content_ripgrep_not_available():
    """Test the tool's behavior when ripgrep is not available."""
    server.IS_RIPGREP_AVAILABLE = False
    
    result = server.grep_content.fn("any_pattern")
    
    assert "Error: ripgrep is not available" in result

@patch('subprocess.run')
def test_grep_content_timeout(mock_run, temp_search_dir):
    """Test the tool's behavior on a timeout."""
    server.IS_RIPGREP_AVAILABLE = True
    server.ALLOWED_DIRS = [temp_search_dir.resolve()]
    
    # Simulate a timeout
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="rg", timeout=10)
    
    result = server.grep_content.fn("any_pattern", search_path=str(temp_search_dir))
    
    assert "Error: Search timed out after 10 seconds" in result

@patch('subprocess.run')
def test_grep_content_case_insensitive(mock_run, temp_search_dir):
    """Test a case-insensitive search."""
    server.IS_RIPGREP_AVAILABLE = True
    server.ALLOWED_DIRS = [temp_search_dir.resolve()]
    
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        '{"type":"match","data":{"path":{"text":"search/test_file.txt"},"line_number":1,"lines":{"text":"hello world\\n"}}}\n'
        '{"type":"match","data":{"path":{"text":"search/test_file.txt"},"line_number":3,"lines":{"text":"hello again\\n"}}}'
    )
    mock_result.stderr = ""
    mock_run.return_value = mock_result
    
    # "HELLO" should match "hello" when case_insensitive is True
    result = server.grep_content.fn("HELLO", search_path=str(temp_search_dir), case_insensitive=True)
    
    assert "File: search/test_file.txt" in result
    assert "Line: 1" in result
    assert "hello world" in result
    assert "Line: 3" in result
    assert "hello again" in result
