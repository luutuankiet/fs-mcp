# Phase 1: Ripgrep Integration & Core Grep Tool - Research

**Researched:** 2026-01-26
**Domain:** Python `subprocess` management and `ripgrep` CLI usage.
**Confidence:** HIGH

## Summary

This research phase focused on the best practices for integrating the `ripgrep` (`rg`) command-line tool into the existing Python server. The primary goal is to create a robust, secure, and efficient `grep_content` tool for the agent.

The standard and most reliable approach is to use Python's built-in `subprocess` module to execute `rg` with specific command-line flags. The single most important flag is `--json`, which provides a structured, machine-readable output format. This completely avoids the fragility of parsing plain-text output and is the cornerstone of the recommended architecture. Dependency checking should be handled by `shutil.which` at startup to ensure `rg` is available.

**Primary recommendation:** Use `subprocess.run` to call `ripgrep` with the `--json` flag. Parse the resulting newline-delimited JSON stream to construct the search results. This approach is secure, robust, and directly provides all the required data points (file path, line number, matches, context).

## Standard Stack

The implementation relies entirely on Python's standard library and the `ripgrep` binary being present on the system. No additional third-party Python libraries are required.

### Core
| Tool/Module | Purpose | Why Standard |
|---|---|---|
| `ripgrep` (`rg`) | High-performance command-line search tool. | Fast, respects `.gitignore` by default, and offers structured JSON output, making it ideal for programmatic use. |
| `subprocess` | Standard Python module for executing external commands. | The modern (`subprocess.run`) and secure way to interact with command-line tools from Python. |
| `shutil.which` | Standard Python function to find an executable in the `PATH`. | The canonical method for checking if a command-line tool like `rg` is installed and available. |
| `platform` | Standard Python module to access underlying platform data. | Used to determine the operating system (macOS, Linux, Windows) to provide platform-specific installation instructions. |
| `json` | Standard Python module for parsing JSON. | Required to parse the output from `ripgrep` when using the `--json` flag. |

## Architecture Patterns

### Pattern 1: Dependency Check at Startup

**What:** On server startup, use `shutil.which('rg')` to check for the `ripgrep` executable. If it returns `None`, the tool is not available.

**When to use:** This pattern should be implemented once when the application initializes. The result (e.g., a boolean `is_ripgrep_available` flag) should be stored in the application's state to be checked by the `grep_content` tool later.

**Example:**
```python
import shutil
import platform

def check_ripgrep_availability():
    """Checks for ripgrep and returns install instructions if missing."""
    if shutil.which('rg'):
        print("ripgrep is installed.")
        return True, ""
    
    system = platform.system()
    if system == "Darwin":
        install_cmd = "brew install ripgrep"
    elif system == "Linux":
        # This is a simplification; could check for apt vs dnf/yum
        install_cmd = "sudo apt-get install -y ripgrep"
    elif system == "Windows":
        install_cmd = "choco install ripgrep"
    else:
        install_cmd = "Please install ripgrep using your system's package manager."
        
    error_message = f"ripgrep not found. Please install it: `{install_cmd}`"
    print(error_message)
    return False, error_message
```

### Pattern 2: Safe and Bounded Subprocess Execution

**What:** Execute the `rg` command using `subprocess.run`. Arguments must be passed as a list to prevent shell injection vulnerabilities. The command should include flags to control output format (`--json`), limit results (`--max-count`), and handle timeouts.

**When to use:** This is the core pattern for the `grep_content` tool.

**Example:**
```python
import subprocess
import json

def run_grep(pattern, path, case_insensitive=False, context_lines=2):
    """Executes the ripgrep command and returns parsed JSON results."""
    command = [
        'rg',
        '--json',
        '--line-number',
        f'--max-count={100}',  // Requirement GREP-05
        f'--context={context_lines}', // Requirement GREP-04
        '--stats', // To check if we hit the max count
    ]
    if case_insensitive:
        command.append('--ignore-case') // Requirement GREP-07

    command.extend([pattern, path])

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False, # Don't raise exception on non-zero exit codes
            timeout=10 # Requirement GREP-10
        )

        if process.returncode == 1:
            # rg exits with 1 for no matches, which is not an error for us
            return {"matches": [], "summary": "No matches found."}
        
        # For other errors (exit code 2), stderr will contain the issue
        if process.returncode != 0:
            return {"error": process.stderr}

        # Process the newline-delimited JSON output
        results = []
        for line in process.stdout.strip().split('\n'):
            results.append(json.loads(line))
        
        return results

    except subprocess.TimeoutExpired:
        return {"error": "Search exceeded 10s limit, refine pattern."}
    except FileNotFoundError:
        # This is a fallback, startup check should prevent this
        return {"error": "ripgrep not found."}
```

