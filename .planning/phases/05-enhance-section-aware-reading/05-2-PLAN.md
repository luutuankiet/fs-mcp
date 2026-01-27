---
phase: 05-enhance-section-aware-reading
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - "src/fs_mcp/server.py"
autonomous: true

must_haves:
  truths:
    - "An agent can call `grep_content` and receive a `section_end_hint` along with each match, suggesting where the current logical block ends."
    - "The `section_end_hint` is generated based on a default list of patterns if no custom patterns are provided."
    - "An agent can provide a custom list of regex patterns to generate the `section_end_hint`."
    - "An agent can disable the hint generation by passing an empty list."
  artifacts:
    - path: "src/fs_mcp/server.py"
      provides: "An enhanced grep_content function that can provide section end hints."
      contains:
        - "def grep_content("
        - "section_patterns: Optional[List[str]] = None"
        - "section_end_hint"
  key_links:
    - from: "Primary `ripgrep` result processing loop"
      to: "Secondary file scan logic for hint generation"
      via: "A nested loop or function call for each grep match"
      pattern: "for match in matches:"
---

<objective>
Enhance the `grep_content` tool in `src/fs_mcp/server.py` to provide a `section_end_hint`. This hint will be a line number suggesting the end of the logical section containing a match, guiding the agent to make more effective use of the newly enhanced `read_files` tool.

Purpose: To bridge the gap between finding a match (`grep`) and reading its full context (`read`). By providing a hint for the section's end, we complete the "grep → read section" workflow.
Output: An updated `src/fs_mcp/server.py` with the modified `grep_content` function.
</objective>

<execution_context>
@~/.config/opencode/get-shit-done/workflows/execute-plan.md
@~/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-enhance-section-aware-reading/05-CONTEXT.md
@.planning/phases/05-enhance-section-aware-reading/05-RESEARCH.md
@src/fs_mcp/server.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add `section_patterns` Parameter to `grep_content`</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Locate the function definition for `grep_content` in `src/fs_mcp/server.py`.
    2.  Add the new optional parameter to its signature: `section_patterns: Optional[List[str]] = None`.
    3.  Ensure the type hints are correct (`Optional`, `List`, `str` from the `typing` module).
  </action>
  <verify>
    - Run the server and inspect the OpenAPI docs (`/docs`).
    - Confirm that the `grep_content` tool now has a `section_patterns` parameter and that its schema accepts a list of strings or null.
  </verify>
  <done>
    The `grep_content` function signature is updated to accept the `section_patterns` parameter.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement `section_end_hint` Generation Logic</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Inside `grep_content`, after the `ripgrep` results have been parsed into a list of matches, iterate through each match.
    2.  **Determine Patterns:**
        - If `section_patterns` is `None` (the default), use the hardcoded default list: `[r"^## ", r"^# ", r"^\[LOG-"]`.
        - If `section_patterns` is an empty list `[]`, skip the hint generation for all matches.
        - If `section_patterns` is a list of strings, use that list.
    3.  **Scan for Hint:** For each match, if hint generation is enabled:
        a. Open the file corresponding to the match.
        b. Start a line-by-line scan beginning on the line *after* the match's line number.
        c. For each line, check if it matches any of the regexes in the chosen pattern list.
        d. The first time a line matches one of the patterns, record its 1-based line number as the `section_end_hint` and stop scanning for that match.
        e. If no pattern is found by EOF, there is no hint for that match.
    4.  **Format Output:** Append the `section_end_hint` to the formatted output string for each match where a hint was found (e.g., ` | section_end_hint: {line_number}`).
  </action>
  <verify>
    - Create a test file with clear sections (e.g., markdown headers).
    - Call `grep_content` targeting content within a section. Verify the output for that match includes the correct line number for the *next* section header as the hint.
    - Call `grep_content` with `section_patterns=[]`. Verify no hints are present in the output.
    - Call `grep_content` with a custom pattern list and verify it is used correctly.
  </verify>
  <done>
    The `grep_content` tool now calculates and includes a `section_end_hint` in its output, based on default or user-provided patterns.
  </done>
</task>

<task type="auto">
  <name>Task 3: Update `grep_content` Docstring</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Locate the docstring for the `grep_content` function.
    2.  Add a detailed explanation of the new `section_patterns` parameter.
    3.  Explain the three behaviors: default (`None`), disabled (`[]`), and custom (list of strings).
    4.  Describe what the `section_end_hint` represents in the output.
    5.  Provide a clear example of how to use the new parameter.
  </action>
  <verify>
    - Check the OpenAPI documentation (`/docs`) and ensure the new parameter and its behaviors are clearly and accurately described.
  </verify>
  <done>
    The `grep_content` tool's documentation is updated to reflect the new section-end hinting capability.
  </done>
</task>

</tasks>

<verification>
1.  The `grep_content` tool includes a `section_end_hint` in its output when appropriate.
2.  The hint generation correctly uses the default patterns when `section_patterns` is not provided.
3.  The hint generation correctly uses custom patterns when provided.
4.  The hint generation is correctly disabled when `section_patterns` is an empty list.
</verification>

<success_criteria>
The `grep_content` tool is enhanced to provide valuable metadata (`section_end_hint`) that guides agents toward more efficient file reading workflows.
</success_criteria>

<output>
After completion, create `.planning/phases/05-enhance-section-aware-reading/05-2-SUMMARY.md`
</output>
