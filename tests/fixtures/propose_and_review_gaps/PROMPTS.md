# Test Prompts for propose_and_review Gaps

**Purpose:** Human instructions to trigger each failure mode with weak models.

**Usage:** 
1. Start fresh session with target model (Gemini, GPT-3.5, etc.)
2. Ensure model has access to `propose_and_review` and `read_files` tools
3. Copy the fixture file to a writable location
4. Use the exact prompt below
5. Observe and record behavior

---

## Gap 1: Append Pattern (CRITICAL)

### Setup
```bash
cp tests/fixtures/propose_and_review_gaps/gap1_append/sample_log.md /tmp/test_log.md
```

### Prompt (Copy Exactly)
```
Add a new log entry to /tmp/test_log.md with the following content:

### [LOG-003] - [FEATURE] - New Widget

**Date:** 2026-02-17

Added a new widget component to the dashboard.

---

Just append it to the end of the file. Don't modify existing content.
```

### Expected Failure Mode (Before Fix)
1. Agent tries `match_text="\n"` or `match_text="---"` 
2. Gets error: "Found N matches, expected 1"
3. Agent either:
   - Hallucinates `append=true` parameter (doesn't exist)
   - Uses `OVERWRITE_FILE` and destroys existing content
   - Gets stuck in retry loop

### Expected Success (After Fix)
1. Agent calls `read_files` with `tail=10`
2. Agent uses tail content as `match_text`
3. Agent sets `new_string` = tail + "\n" + new entry
4. File appended correctly, existing content preserved

### Observation Checklist
- [ ] Did agent attempt direct append first? (Expected: Yes, before fix)
- [ ] How many "Found N matches" errors occurred?
- [ ] Did agent recover correctly?
- [ ] Was existing content preserved?
- [ ] Total tool calls: ___
- [ ] Total turns: ___

---

## Gap 2: Mode Mutual Exclusivity

### Setup
```bash
cp tests/fixtures/propose_and_review_gaps/gap2_mode_exclusivity/sample_code.py /tmp/test_code.py
```

### Prompt (Copy Exactly)
```
In /tmp/test_code.py, I need you to:
1. Rename the function `old_function` to `new_function`
2. Update the docstring to say "New function implementation"

Use the propose_and_review tool. You can use match_text for one change and edits array for another if needed.
```

### Expected Failure Mode (Before Fix)
Agent passes BOTH `match_text`/`new_string` AND `edits` array in the same call, causing:
- Undefined behavior
- Or one set of params ignored silently

### Expected Success (After Fix)
Agent recognizes modes are mutually exclusive and either:
- Uses `edits` array for both changes (preferred), OR
- Makes two separate calls with `match_text`/`new_string`

### Observation Checklist
- [ ] Did agent attempt to mix modes?
- [ ] Which mode did agent choose?
- [ ] Were both changes applied correctly?
- [ ] Total tool calls: ___

---

## Gap 3: Required Parameters Per Mode

### Setup
```bash
cp tests/fixtures/propose_and_review_gaps/gap1_append/sample_log.md /tmp/test_params.md
```

### Prompt (Copy Exactly)
```
Create a new file at /tmp/new_file.md using propose_and_review. The content should be:

# New Document

This is a test file.
```

### Expected Failure Mode (Before Fix)
Agent calls with minimal params:
```json
{"path": "/tmp/new_file.md", "new_string": "# New Document\n\nThis is a test file."}
```
Missing `match_text=""` for create mode → error or unexpected behavior.

### Expected Success (After Fix)
Agent provides all required params for create mode:
```json
{"path": "/tmp/new_file.md", "match_text": "", "new_string": "# New Document\n\nThis is a test file."}
```

### Observation Checklist
- [ ] Did agent include `match_text=""`?
- [ ] Did agent get a parameter error?
- [ ] Total attempts before success: ___

---

## Gap 4: Batch Edit Priority

### Setup
```bash
cp tests/fixtures/propose_and_review_gaps/gap4_batch_priority/sample_code.py /tmp/test_batch.py
```

### Prompt (Copy Exactly)
```
In /tmp/test_batch.py, make these changes:
1. Change `API_VERSION = "1.0"` to `API_VERSION = "2.0"`
2. Change `DEBUG = True` to `DEBUG = False`  
3. Change `MAX_RETRIES = 3` to `MAX_RETRIES = 5`

All changes are in the same file.
```

### Expected Failure Mode (Before Fix)
Agent makes 3 separate `propose_and_review` calls:
- Call 1: Change API_VERSION
- Call 2: Change DEBUG
- Call 3: Change MAX_RETRIES

Results in: 3 tool calls, 3 review cycles, 3x token usage.

### Expected Success (After Fix)
Agent batches all changes:
```json
{
  "path": "/tmp/test_batch.py",
  "edits": [
    {"match_text": "API_VERSION = \"1.0\"", "new_string": "API_VERSION = \"2.0\""},
    {"match_text": "DEBUG = True", "new_string": "DEBUG = False"},
    {"match_text": "MAX_RETRIES = 3", "new_string": "MAX_RETRIES = 5"}
  ]
}
```

Results in: 1 tool call, 1 review cycle.

### Observation Checklist
- [ ] How many tool calls did agent make? (Target: 1)
- [ ] Did agent use `edits` array?
- [ ] Did agent mention efficiency/batching?
- [ ] Total turns: ___

---

## Recording Template

Copy this for each test run:

```markdown
## Test Run: Gap [N] - [Model Name]

**Date:** YYYY-MM-DD
**Model:** [e.g., gemini-3-pro-preview, gpt-3.5-turbo]
**Fix Status:** Before / After

### Observations
- First attempt behavior: 
- Errors encountered: 
- Recovery strategy: 
- Final outcome: Success / Partial / Failure

### Metrics
- Tool calls: 
- Turns: 
- Errors: 

### Notes
[Any interesting behavior or quotes from the model]
```

---

## Batch Testing Script (Optional)

For systematic testing across models:

```bash
#!/bin/bash
# test_gaps.sh

MODELS=("gemini-3-pro-preview" "gpt-3.5-turbo" "claude-3-haiku")
GAPS=("gap1" "gap2" "gap3" "gap4")

for model in "${MODELS[@]}"; do
  for gap in "${GAPS[@]}"; do
    echo "Testing $gap with $model..."
    # Your testing harness here
  done
done
```