### Anti-Patterns to Avoid
- **Using `shell=True`:** Never use `subprocess.run(..., shell=True)` with user-provided input. It is a major security vulnerability that allows for command injection. Always pass arguments as a list.
- **Parsing Raw Text Output:** Do not attempt to parse the default, human-readable output of `ripgrep`. It is brittle and will break with future `ripgrep` updates. The `--json` flag provides a stable, machine-readable contract.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Finding executable | Custom PATH searching logic | `shutil.which()` | It's the standard, cross-platform, and correct way to find an executable in the user's `PATH`. |
| OS detection | Complex parsing of `os.name` or other variables | `platform.system()` | Returns a simple, standard string like 'Linux', 'Darwin', or 'Windows' that is easy to work with. |
| Search result parsing | Regex parsing of `rg`'s text output | `rg --json` and `json.loads()` | `ripgrep` provides a stable JSON API for programmatic use. Parsing text is fragile and error-prone. |

## Common Pitfalls

### Pitfall 1: Mishandling `ripgrep` Exit Codes
**What goes wrong:** The script crashes or returns a generic error when `ripgrep` finds no matches.
**Why it happens:** `ripgrep` exits with code `1` when no matches are found. `subprocess.run` with `check=True` will raise a `CalledProcessError` in this case, which is incorrect behavior for our use case.
**How to avoid:** Set `check=False` in the `subprocess.run` call and explicitly check the `returncode`. Treat `0` as success, `1` as "no matches found," and any other code (like `2`) as a genuine error.
**Warning signs:** The tool returns an error instead of an empty result set for valid but non-matching patterns.

### Pitfall 2: Command Injection via Unsafe Argument Handling
**What goes wrong:** A malicious user crafts a search pattern like `; rm -rf /` that gets executed by the shell.
**Why it happens:** This occurs if `subprocess.run` is used with `shell=True` and the command is passed as a single string.
**How to avoid:** Always pass the command and its arguments as a list of strings to `subprocess.run` (e.g., `['rg', '--ignore-case', pattern, path]`). This ensures that arguments are treated as data, not executable code.

### Pitfall 3: Inefficiently Parsing Large JSON Outputs
**What goes wrong:** The server becomes unresponsive or consumes excessive memory when a search yields a very large number of results (even within the 100-match limit).
**Why it happens:** Reading the entire `stdout` into memory at once and then splitting by newlines can be inefficient for large outputs.
**How to avoid:** For now, the 100-match cap makes this less of a concern. However, the ideal pattern for large outputs is to use `subprocess.Popen` and read `process.stdout` line by line, parsing each JSON object as it arrives. For this phase, `subprocess.run` is sufficient due to the hard result limit.

## Code Examples

### Finding `ripgrep` and Providing Instructions
```python
# Source: Python Standard Library Documentation
# See "Pattern 1" in Architecture Patterns for full example.
import shutil
import platform

def get_ripgrep_install_command():
    if shutil.which('rg'):
        return None # It's installed

    system = platform.system()
    if system == "Darwin":
        return "brew install ripgrep"
    if system == "Linux":
        return "sudo apt-get install -y ripgrep # or use dnf/yum"
    if system == "Windows":
        return "choco install ripgrep"
    return "Could not determine OS. Please install ripgrep manually."
```

### Parsing `ripgrep`'s JSON Output
```python
# Source: ripgrep GUIDE.md and Python json module docs
import json

def process_rg_json_output(json_stream_string):
    """
    Parses newline-delimited JSON from ripgrep and extracts matches.
    NOTE: This is a simplified example. The actual implementation
    will need to handle different message types ('begin', 'end', 'context').
    """
    matches = []
    for line in json_stream_string.strip().split('\n'):
        try:
            message = json.loads(line)
            if message['type'] == 'match':
                match_data = {
                    'path': message['data']['path']['text'],
                    'line_number': message['data']['line_number'],
                    'line_text': message['data']['lines']['text'].strip(),
                    'submatches': message['data']['submatches']
                }
                matches.append(match_data)
        except (json.JSONDecodeError, KeyError) as e:
            # Log this error, as it indicates unexpected output from rg
            print(f"Skipping invalid JSON line: {e}")
            continue
    return matches
```

## Open Questions

1. **How to handle Linux package manager diversity?**
   - What we know: `apt-get` is common on Debian/Ubuntu, but Fedora/CentOS use `dnf` or `yum`.
   - What's unclear: How much effort should be spent auto-detecting the specific Linux package manager?
   - Recommendation: For Phase 1, providing a message like `"sudo apt-get install ripgrep # or use dnf/yum on Fedora/CentOS"` is sufficient. We can improve the detection logic later if users request it.

## Sources

### Primary (HIGH confidence)
- **Python `subprocess` docs:** [https://docs.python.org/3/library/subprocess.html](https://docs.python.org/3/library/subprocess.html)
- **Python `shutil.which` docs:** [https://docs.python.org/3/library/shutil.html#shutil.which](https://docs.python.org/3/library/shutil.html#shutil.which)
- **`ripgrep` GUIDE.md (for `--json` flag):** [https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md](https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md)

### Tertiary (LOW confidence)
- General web searches for `ripgrep` examples, which confirmed the common flags (`-i`, `-C`, etc.). These were cross-referenced with the official guide.
