---
phase: 01-ripgrep-integration-core-grep-tool
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - 'server.py'
autonomous: true
user_setup: []

must_haves:
  truths:
    - "When `rg` is not installed, the server starts, prints platform-specific install instructions, and logs a warning."
    - "Calling the `grep_content` tool when `rg` is not installed returns a helpful error message with the same install instructions."
    - "A successful call to `grep_content` returns a structured list of matches, including file path, line number, and content."
    - "Searches are bounded to 100 results to prevent context overflow."
    - "A search with no matches returns a clear 'No matches found' message, not an error."
    - "The search correctly respects `.gitignore` files by default."
  artifacts:
    - path: "server.py"
      provides: "Ripgrep dependency check and the `grep_content` agent tool."
      contains:
        - "def grep_content("
        - "shutil.which('rg')"
        - "subprocess.run"
  key_links:
    - from: "server startup"
      to: "shutil.which('rg')"
      via: "A function call to check for ripgrep availability."
      pattern: "RIPGREP_PATH = shutil.which('rg')"
    - from: "grep_content()"
      to: "subprocess.run(['rg', ...])"
      via: "Executing the ripgrep command-line tool securely."
      pattern: "subprocess.run(rg_command,"
    - from: "subprocess.run() result"
      to: "result parsing"
      via: "Checking the process return code to differentiate success (0), no matches (1), and error (>1)."
      pattern: "proc.returncode"
---

<objective>
This plan integrates the `ripgrep` utility into `server.py`. It adds a dependency check at startup with user-friendly installation instructions and implements the core `grep_content` agent tool with robust error handling and bounded results.

Purpose: To provide a powerful and safe content-search capability for the agent, forming the foundation of the `grep -> read` workflow.
Output: An updated `server.py` with the new tool and dependency check.
</objective>

<execution_context>
@~/.config/opencode/get-shit-done/workflows/execute-plan.md
@~/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-ripgrep-integration-core-grep-tool/01-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement Ripgrep Dependency Check on Startup</name>
  <files>
    - server.py
  </files>
  <action>
    Modify `server.py` to perform a check for the `rg` executable upon startup.
    1.  Import the `shutil` and `platform` modules.
    2.  Use `shutil.which('rg')` to find the path to the ripgrep executable.
    3.  Store the result in a global variable, e.g., `RIPGREP_PATH`.
    4.  If `RIPGREP_PATH` is `None`, print a prominent, user-friendly error message to the console that includes platform-specific installation instructions for macOS (Homebrew), Debian/Ubuntu (apt-get), RedHat/CentOS (dnf), and Windows (winget/choco).
    5.  Log a warning if `rg` is not found, but allow the server to continue running to ensure graceful degradation.
  </action>
  <verify>
    Temporarily rename your `rg` executable (if installed) to simulate its absence. Run `python server.py`. The server should start, print the correct installation instructions for your OS, and log a warning. Restore the executable name and restart the server; the message should not appear.
  </verify>
  <done>
    The server checks for `rg` on startup, provides clear installation instructions if it's missing, and sets a global variable indicating its availability.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement `grep_content` Agent Tool</name>
  <files>
    - server.py
  </files>
  <action>
    In `server.py`, define and register a new agent tool `grep_content`.
    1.  The function signature should accept `pattern: str`, `search_path: str = '.'`, `case_insensitive: bool = False`, and `context_lines: int = 2`.
    2.  **Security:** Immediately inside the function, check if the `RIPGREP_PATH` global variable is `None`. If it is, return the same helpful error message with install instructions defined in Task 1.
    3.  **Security:** Validate that the `search_path` is within the allowed project directory to prevent path traversal attacks.
    4.  Construct the `rg` command as a list of strings to avoid shell injection. Use the `--json` flag for reliable output parsing.
        - Command arguments to include:
            - `--json`: for structured output.
            - `-m 100`: to cap results at 100 matches (Requirement GREP-05).
            - `-C {context_lines}`: for context lines.
            - `-i`: if `case_insensitive` is True.
            - The `pattern` and `search_path`.
    5.  Use `subprocess.run` to execute the command with a `timeout` of 10 seconds (Requirement GREP-10). Capture stdout and stderr.
    6.  Handle the return code:
        - `0`: Success, proceed with parsing.
        - `1`: No matches found. Return a simple message like "No matches found." (Requirement GREP-09).
        - `>1`: An actual error occurred. Return an error message including the contents of stderr.
    7.  If successful, parse the line-delimited JSON output from stdout. Transform the data into a clear, structured list of results for the agent, including file path, line number, and matched text with context.
  </action>
  <verify>
    With the server running, make test calls to the `grep_content` tool:
    - A call that should find matches. Verify the output is a correctly formatted JSON list.
    - A call with a pattern that doesn't exist. Verify it returns "No matches found."
    - A call with `case_insensitive=True`.
    - A call from an agent that attempts to search outside the project directory (e.g., `/etc/`) and verify it is denied.
  </verify>
  <done>
    A secure, robust `grep_content` tool is available to the agent, handling various success and error cases gracefully.
  </done>
</task>

</tasks>

<verification>
After both tasks are complete:
1.  Restart the server.
2.  Confirm the startup dependency check works as expected.
3.  Execute a series of `grep_content` calls that test all specified requirements (case-insensitivity, context lines, no matches, bounded results, timeout).
4.  Verify that a search within a sub-directory containing a `.gitignore` file correctly excludes ignored files.
</verification>

<success_criteria>
1.  Server starts and correctly identifies if `ripgrep` is installed, providing clear instructions if it is not.
2.  The `grep_content` tool is functional and exposed to the agent.
3.  The tool correctly handles searches, no-match scenarios, timeouts, and the `rg`-is-missing case.
4.  Search results are capped and formatted correctly.
5.  Security measures (path validation, no `shell=True`) are implemented.
</success_criteria>

<output>
After completion, create `.planning/phases/01-ripgrep-integration-core-grep-tool/01-1-SUMMARY.md`
</output>
