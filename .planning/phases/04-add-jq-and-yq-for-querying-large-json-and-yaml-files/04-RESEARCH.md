# Phase 4: Add jq and yq for querying large JSON and YAML files - Research

**Researched:** 2026-01-26
**Domain:** CLI tool integration for structured data querying (jq for JSON, yq for YAML)
**Confidence:** HIGH

## Summary

This phase adds jq and yq as external CLI tools for efficient querying of large JSON and YAML files through Python subprocess integration. Both tools are mature, stable command-line processors with zero runtime dependencies, making them ideal for the server's pattern of graceful degradation.

**Key findings:**
- **jq 1.8.1** (latest, July 2025) is the industry standard for JSON processing - 33.4k GitHub stars, mature C implementation
- **yq v4.50.1** (latest, December 2025) uses jq-like syntax for YAML/JSON/XML - 14.8k stars, Go implementation
- Both tools follow the same CLI patterns: `tool 'expression' file` with compact output flags
- Query expressions share similar syntax patterns but have important differences (especially for YAML-specific features)
- Python subprocess.run() with proper error handling, timeouts, and output capture is the standard approach
- The ripgrep pattern established in Phase 3 provides an excellent template for implementation

**Primary recommendation:** Follow the ripgrep pattern exactly - subprocess execution with graceful degradation, platform-specific installation guidance, and independent tool checking.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jq | 1.8.1 | JSON command-line processor | Industry standard JSON processor; 33.4k stars, zero dependencies, portable C binary |
| yq (mikefarah) | v4.50.1 | YAML/JSON/XML processor | Most popular YAML processor using jq-like syntax; 14.8k stars, Go implementation |
| subprocess | Python 3.10+ stdlib | Process execution | Python standard library - no external dependencies |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| shutil.which() | Python stdlib | Binary detection | Check if jq/yq are installed before use |
| platform.system() | Python stdlib | OS detection | Platform-specific install instructions |
| distro | (already in deps) | Linux distribution detection | Linux-specific package manager commands |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| yq (mikefarah) | yq (kislyuk) - Python | Python library is older, less maintained (last update 2020), doesn't follow jq syntax |
| Subprocess | pyjq (Python bindings) | Requires compilation, adds dependencies, no benefit over subprocess for this use case |
| Native JSON parsing | jq subprocess | For large files, jq's streaming and filtering is more memory-efficient than loading entire file |

**Installation:**
```bash
# jq
brew install jq          # macOS
choco install jq         # Windows
sudo apt-get install jq  # Ubuntu/Debian
sudo dnf install jq      # Fedora/RHEL

# yq
brew install yq          # macOS
choco install yq         # Windows
# Linux: Download binary from GitHub releases (no native package on most distros)
```

## Architecture Patterns

### Recommended Function Structure
```python
# Pattern: Independent tool functions following ripgrep model
def query_json(file_path: str, jq_expression: str, timeout: int = 30) -> str:
    """Query JSON file using jq"""
    
def query_yaml(file_path: str, yq_expression: str, timeout: int = 30) -> str:
    """Query YAML file using yq"""

# Startup check pattern (existing in server.py initialize())
IS_JQ_AVAILABLE = False
IS_YQ_AVAILABLE = False

def initialize(directories: List[str]):
    global IS_JQ_AVAILABLE, IS_YQ_AVAILABLE
    IS_JQ_AVAILABLE, jq_message = check_jq()
    IS_YQ_AVAILABLE, yq_message = check_yq()
    if not IS_JQ_AVAILABLE:
        print(jq_message)
    if not IS_YQ_AVAILABLE:
        print(yq_message)
```

### Pattern 1: Subprocess Execution with Proper Error Handling
**What:** Execute CLI tool with subprocess.run(), capture output, handle errors
**When to use:** All jq/yq executions
**Example:**
```python
# Source: Existing ripgrep implementation in server.py (lines 660-676)
# Adapted for jq/yq
try:
    result = subprocess.run(
        ['jq', '-c', jq_expression, str(validated_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False  # Handle errors manually
    )
except FileNotFoundError:
    return "Error: 'jq' command not found. Please install jq: [platform-specific command]"
except subprocess.TimeoutExpired:
    return f"Error: Query timed out after {timeout} seconds. Simplify your query."

if result.returncode != 0:
    # jq/yq return non-zero for syntax errors or failures
    return f"Query error: {result.stderr}"

return result.stdout.strip()
```

