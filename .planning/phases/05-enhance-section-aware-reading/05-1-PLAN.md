---
phase: 05-enhance-section-aware-reading
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - "src/fs_mcp/server.py"
autonomous: true

must_haves:
  truths:
    - "An agent can call `read_files` with a `start_line` and a `read_to_next_pattern` and get the content between that line and the pattern."
    - "If the `read_to_next_pattern` is not found, the agent receives content from the start line to the end of the file, along with an informational note."
    - "Calling `read_files` with conflicting parameters (`end_line` and `read_to_next_pattern`) results in a clear, structured error message that helps the agent self-correct."
  artifacts:
    - path: "src/fs_mcp/server.py"
      provides: "An enhanced FileReadRequest model and read_files function supporting pattern-based reading."
      contains:
        - "class FileReadRequest(BaseModel):"
        - "read_to_next_pattern: Optional[str] = None"
        - "def read_files("
  key_links:
    - from: "Parameter validation logic within `read_files`"
      to: "Structured error message formatting"
      via: "Conditional checks for conflicting or invalid parameters"
      pattern: "if file_request.end_line and file_request.read_to_next_pattern:"
    - from: "Core file reading loop in `read_files`"
      to: "Regex scanning for `read_to_next_pattern`"
      via: "Iterating through file lines after `start_line`"
      pattern: "re.search(file_request.read_to_next_pattern, line)"
---

<objective>
Enhance the `read_files` tool in `src/fs_mcp/server.py` to support "section-aware" reading. This involves adding a `read_to_next_pattern` parameter to allow reading from a start line until a specified regex pattern is found, along with robust error handling for invalid parameter combinations.

Purpose: To allow agents to read logical blocks of code (like a function or a class) without needing to know the exact end line number, making their interaction with the file system more efficient and intuitive.
Output: An updated `src/fs_mcp/server.py` with the modified `FileReadRequest` model and `read_files` function.
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
  <name>Task 1: Update `FileReadRequest` Model and Add Parameter Validation</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Locate the `FileReadRequest(BaseModel)` class definition in `src/fs_mcp/server.py`.
    2.  Add the new optional field: `read_to_next_pattern: Optional[str] = None`.
    3.  In the `read_files` function, iterate through each `file_request` and implement parameter validation logic *before* reading the file.
    4.  **Validation 1 (Mutual Exclusion):** Check if both `end_line` and `read_to_next_pattern` are provided. If so, return the structured error message as defined in `05-CONTEXT.md`.
    5.  **Validation 2 (Requires `start_line`):** Check if `read_to_next_pattern` is provided but `start_line` is not. If so, return a structured error.
    6.  The existing `start_line` > file length check should be preserved and enhanced to include the tip: "Tip: Use grep_content to find valid line numbers first".
  </action>
  <verify>
    - Run the server and inspect the OpenAPI docs (`/docs`) to confirm the `read_to_next_pattern` field is present in the schema for `FileReadRequest`.
    - Manually test the tool (or write a unit test) that calls `read_files` with both `end_line` and `read_to_next_pattern` set, and verify it returns the specified structured error.
  </verify>
  <done>
    The `FileReadRequest` model is updated, and the `read_files` function correctly validates the new parameter combinations, returning structured errors for invalid requests.
  </done>
</task>

<task type="auto">
  <name>Task 2: Implement Section-Aware Reading Logic</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Inside the `read_files` function, after the validation, modify the file reading logic.
    2.  If a `file_request` includes `read_to_next_pattern`, implement the following behavior:
        a. Read the file line by line, starting from `start_line`.
        b. Begin scanning for the regex pattern on the line *after* `start_line` (`start_line + 1`).
        c. If the pattern is found, stop reading and return the content from `start_line` up to (but not including) the line with the pattern.
        d. If the pattern is not found by the end of the file (EOF), return the content from `start_line` to the EOF.
        e. If EOF is reached without finding the pattern, append the informational note to the output, formatted exactly as: `Note: Pattern '{pattern}' not found after line {start_line}. Read to end of file.`
    3.  Ensure the implementation is memory-efficient and correctly handles 1-based line numbering from the request.
  </action>
  <verify>
    - Create a test file.
    - Call `read_files` with a `start_line` and a `read_to_next_pattern` that exists in the file. Verify the returned content is the correct slice.
    - Call `read_files` with a pattern that does *not* exist. Verify the content is from `start_line` to EOF and that the specified `Note:` is present in the output.
  </verify>
  <done>
    The `read_files` tool correctly reads a file section from a given start line to the next occurrence of a regex pattern, or to the end of the file if the pattern is not found.
  </done>
</task>

<task type="auto">
  <name>Task 3: Update `read_files` Docstring</name>
  <files>
    - src/fs_mcp/server.py
  </files>
  <action>
    1.  Locate the docstring for the `read_files` function.
    2.  Update the docstring for the `FileReadRequest` model to explain the new `read_to_next_pattern` parameter.
    3.  Clearly describe its behavior, its relationship with `start_line`, and that it is mutually exclusive with `end_line`.
    4.  Provide a clear example of how to use it.
  </action>
  <verify>
    - Check the OpenAPI documentation (`/docs`) and ensure the new parameter and its description are rendered correctly and are easy to understand.
  </verify>
  <done>
    The `read_files` tool's documentation is updated to reflect the new section-aware reading capability.
  </done>
</task>

</tasks>

<verification>
1.  The `read_files` tool can successfully read a section of a file using `start_line` and `read_to_next_pattern`.
2.  The tool provides the specified informational note when the pattern is not found and reading proceeds to EOF.
3.  The tool returns specific, structured errors for invalid parameter combinations (`end_line` with `read_to_next_pattern`, or `read_to_next_pattern` without `start_line`).
</verification>

<success_criteria>
The `read_files` tool is enhanced with reliable and well-documented section-aware reading capabilities, improving an agent's ability to explore files efficiently.
</success_criteria>

<output>
After completion, create `.planning/phases/05-enhance-section-aware-reading/05-1-SUMMARY.md`
</output>
