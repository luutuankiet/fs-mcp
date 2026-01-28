---
phase: 05-enhance-section-aware-reading
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - "src/fs_mcp/server.py"
autonomous: true
gap_closure: true

must_haves:
  truths:
    - "An agent can call `grep_content` and receive a `section_end_hint`."
    - "The `section_end_hint` is generated based on a default list of patterns."
    - "An agent can provide a custom list of regex patterns to generate the `section_end_hint`."
    - "An agent can disable the hint generation by passing an empty list."
  artifacts:
    - path: "src/fs_mcp/server.py"
      provides: "Enhanced grep_content function with section end hinting"
      contains:
        - "def grep_content("
        - "section_patterns: Optional[List[str]] = None"
        - "section end hint:"
  key_links:
    - from: "grep_content result processing loop"
      to: "file content scanning logic"
      via: "nested file read after a match is found"
      pattern: "with open(result_file_path, 'r', encoding='utf-8') as f:"
---

<objective>
Close the gaps identified in the Phase 5 verification report by re-implementing the `section_end_hint` feature in the `grep_content` tool. The previous implementation was lost or reverted, breaking the "grep -> read section" workflow.

**Purpose:** To restore the intended functionality of Phase 5, Plan 2, enabling agents to intelligently read logical blocks of code.
**Output:** An updated `src/fs_mcp/server.py` with a fully functional `grep_content` that provides section end hints.
</objective>

<execution_context>
@~/.config/opencode/get-shit-done/workflows/execute-plan.md
@~/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@src/fs_mcp/server.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Re-implement Section End Hinting in `grep_content`</name>
  <files>
    src/fs_mcp/server.py
  </files>
  <action>
    The goal is to modify the `grep_content` function to add a `section_end_hint` to each match. This will close the four gaps identified in the verification report.

    1.  **Update Function Signature:** Modify the `grep_content` function signature to accept a new optional parameter: `section_patterns: Optional[List[str]] = None`.

    2.  **Implement Hint Generation Logic:**
        - Inside `grep_content`, after the initial `ripgrep` subprocess call and inside the loop that processes results, add the logic to find section ends.
        - **Default Patterns:** If `section_patterns` is `None`, use a default list of patterns suitable for Python, such as `[r'^\s*def ', r'^\s*class ']`.
        - **Disable Hinting:** If `section_patterns` is an empty list `[]`, skip the entire hint generation process for that call.
        - **Custom Patterns:** If `section_patterns` is a list of strings, use those as the regex patterns.
        - **Scanning Logic:** For each match from `ripgrep`:
            - Open the file corresponding to the match.
            - Seek to the line *after* the matched line number.
            - Read the rest of the file line by line.
            - For each subsequent line, check if it matches any of the active section end patterns.
            - The first line that matches a pattern is the end of the section. Record its line number.
            - If no pattern is matched by the end of the file, the hint should be `EOF`.
        - **Error Handling:** Wrap the hint generation logic in a `try...except` block to ensure that any failures (e.g., file read errors, bad regex) do not crash the `grep_content` tool. If an error occurs, simply don't add a hint.

    3.  **Update Output Format:**
        - Append the hint to the end of the result string for each match.
        - The format should be ` (section end hint: L<line_number>)` or ` (section end hint: EOF)`.
        - Example: `123:    def my_function(): (section end hint: L145)`

    Reference the existing implementation of `read_files` for patterns on how to read files line-by-line efficiently.
  </action>
  <verify>
    After modification, run `grep "section end hint" src/fs_mcp/server.py`. The command should find the new implementation details within the `grep_content` function. The core logic for pattern matching and file scanning should be present.
  </verify>
  <done>
    - The `grep_content` function in `src/fs_mcp/server.py` is updated with the `section_patterns` parameter.
    - The function correctly generates and appends `section_end_hint` to its output.
    - The feature works with default patterns, custom patterns, and can be disabled with an empty list.
    - All four failed truths from the verification report are now addressed.
  </done>
</task>

</tasks>

<verification>
The successful completion of this plan will be verified by re-running the checks that previously failed:
1.  Calling `grep_content` without custom patterns adds a default hint (e.g., the start of the next function).
2.  Calling `grep_content` with a custom pattern list uses those patterns for hinting.
3.  Calling `grep_content` with `section_patterns=[]` produces no hints.
4.  The "grep -> read section" workflow is now fully functional.
</verification>

<success_criteria>
All gaps from the Phase 5 verification report are closed. The `grep_content` tool is now fully integrated with the section-aware reading capabilities of `read_files`, making the agent's codebase exploration workflow significantly more efficient. The project is ready to proceed to the next phase or be considered complete.
</success_criteria>

<output>
After completion, create `.planning/phases/05-enhance-section-aware-reading/05-2-SUMMARY.md`
</output>
