#!/usr/bin/env python3
"""Quick debug script for the depends_on pattern."""
import re

pattern = r"\*{0,2}[Dd]epends\s*[Oo]n\*{0,2}[:\s]*(LOG-\d+)"
test_strings = [
    "**Depends On:** LOG-005",
    "Depends On: LOG-005",
    "depends on LOG-005",
    "**Depends On**: LOG-005",
]

for s in test_strings:
    matches = re.findall(pattern, s)
    print(f"Input: {s!r}")
    print(f"Matches: {matches}")
    print()