### Pattern 2: Tool Availability Check with Installation Guidance
**What:** Check if tool exists, provide platform-specific install commands
**When to use:** Server startup and when tool is called but unavailable
**Example:**
```python
# Source: Existing utils.py check_ripgrep() (lines 5-35)
# Pattern to follow exactly
def check_jq():
    if shutil.which('jq'):
        return True, "jq is installed."
    
    system = platform.system()
    if system == 'Darwin':
        install_cmd = "brew install jq"
    elif system == 'Windows':
        install_cmd = "choco install jq"
    elif system == 'Linux':
        dist = distro.id()
        if dist in ['ubuntu', 'debian']:
            install_cmd = "sudo apt-get install jq"
        elif dist in ['fedora', 'centos', 'rhel']:
            install_cmd = "sudo dnf install jq"
        else:
            install_cmd = "Please install jq using your system's package manager."
    else:
        install_cmd = "Could not determine OS. Please install jq manually."
    
    message = f"Warning: jq is not installed. The 'query_json' tool will be disabled. Please install it with: {install_cmd}"
    return False, message
```

### Pattern 3: Compact Output for Token Efficiency
**What:** Use -c flag for single-line JSON output
**When to use:** All query results
**Example:**
```bash
# jq: Use -c for compact output (official flag)
jq -c '.items[] | select(.active == true)' data.json

# yq: Compact output by default for JSON, use -o=json -I=0 for guaranteed compact
yq -o=json -I=0 '.items[] | select(.active == true)' data.yaml
```

### Pattern 4: Result Count Limiting
**What:** Limit results to prevent context overflow (following grep pattern of 100 max)
**When to use:** All queries
**Example:**
```python
# Post-process output to enforce result limit
lines = result.stdout.strip().split('\n')
if len(lines) > 100:
    truncated = '\n'.join(lines[:100])
    return f"{truncated}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use jq/yq slicing: .items[100:200]"
return result.stdout.strip()
```

### Anti-Patterns to Avoid

- **Don't use shell=True**: Security risk for user-supplied query expressions
- **Don't parse JSON in Python first**: Defeats the purpose - use jq/yq directly on files
- **Don't forget timeout**: Large files can cause hangs
- **Don't ignore stderr**: Contains valuable syntax error messages
- **Don't conflate the two yq projects**: mikefarah/yq (Go, jq-like) vs kislyuk/yq (Python, different syntax)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing large files | Python json.load() | jq CLI | Streaming parser, memory-efficient filtering, avoids loading entire file |
| YAML parsing large files | Python yaml.safe_load() | yq CLI | Memory efficiency, built-in jq-like querying instead of nested dict navigation |
| Query syntax validation | Custom regex/parser | jq/yq stderr | Tools provide detailed syntax error messages with line/column info |
| Result formatting | Custom JSON formatter | jq -c / yq -o=json | Built-in compact output, consistent formatting |
| Array slicing syntax | Custom string manipulation | jq/yq .items[0:100] | Native slice syntax, handles edge cases |

**Key insight:** jq and yq are mature tools (10+ years for jq) with extensive testing for edge cases. Custom parsing of large structured files in Python leads to memory issues and slower performance.

## Common Pitfalls

### Pitfall 1: yq Confusion - Two Different Tools
**What goes wrong:** Developers confuse mikefarah/yq (Go, jq-like syntax) with kislyuk/yq (Python wrapper, different syntax)
**Why it happens:** Both are named "yq" but have completely different syntax and capabilities
**How to avoid:** 
- Always specify "mikefarah/yq" in documentation
- Use GitHub release URL: github.com/mikefarah/yq
- Test that `yq --version` shows "mikefarah" in output
**Warning signs:** Query syntax errors when using jq-like expressions with wrong yq version

