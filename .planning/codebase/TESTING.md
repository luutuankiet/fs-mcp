# Testing Patterns

**Analysis Date:** 2026-01-26

## Test Framework

**Runner:**
- pytest 8.0.0+
- Config: No explicit `pytest.ini` or `setup.cfg` - uses defaults from `pyproject.toml`

**Assertion Library:**
- pytest's built-in `assert` statements
- Pydantic validators for model assertions

**Run Commands:**
```bash
pytest                  # Run all tests
pytest -v              # Run with verbose output
pytest tests/          # Run specific test directory
pytest tests/test_server.py::test_security_barrier  # Run specific test
```

## Test File Organization

**Location:**
- Co-located in separate `tests/` directory
- Not inline with source code
- Mirror source structure: `src/fs_mcp/` corresponds to `tests/test_*.py`

**Naming:**
- Test files: `test_*.py` prefix: `test_server.py`, `test_edit_tool.py`
- Test functions: `test_*` prefix: `test_security_barrier()`, `test_write_and_read()`, `test_literal_newline_roundtrip()`
- Fixtures: `test_edit_tool.py` line 9-45 shows fixture naming convention

**Structure:**
```
tests/
├── test_server.py        # Tests for src/fs_mcp/server.py
├── test_edit_tool.py     # Tests for src/fs_mcp/edit_tool.py
└── __pycache__/         # Generated, not committed
```

## Test Structure

**Suite Organization:**

In `tests/test_server.py`:
```python
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
    """Test name as docstring describing what is tested"""
    outside = Path("/etc/passwd")
    with pytest.raises(ValueError, match="Access denied"):
        server.validate_path(str(outside))
```

In `tests/test_edit_tool.py`:
```python
import pytest
import shutil
import tempfile
from pathlib import Path

from fs_mcp.edit_tool import RooStyleEditTool

@pytest.fixture
def temp_src_dir(request):
    """Fixture with setup and teardown"""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_fs_mcp_"))
    src_path = Path(__file__).parent.parent / 'src'
    dest_path = temp_dir / 'src'
    shutil.copytree(src_path, dest_path)
    yield dest_path      # Provide resource to tests
    shutil.rmtree(temp_dir)  # Cleanup

@pytest.fixture
def edit_tool(temp_src_dir):
    """Depends on other fixture"""
    return RooStyleEditTool(validate_path_func=create_mock_validator(temp_src_dir))

def test_identity_edit_on_real_file(edit_tool, temp_src_dir):
    """Test receives fixtures as parameters"""
    file_to_test = temp_src_dir / 'fs_mcp' / 'edit_tool.py'
    # ... test body
```

**Patterns:**
- Fixtures use `@pytest.fixture` decorator
- Setup in fixture function body
- Teardown after `yield` statement
- Tests receive fixtures as function parameters
- Docstrings on fixtures describe purpose
- Docstrings on tests describe what is being tested

## Mocking

**Framework:** pytest fixtures + manual mock validation functions

**Patterns:**

In `tests/test_edit_tool.py` line 33-37:
```python
def create_mock_validator(base_path: Path):
    """Creates a mock validator function for testing"""
    def validate(path_str: str) -> Path:
        return base_path.parent / path_str
    return validate
```

This mock replaces actual path validation so tests can:
- Control the working directory
- Test file operations safely
- Verify error handling without real filesystem access

**What to Mock:**
- External dependencies: `server.initialize()` is called in test fixtures
- Path validation: use `create_mock_validator()` for edit_tool tests
- Filesystem operations: use `tmp_path` fixture for temporary files

**What NOT to Mock:**
- Core business logic: `RooStyleEditTool._prepare_edit()` is tested with real logic
- File I/O operations: tests use actual read/write to verify correctness
- Pydantic model validation: tested with real `FileReadRequest` models

## Fixtures and Factories

**Test Data:**

In `tests/test_edit_tool.py` line 48-104:
```python
def test_edit_preserves_literal_escape_sequences(edit_tool, temp_src_dir):
    """Fixture-provided tool and directory used for data setup"""
    file_to_test = temp_src_dir / 'fs_mcp' / 'test_escapes.py'
    # Create test data directly
    original_content = 'line1\nprint("Hello\\nWorld")\nline3\n'
    file_to_test.write_text(original_content, encoding='utf-8')

    # Use the tool with test data
    result = edit_tool._prepare_edit(
        file_path=str(file_to_test),
        old_string='print("Hello\\nWorld")',
        new_string='print("Hi\\nUniverse")',
        expected_replacements=1
    )
```

**Location:**
- Test data created inline within test functions
- Fixtures handle environment setup (`temp_env`, `temp_src_dir`)
- No separate factory module or data files

## Coverage

**Requirements:** Not enforced (no coverage configuration in `pyproject.toml`)

