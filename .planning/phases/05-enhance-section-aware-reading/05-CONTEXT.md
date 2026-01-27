# Phase 5: enhance Section-Aware Reading - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Enhance the `read_files` tool to intelligently read bounded sections from structured files. The agent will provide a `start_line` and a `read_to_next_pattern` (regex), and the server will calculate the end boundary automatically. This simplifies the agent's workflow by removing the need for manual boundary calculation. The phase also includes enhancing the `grep_content` tool to provide a `section_end_hint`.

</domain>

<decisions>
## Implementation Decisions

### `read_files` Boundary Definition
- **Scan Start:** The scan for the `read_to_next_pattern` will begin on the line *after* the provided `start_line` (`start_line + 1`). This ensures the content on `start_line` is always included in the output.
- **Pattern Not Found:** If the pattern is not found after `start_line`, the tool will read to the end of the file (EOF). A note will be included in the output to inform the agent of this behavior.
- **Invalid `start_line`:** If the `start_line` is greater than the total lines in the file, the tool will return a structured, actionable error message.

### `grep_content` Enhancement: `section_end_hint`
- **Agent Flexibility:** The `grep_content` tool will accept an optional parameter, `section_patterns` (a list of regex strings), to generate a `section_end_hint`.
- **Default Behavior:** If `section_patterns` is not provided (`None`), the tool will fall back to a default static list of common patterns to generate the hint.
- **Default Patterns:** The static list will be `[r"^## ", r"^# ", r"^\[LOG-"]`, checked in that order.
- **Disabling Hints:** To disable hints entirely, the agent must pass an empty list (`section_patterns=[]`).
- **Docstring:** The tool's docstring will be updated to clearly explain this behavior with examples.

### Error Handling Format
- All parameter validation errors will follow a structured, multi-line text format to help agents self-correct.
- **Format:**
  ```
  Error: [Short description]

  You provided: [echo back the parameters]
  Problem: [why this is invalid]
  Fix: [how to correct it]
  ```
- This format will be used for cases like conflicting parameters (`end_line` and `read_to_next_pattern`), missing required parameters (`start_line`), and invalid values (`start_line` > file length).

### Claude's Discretion
- The specific implementation of the regex scanning and file reading can be determined by the planning and execution agents, as long as it adheres to the behaviors defined above.

</decisions>

<specifics>
## Specific Ideas

- The error message for a `start_line` exceeding file length should include a tip: "Tip: Use grep_content to find valid line numbers first".
- The informational note for when a pattern is not found should be formatted as: `Note: Pattern '{pattern}' not found after line {start_line}. Read to end of file.`

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-enhance-section-aware-reading*
*Context gathered: 2026-01-27*