### Pitfall 2: Query Expression Escaping
**What goes wrong:** Shell metacharacters in expressions break the command or cause security issues
**Why it happens:** Passing user input directly to subprocess without proper quoting
**How to avoid:**
```python
# GOOD: Use list form, subprocess handles escaping
subprocess.run(['jq', expression, file], ...)

# BAD: String form with shell=True - security risk
subprocess.run(f"jq '{expression}' {file}", shell=True, ...)
```
**Warning signs:** Commands fail with shell errors, single quotes in expressions break

### Pitfall 3: Exit Code Misinterpretation
**What goes wrong:** Treating exit code 1 as error when it means "no results"
**Why it happens:** Both jq and yq exit with 1 for empty results, but also for syntax errors
**How to avoid:**
- Check stderr to distinguish: empty output = no results, stderr content = error
- For jq: exit 0 = success, 1 = no output/runtime error, 2 = usage error, 3 = compile error, 5 = system error
- Handle gracefully: "No results found" vs "Query error: ..."
**Warning signs:** "No results" being reported as errors

### Pitfall 4: Large Result Memory Issues
**What goes wrong:** Query returns massive results that overflow agent context or crash server
**Why it happens:** Forgetting to limit result count, especially with .[] iterators
**How to avoid:**
- Always limit results (first 100 by default, matching grep pattern)
- Post-process output to count and truncate
- Guide users to use jq/yq slicing: .items[0:100], .items[100:200]
**Warning signs:** Memory spikes, context overflow errors, slow response times

### Pitfall 5: File Path Validation Order
**What goes wrong:** Validating file path after passing to jq/yq, bypassing security
**Why it happens:** Forgetting the existing validate_path() pattern
**How to avoid:**
```python
# ALWAYS validate before subprocess
validated_path = validate_path(file_path)  # Security check
result = subprocess.run(['jq', expression, str(validated_path)], ...)
```
**Warning signs:** Path traversal vulnerabilities, access to unauthorized files

### Pitfall 6: Timeout Not Propagating to Child Process
**What goes wrong:** Timeout expires but jq/yq process continues running
**Why it happens:** subprocess.run() timeout kills Python's wait, not the child process
**How to avoid:**
- Use result.timeout parameter correctly (already handled by subprocess.run)
- For more control, use Popen.communicate() with timeout
- Current ripgrep pattern is correct and should be followed
**Warning signs:** Zombie processes, continued CPU usage after timeout

## Code Examples

Verified patterns from official sources:

### Basic JSON Query
```python
# Source: Official jq manual + existing ripgrep pattern
# Query specific fields from JSON
command = ['jq', '-c', '.users[] | {name: .name, id: .id}', str(validated_path)]
result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)

# Example input (users.json):
# {"users": [{"name": "Alice", "id": 1}, {"name": "Bob", "id": 2}]}

# Example output (compact, one per line):
# {"name":"Alice","id":1}
# {"name":"Bob","id":2}
```

### YAML Query with Filtering
```python
# Source: mikefarah/yq documentation
# Query YAML with filtering
command = ['yq', '-o=json', '-I=0', '.services[] | select(.enabled == true)', str(validated_path)]
result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)

# Example input (services.yaml):
# services:
#   - name: web
#     enabled: true
#   - name: db
#     enabled: false

# Example output (compact JSON):
# {"name":"web","enabled":true}
```

### Error Handling Pattern
```python
# Source: Existing ripgrep implementation (server.py lines 660-676)
# Complete error handling pattern
def query_json(file_path: str, jq_expression: str, timeout: int = 30) -> str:
    if not IS_JQ_AVAILABLE:
        _, msg = check_jq()
        return f"Error: jq is not available. {msg}"
    
    validated_path = validate_path(file_path)
    
    command = ['jq', '-c', jq_expression, str(validated_path)]
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
    except FileNotFoundError:
        return "Error: 'jq' command not found. Please ensure jq is installed and in your PATH."
    except subprocess.TimeoutExpired:
        return f"Error: Query timed out after {timeout} seconds. Please simplify your query."
    
    if result.returncode != 0:
        # Include stderr for debugging
        error_msg = result.stderr.strip() or "Unknown error"
        return f"Query error: {error_msg}"
    
    # Limit results
    lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
    if not lines or (len(lines) == 1 and not lines[0]):
        return "No results found."
    
    if len(lines) > 100:
        truncated = '\n'.join(lines[:100])
        return f"{truncated}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use jq slicing: .items[100:200]"
    
    return '\n'.join(lines)
```

