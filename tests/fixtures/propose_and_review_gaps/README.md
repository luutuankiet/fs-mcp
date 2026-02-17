# propose_and_review Gap Testing Fixtures

**Purpose:** Test fixtures to verify weak model behavior before/after documentation fixes.

**Related:** LOG-009 (Cross-Model Schema Analysis)

## Test Structure

```
propose_and_review_gaps/
├── README.md                    # This file
├── PROMPTS.md                   # Human instructions to trigger each scenario
├── gap1_append/                 # Gap 1: Append pattern undocumented
│   ├── sample_log.md           # File to append to
│   └── expected_result.md      # What success looks like
├── gap2_mode_exclusivity/       # Gap 2: Mode mutual exclusivity
│   ├── sample_code.py          # File with multiple edit targets
│   └── expected_result.py      # What success looks like
├── gap3_required_params/        # Gap 3: Required params per mode
│   └── (uses gap1 fixtures)
└── gap4_batch_priority/         # Gap 4: Batch not prioritized
    ├── sample_code.py          # File needing 3+ edits
    └── expected_result.py      # What success looks like
```

## How to Use

1. Copy fixture file to a temp location
2. Follow prompt in PROMPTS.md for that gap
3. Observe agent behavior (tool calls, errors, recovery)
4. Compare result against expected_result
5. Record: turns taken, errors encountered, final success/failure

## Success Criteria

| Gap | Before Fix | After Fix |
|-----|------------|-----------|
| Gap 1 (Append) | Agent fails with "Found N matches" or overwrites file | Agent uses tail-anchor pattern, 2 tool calls |
| Gap 2 (Mode) | Agent passes both match_text AND edits | Agent picks one mode cleanly |
| Gap 3 (Params) | Agent calls with just path, gets error | Agent provides all required params |
| Gap 4 (Batch) | Agent makes 3 separate calls | Agent batches into 1 call |