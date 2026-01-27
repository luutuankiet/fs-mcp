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
      provides: "An enhanced grep_content function that can provide section end hints."
      contains:
        - "def grep_content(pattern: str, search_path: str = '.', case_insensitive: bool = False, context_lines: int = 2, section_patterns: Optional[List[str]] = None) -> str:"
        - "section_end_hint"
  key_links:
    - from: "Primary `ripgrep` result processing loop"
      to: "Secondary file scan logic for hint generation"
      via: "A nested loop or function call for each grep match"
      pattern: "for message in result.stdout.strip().split('\\n'):"
---

<objective>
Close the verification gaps from the previous execution by implementing the `section_end_hint` feature in the `grep_content` tool. This involves modifying the function signature, adding logic to scan for section boundaries, and updating the output format and documentation.

Purpose: To complete the "grep → read section" workflow, enabling agents to efficiently read logical blocks of code identified by `grep_content`.
Output: An updated `src/fs_mcp/server.py` with a fully functional `grep_content` tool that includes section end hints.
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
@.planning/phases/05-enhance-section-aware-reading/05-1-SUMMARY.md
@src/fs_mcp/server.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Implement `section_end_hint` feature in `grep_content`</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    This is a single, comprehensive task to fully implement the `section_end_hint` feature, addressing all previous gaps.

    **1. Update Function Signature:**
    Locate the `grep_content` function definition and modify its signature to accept the new optional parameter.
    *   **From:** `def grep_content(pattern: str, search_path: str = '.', case_insensitive: bool = False, context_lines: int = 2) -> str:`
    *   **To:** `def grep_content(pattern: str, search_path: str = '.', case_insensitive: bool = False, context_lines: int = 2, section_patterns: Optional[List[str]] = None) -> str:`

    **2. Implement Hint Generation Logic:**
    Inside the `grep_content` function, after the subprocess call and before returning the results, you will process the matches to add hints.

    *   Collect the initial matches from ripgrep's JSON output into a list of dictionaries. Each dictionary should contain the path, line number, and text.
    *   Define the default patterns: `DEFAULT_SECTION_PATTERNS = [r"^## ", r"^# ", r"^\[LOG-", r"^def ", r"^class "]`
    *   Iterate through your list of collected matches. For each match:
        *   Determine which patterns to use:
            *   If `section_patterns` is `None`, use `DEFAULT_SECTION_PATTERNS`.
            *   If `section_patterns` is `[]` (an empty list), skip hint generation for this match.
            *   Otherwise, use the agent-provided `section_patterns`.
        *   If hint generation is enabled, open the file for the current match.
        *   Use `itertools.islice(f, match['line_number'], None)` to efficiently start scanning from the line *after* the match.
        *   Loop through the subsequent lines, using `re.search()` to check against each pattern.
        *   The first time a line matches a pattern, store its line number (match line number + lines scanned) as the `section_end_hint` and break the inner loop.
        *   Add the found hint (or `None`) to the match's dictionary.

    **3. Update Output Formatting:**
    Modify the final loop that builds the output string.
    *   For each processed match, check if it has a `section_end_hint`.
    *   If a hint exists, append it to the output string for that match. Example: `File: {path}, Line: {line_number}, section_end_hint: {hint_line_number}\\n---\\n{text}\\n---`
    *   If no hint exists, format the output as before.

    **4. Update Docstring:**
    Modify the docstring of `grep_content` to document the new functionality.
    *   Add `section_patterns: Optional[List[str]] = None` to the arguments section.
    *   Explain what the parameter does and its three modes of operation (default `None`, disabled `[]`, custom list).
    *   Explain what the `section_end_hint` in the output represents.
    *   Add a new example to the docstring showing how to use `section_patterns`.

  </action>
  <verify>
    1. Create a temporary file `test_sections.md` with content like:
    ```markdown
    # Section 1
    Some content to find.

    ## Section 1.1
    More content here.

    # Section 2
    Another thing to find.
    ```
    2. Call `grep_content` with `pattern="content to find"` on `test_sections.md`. The output should include `section_end_hint: 4`.
    3. Call `grep_content` with `pattern="Another thing"` on `test_sections.md`. The output should not have a hint, as it's the last section.
    4. Call `grep_content` with the same pattern but `section_patterns=[]`. The output should NOT include a `section_end_hint`.
    5. Call `grep_content` with `pattern="More content here"` and `section_patterns=["^# "]`. The output should include `section_end_hint: 7`.
  </verify>
  <done>
    All gaps identified in the verification report are closed. The `grep_content` tool now correctly generates and displays `section_end_hint`s based on default, custom, or disabled patterns, and its documentation is updated.
  </done>
</task>

</tasks>

<verification>
- The `grep_content` tool includes a `section_end_hint` in its output when appropriate.
- The hint generation correctly uses the default patterns when `section_patterns` is not provided.
- The hint generation correctly uses custom patterns when provided.
- The hint generation is correctly disabled when `section_patterns` is an empty list.
- The tool's docstring in the OpenAPI docs (`/docs`) is updated and accurate.
</verification>

<success_criteria>
The "grep -> read section" workflow is now fully enabled and discoverable by agent developers, closing all gaps from the previous verification failure.
</success_criteria>

<output>
After completion, create `.planning/phases/05-enhance-section-aware-reading/05-2-SUMMARY.md`
</output>