**View Coverage:**
```bash
pytest --cov=src/fs_mcp --cov-report=html
# Then open htmlcov/index.html
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and classes
- Approach: Test in isolation with fixtures
- Examples:
  - `test_security_barrier()` - tests `validate_path()` function
  - `test_identity_edit_on_real_file()` - tests `RooStyleEditTool._prepare_edit()` method
  - `test_write_and_read()` - tests individual tool functions

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Tests use real fixtures and actual file operations
- Examples:
  - `test_write_and_read()` - writes file, then reads it back
  - `test_literal_newline_roundtrip()` - creates file, edits it, verifies content preserved
  - `test_read_multiple_files()` - reads multiple files in single call, verifies output format

**E2E Tests:**
- Framework: Not implemented in current codebase
- The UI server (`web_ui.py`) is not tested (Streamlit apps typically require integration test framework)

## Common Patterns

**Async Testing:**
Not used (no async functions in codebase)

**Error Testing:**

Pattern from `tests/test_server.py` line 13-18:
```python
def test_security_barrier(temp_env):
    """Attempting to access outside the temp dir should fail"""
    outside = Path("/etc/passwd")

    with pytest.raises(ValueError, match="Access denied"):
        server.validate_path(str(outside))
```

- Use `pytest.raises()` context manager to verify exceptions
- Verify exception type: `ValueError`, `FileNotFoundError`
- Verify exception message with `match` parameter (regex)

**Assertion Pattern:**

From `tests/test_server.py` line 20-30:
```python
def test_write_and_read(temp_env):
    """Test basic read/write tools"""
    target = temp_env / "test.txt"

    # Write (Access .fn to call underlying function)
    server.write_file.fn(str(target), "Hello MCP")
    assert target.exists()

    # Read
    content = server.read_files.fn([{"path": str(target)}])
    assert "Hello MCP" in content
```

- Use `assert` statements with inline truthiness checks
- Use `in` operator for string content verification
- Access tool functions via `.fn` attribute (FastMCP tool wrapper)

**Multi-assertion Pattern:**

From `tests/test_server.py` line 32-52:
```python
def test_read_multiple_files(temp_env):
    """Test reading multiple files"""
    f1 = temp_env / "f1.txt"
    f2 = temp_env / "f2.txt"

    server.write_file.fn(str(f1), "Content 1")
    server.write_file.fn(str(f2), "Content 2")

    requests = [
        {"path": str(f1)},
        {"path": str(f2)},
        {"path": str(temp_env / "missing.txt")}
    ]
    result = server.read_files.fn(requests)

    assert "Content 1" in result
    assert "Content 2" in result
    assert "missing.txt" in result
    assert "Error" in result  # For the missing file
    assert "---" in result    # Separator marker
```

- Multiple related assertions in one test
- Each assertion verifies one aspect of result
- Comments explain intent of each assertion

**Setup/Teardown Pattern:**

From `tests/test_edit_tool.py` line 9-31:
```python
@pytest.fixture
def temp_src_dir(request):
    """
    Copies the './src' directory into a temporary directory so that
    tests can be run on them without affecting the original files.
    """
    # Setup
    temp_dir = Path(tempfile.mkdtemp(prefix="test_fs_mcp_"))
    src_path = Path(__file__).parent.parent / 'src'
    dest_path = temp_dir / 'src'
    shutil.copytree(src_path, dest_path)

    # Provide to tests
    yield dest_path

    # Teardown - guaranteed to run
    shutil.rmtree(temp_dir)
```

- Setup runs before fixture usage
- `yield` provides resource to test
- Cleanup after `yield` guaranteed via pytest protocol
- No manual cleanup needed in tests

## Test Organization Best Practices

**Fixture Dependency Chain:**

From `tests/test_edit_tool.py` line 40-45:
```python
@pytest.fixture
def edit_tool(temp_src_dir):
    """
    Returns an instance of RooStyleEditTool configured to work with
    the temporary test directory.
    """
    return RooStyleEditTool(validate_path_func=create_mock_validator(temp_src_dir))
```

- Fixtures can depend on other fixtures
- pytest automatically resolves dependencies
- Parameters in fixture function specify dependencies
- Creates clean dependency graph

**Test Isolation:**

- Each test receives fresh fixture instances
- `tmp_path` pytest built-in creates unique temp dirs per test
- No shared state between tests
- Tests can run in any order

**Real File Testing:**

From `tests/test_server.py` line 117-148:
```python
def test_literal_newline_roundtrip(temp_env):
    """Test that files with literal \\n are preserved..."""
    target = temp_env / "test_newline.py"

    # Step 1: Create a file with literal \n escape sequences
    raw_content = 'print("Hello\\nWorld")'
    server.write_file.fn(str(target), raw_content)

    # Step 2: read_files should return the content as-is
    read_result = server.read_files.fn([{"path": str(target)}])
    assert 'print("Hello\\nWorld")' in read_result

    # Step 3: Edit using exact content from read
    tool = server.RooStyleEditTool(validate_path_func=lambda p: Path(p))
    prep_result = tool._prepare_edit(
        file_path=str(target),
        old_string='print("Hello\\nWorld")',
        new_string='print("Hi\\nUniverse")',
        expected_replacements=1
    )

    assert prep_result.success
    assert prep_result.new_content == 'print("Hi\\nUniverse")'

    # Step 4: Write back and verify file on disk
    server.write_file.fn(str(target), prep_result.new_content)
    final_content = target.read_text(encoding='utf-8')
    assert final_content == 'print("Hi\\nUniverse")'

    # Step 5: Re-read and confirm no corruption
    re_read = server.read_files.fn([{"path": str(target)}])
    assert 'print("Hi\\nUniverse")' in re_read
```

- Tests real file I/O in temp directories
- Verifies encoding/escaping correctness through full roundtrip
- Each step clearly labeled with numbered comments
- Assert at each step to catch failure points

---

*Testing analysis: 2026-01-26*
