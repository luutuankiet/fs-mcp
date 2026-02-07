# Test WORK.md — Quine Paradox Cases

## 3. Atomic Session Log

### [LOG-001] - [DECISION] - Initial Setup - Task: SETUP-001
**Status:** ✅ COMPLETE
Basic setup, no signals here.

### [LOG-002] - [DECISION] - ~~Abandoned Approach~~ - Task: FEAT-001 - **SUPERSEDED BY: LOG-003**
**Status:** ❌ SUPERSEDED
This log is genuinely superseded. Should trigger Tier 1.

### [LOG-003] - [DECISION] - Better Approach - Task: FEAT-001
**Status:** ✅ COMPLETE
**Depends On:** LOG-002
This replaces the previous approach. Has Tier 2 signals.

### [LOG-004] - [PLAN] - Document Signal Patterns - Task: DOCS-001
**Status:** ✅ COMPLETE

This log discusses signals but should NOT trigger false positives:

Example of strikethrough: `~~this is not a real signal~~`
Example of tag: `SUPERSEDED BY: LOG-999`

```python
# Code block should be masked
PATTERNS = {
    "strikethrough": r"~~[^~]+~~",
    "superseded": r"SUPERSEDED BY: LOG-\d+",
}
title = "~~Fake Title~~"
```

The patterns above are documentation, not real signals.

### [LOG-005] - [DECISION] - ~~Another Dead End~~ - Task: FEAT-002
**Status:** ❌ SUPERSEDED
Decided not to pursue this. Hit a wall with the API.