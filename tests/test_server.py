import pytest
from pathlib import Path
from fs_mcp import server
import tempfile
import shutil

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
    content = server.read_files.fn([{"path": str(target)}])
    assert "Hello MCP" in content

def test_read_multiple_files(temp_env):
    """Test reading multiple files"""
    f1 = temp_env / "f1.txt"
    f2 = temp_env / "f2.txt"
    
    server.write_file.fn(str(f1), "Content 1")
    server.write_file.fn(str(f2), "Content 2")
    
    # Test valid + invalid path mixed
    requests = [
        {"path": str(f1)},
        {"path": str(f2)},
        {"path": str(temp_env / "missing.txt")}
    ]
    result = server.read_files.fn(requests)
    
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

def test_relative_path_resolution(temp_env):
    """Test that relative paths are resolved correctly."""
    # Create a subdirectory and a file within it
    sub_dir = temp_env / "sub"
    sub_dir.mkdir()
    target_file = sub_dir / "relative_test.txt"
    target_file.touch()

    # Attempt to validate the path using a relative path
    # The server should resolve this relative to the temp_env
    resolved_path = server.validate_path("sub/relative_test.txt")

    # Assert that the resolved path is correct and absolute
    assert resolved_path == target_file.resolve()

def test_temp_file_access_security(temp_env):
    """Test security restrictions for temporary file access."""
    # This test simulates the `propose_and_review` workflow.
    
    # 1. Create a mock review directory in the actual temp location
    real_temp_dir = Path(tempfile.gettempdir())
    review_dir = real_temp_dir / "mcp_review_abc123"
    review_dir.mkdir(exist_ok=True)
    
    # 2. Create valid and invalid files within the mock review dir
    valid_file = review_dir / "current_test.py"
    invalid_file = review_dir / "some_other_file.txt"
    valid_file.touch()
    invalid_file.touch()
    
    # 3. Create a file in a non-review temp directory
    non_review_dir = real_temp_dir / "not_a_review_dir"
    non_review_dir.mkdir(exist_ok=True)
    rogue_file = non_review_dir / "rogue.txt"
    rogue_file.touch()

    # --- Assertions ---
    
    # a) The agent SHOULD be able to access the 'current_' file.
    try:
        # We expect this to succeed. If it raises an error, the test fails.
        resolved_path = server.validate_path(str(valid_file))
        assert resolved_path.exists()
    except ValueError:
        pytest.fail("Validation of a valid temp file unexpectedly failed.")

    # b) The agent SHOULD NOT be able to access a file that doesn't match the expected pattern.
    with pytest.raises(ValueError, match="Access denied"):
        server.validate_path(str(invalid_file))

    # c) The agent SHOULD NOT be able to access files in other temp directories.
    with pytest.raises(ValueError, match="Access denied"):
        server.validate_path(str(rogue_file))
        
    # Cleanup
    shutil.rmtree(review_dir)
    shutil.rmtree(non_review_dir)