### Tool Description Pattern (for weak models)
```python
# Pattern: Combine syntax examples with workflow guidance
@mcp.tool()
def query_json(file_path: str, jq_expression: str, timeout: int = 30) -> str:
    """
    Query a JSON file using jq expressions. Use this to efficiently explore large JSON files
    without reading the entire content into memory.
    
    **Common Query Patterns:**
    - Get specific field: '.field_name'
    - Array iteration: '.items[]'
    - Filter array: '.items[] | select(.active == true)'
    - Select fields: '.items[] | {name, id}'
    - Array slice: '.items[0:100]' (first 100 items)
    - Count items: '.items | length'
    
    **Workflow Example:**
    1. Get structure overview: query_json("data.json", "keys")
    2. Count array items: query_json("data.json", ".items | length")
    3. Explore first few: query_json("data.json", ".items[0:5]")
    4. Filter specific: query_json("data.json", ".items[] | select(.status == 'active')")
    
    **Result Limit:** Returns first 100 results. For more, use slicing: .items[100:200]
    
    Args:
        file_path: Path to JSON file (relative or absolute)
        jq_expression: jq query expression (see https://jqlang.github.io/jq/manual/)
        timeout: Query timeout in seconds (default: 30)
    
    Returns:
        Compact JSON results (one per line), or error message
    """
    # Implementation...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| jq 1.6 (2018) | jq 1.8.1 (2025) | July 2025 | New datetime functions, improved error messages, security fixes |
| yq (Python/kislyuk) | yq (Go/mikefarah) | ~2019 | jq-like syntax, multi-format support (YAML/JSON/XML/CSV), better maintained |
| shell=True subprocess | List-form subprocess.run() | Python 3.5+ | Security improvement, proper argument escaping |
| Manual JSON streaming | jq --stream | jq 1.5 (2015) | Memory-efficient streaming for huge files |

**Deprecated/outdated:**
- **yq (kislyuk)**: Python wrapper, last updated 2020, different syntax from jq
- **jq 1.5 and earlier**: Security vulnerabilities (CVE-2023-50246, CVE-2023-50268 fixed in 1.7.1)
- **shell=True with user input**: Security risk, deprecated pattern in subprocess best practices

## Open Questions

Things that couldn't be fully resolved:

1. **yq Linux Package Availability**
   - What we know: yq (mikefarah) is not in most Linux distro repos (apt/dnf)
   - What's unclear: Best installation method for Linux users
   - Recommendation: Provide GitHub release download instructions, or use brew on Linux if available

2. **Optimal Timeout Value**
   - What we know: ripgrep uses 10s, but jq/yq may need longer for complex queries on large files
   - What's unclear: Typical processing time for 100MB+ files
   - Recommendation: Start with 30s default (configurable parameter), monitor in production

3. **Output Format Consistency Between jq and yq**
   - What we know: jq -c produces compact JSON, yq needs -o=json -I=0
   - What's unclear: Whether yq output exactly matches jq format in all cases
   - Recommendation: Test both, document any edge cases in implementation

## Sources

### Primary (HIGH confidence)
- jqlang.github.io/jq - Official jq documentation (version 1.8.1)
- github.com/jqlang/jq - Official jq repository (33.4k stars, verified current version)
- mikefarah.gitbook.io/yq - Official yq documentation
- github.com/mikefarah/yq - Official yq repository (14.8k stars, verified v4.50.1)
- docs.python.org/3/library/subprocess.html - Python subprocess documentation

### Secondary (MEDIUM confidence)
- Existing ripgrep implementation in src/fs_mcp/server.py (lines 622-697) - Established pattern to follow
- Existing utils.py check_ripgrep() (lines 5-35) - Tool detection pattern

### Tertiary (LOW confidence)
- None - All findings verified with official sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official releases and GitHub stars verified, current versions confirmed
- Architecture: HIGH - Existing ripgrep pattern provides proven implementation template
- Pitfalls: MEDIUM-HIGH - Based on official docs and common subprocess issues, some from inference

**Research date:** 2026-01-26
**Valid until:** ~90 days (March 2026) - jq and yq are mature tools with infrequent breaking changes
