import pytest
from pathlib import Path
from fs_mcp import server

@pytest.fixture
def temp_env(tmp_path):
    """Sets up a safe temporary directory environment"""
    server.initialize([str(tmp_path)])
    return tmp_path

def test_security_barrier(temp_env):
    """Attempting to access outside the temp dir should fail"""
    outside = Path("/etc/passwd")
    
    with pytest.raises(ValueError, match="Access denied"):
        server.validate_path(str(outside))

def test_write_and_read(temp_env):
    """Test basic read/write tools"""
    target = temp_env / "test.txt"
    
    # Write (Access .fn to call underlying function)
    server.write_file.fn(str(target), "Hello MCP")
    assert target.exists()
    
    # Read
    content = server.read_text_file.fn(str(target))
    assert content == "Hello MCP"

def test_read_multiple_files(temp_env):
    """Test reading multiple files"""
    f1 = temp_env / "f1.txt"
    f2 = temp_env / "f2.txt"
    
    server.write_file.fn(str(f1), "Content 1")
    server.write_file.fn(str(f2), "Content 2")
    
    # Test valid + invalid path mixed
    paths = [str(f1), str(f2), str(temp_env / "missing.txt")]
    result = server.read_multiple_files.fn(paths)
    
    assert "Content 1" in result
    assert "Content 2" in result
    assert "missing.txt" in result
    assert "Error" in result # For the missing file
    assert "---" in result

def test_list_directory(temp_env):
    """Test directory listing"""
    (temp_env / "A").mkdir()
    (temp_env / "B.txt").touch()
    
    res = server.list_directory.fn(str(temp_env))
    assert "[DIR] A" in res
    assert "[FILE] B.txt" in res