"""
Tests for GSD-Lite Analyzer — Quine Paradox Cases

Tests the context-aware masking pipeline that prevents false positives
when documentation contains examples of the patterns being detected.

Key test cases:
1. Real signals in headers should be detected
2. Code blocks containing patterns should be masked (no false positives)
3. Inline code containing patterns should be masked (no false positives)
4. Tier 1 vs Tier 2 classification is correct
"""

import pytest
from pathlib import Path
from fs_mcp.gsd_lite_analyzer import (
    mask_exclusion_zones,
    detect_signals_in_header,
    detect_signals_in_content,
    parse_log_entries,
    analyze_gsd_logs,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "quine_test_work.md"


class TestMaskExclusionZones:
    """Tests for the masking pipeline."""

    def test_masks_fenced_code_blocks(self):
        text = "Before\n```python\n~~fake~~\n```\nAfter"
        masked, placeholders = mask_exclusion_zones(text)
        
        assert "~~fake~~" not in masked
        assert "__MASKED_" in masked
        assert len(placeholders) == 1

    def test_masks_inline_code(self):
        text = "Example: `~~not a signal~~` here"
        masked, placeholders = mask_exclusion_zones(text)
        
        assert "~~not a signal~~" not in masked
        assert len(placeholders) == 1

    def test_preserves_line_count(self):
        text = "Line 1\n```\nLine 3\nLine 4\n```\nLine 6"
        masked, _ = mask_exclusion_zones(text)
        
        # Masking should preserve newlines for accurate line numbers
        assert masked.count("\n") == text.count("\n")

    def test_real_signal_not_masked(self):
        text = "### [LOG-001] - ~~Real Signal~~ - Task: X"
        masked, placeholders = mask_exclusion_zones(text)
        
        # No code blocks = nothing masked
        assert "~~Real Signal~~" in masked
        assert len(placeholders) == 0


class TestSignalDetection:
    """Tests for Tier 1 and Tier 2 signal detection."""

    def test_detects_strikethrough_in_header(self):
        header = "### [LOG-001] - [DECISION] - ~~Dead Approach~~ - Task: X"
        signals = detect_signals_in_header(header, 1)
        
        assert len(signals["tier_1"]) == 1
        assert "strikethrough" in signals["tier_1"][0]

    def test_detects_superseded_by_in_header(self):
        header = "### [LOG-001] - Title - Task: X - **SUPERSEDED BY: LOG-002**"
        signals = detect_signals_in_header(header, 1)
        
        assert len(signals["tier_1"]) == 1
        assert "superseded_by" in signals["tier_1"][0]

    def test_tier2_depends_on(self):
        content = "**Depends On:** LOG-005"
        signals = detect_signals_in_content(content, start_line_offset=10)
        
        assert len(signals["tier_2"]) >= 1
        assert any("depends_on" in s for s in signals["tier_2"])

    def test_tier2_hit_wall(self):
        content = "We hit a wall with this approach."
        signals = detect_signals_in_content(content, start_line_offset=0)
        
        assert any("hit_wall" in s for s in signals["tier_2"])


class TestQuineParadox:
    """
    The critical tests: documentation about signals should NOT trigger detection.
    This is the "Quine Paradox" — code that describes itself.
    """

    def test_inline_code_example_not_detected(self):
        # LOG-004 in fixture has: `~~this is not a real signal~~`
        content = "Example of strikethrough: `~~this is not a real signal~~`"
        signals = detect_signals_in_content(content, start_line_offset=0)
        
        # Should NOT detect strikethrough (it's in inline code)
        tier1_types = [s.split(":")[0] for s in signals["tier_1"]]
        assert "strikethrough" not in tier1_types

    def test_code_block_patterns_not_detected(self):
        content = '''Here's the pattern:
```python
PATTERNS = {"strikethrough": r"~~[^~]+~~"}
title = "~~Fake Title~~"
```
End of example.'''
        signals = detect_signals_in_content(content, start_line_offset=0)
        
        # Should NOT detect any strikethrough (all in code block)
        tier1_types = [s.split(":")[0] for s in signals["tier_1"]]
        assert "strikethrough" not in tier1_types

    def test_real_vs_documented_signals(self):
        """Integration test using the full fixture file."""
        if not FIXTURE_PATH.exists():
            pytest.skip("Fixture file not found")
        
        result = analyze_gsd_logs(str(FIXTURE_PATH))
        logs_by_id = {log["log_id"]: log for log in result["logs"]}
        
        # LOG-001: No signals (clean log)
        assert len(logs_by_id["LOG-001"]["signals"]["tier_1"]) == 0
        
        # LOG-002: Real superseded (header has ~~...~~ AND SUPERSEDED BY)
        log2_t1 = logs_by_id["LOG-002"]["signals"]["tier_1"]
        assert len(log2_t1) >= 1, "LOG-002 should have Tier 1 signals"
        
        # LOG-004: The Quine case — discusses patterns but shouldn't trigger
        log4_t1 = logs_by_id["LOG-004"]["signals"]["tier_1"]
        # Should be 0 — all examples are in code blocks or inline code
        assert len(log4_t1) == 0, f"LOG-004 false positive! Got: {log4_t1}"
        
        # LOG-005: Real superseded
        log5_t1 = logs_by_id["LOG-005"]["signals"]["tier_1"]
        assert len(log5_t1) >= 1, "LOG-005 should have Tier 1 signals"


class TestAnalyzeGsdLogs:
    """Tests for the main entry point."""

    def test_returns_summary(self):
        if not FIXTURE_PATH.exists():
            pytest.skip("Fixture file not found")
        
        result = analyze_gsd_logs(str(FIXTURE_PATH))
        
        assert "summary" in result
        assert "logs" in result
        assert result["summary"]["total_logs"] == 5

    def test_table_format(self):
        if not FIXTURE_PATH.exists():
            pytest.skip("Fixture file not found")
        
        result = analyze_gsd_logs(str(FIXTURE_PATH), format="table")
        
        assert isinstance(result, str)
        assert "LOG-001" in result
        assert "|" in result  # Table formatting