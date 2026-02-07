"""
GSD-Lite Context Analyzer

Provides context-aware analysis of GSD-Lite WORK.md files for the Housekeeping Agent.
Implements the "Mask -> Scan -> Unmask" pipeline from LOG-026 to prevent false positives
when documentation contains examples of the very patterns being detected (the "Quine Paradox").

Key Features:
1. Masks code blocks and inline code before signal detection
2. Detects Tier 1 (high confidence) and Tier 2 (medium confidence) semantic signals
3. Outputs structured JSON for machine consumption by agents

Usage:
    from fs_mcp.gsd_lite_analyzer import analyze_gsd_logs
    
    result = analyze_gsd_logs("gsd-lite/WORK.md")
    print(json.dumps(result, indent=2))

References:
    - LOG-025: Original spec for signal detection
    - LOG-026: Quine Paradox fix (context-aware exclusion)
"""

import re
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

# ============================================================================
# CONFIGURATION: Signal Patterns from LOG-025/026
# ============================================================================

# Tier 1 Patterns: High Confidence - Auto-Flag (deterministic, zero ambiguity)
TIER_1_PATTERNS = {
    "strikethrough": r"~~[^~]+~~",                          # Title strikethrough
    "superseded_by": r"SUPERSEDED\s*BY[:\s]+LOG-\d+",       # Explicit tag
    "deprecated_tag": r"\[DEPRECATED\]|\[OBSOLETE\]|\[ARCHIVED\]",
    "do_not_follow": r"[Dd]o\s*[Nn][Oo][Tt]\s*follow",
    "status_obsolete": r"[Ss]tatus[:\s]*(obsolete|deprecated|superseded|abandoned)",
    "killed": r"\b(killed|scrapped|abandoned|discarded)\b",
}

# Tier 2 Patterns: Medium Confidence - Flag for Review (needs human context)
TIER_2_PATTERNS = {
    "depends_on": r"\*{0,2}[Dd]epends\s*[Oo]n:?\*{0,2}[:\s]*(LOG-\d+)",
    "supersedes": r"\b(supersedes?|superseding)\b",
    "replaces": r"\b(replaces?|replacing)\b",
    "pivot": r"\b(pivot(ed|ing)?|pivotal)\b",
    "hit_wall": r"hit\s*(a\s*)?(wall|dead\s*end|roadblock)",
    "decided_not_to": r"decided\s*(not\s*to|against)",
    "options_evaluated": r"[Oo]ption\s*[A-Z1-9][:\s]",
}

# Header-only patterns (only valid when found in log header lines)
HEADER_ONLY_SIGNALS = {"strikethrough", "superseded_by"}

# Log header regex - permissive to capture various task naming conventions
# Matches: ### [LOG-NNN] - [TYPE] - Title - Task: TASK-ID
LOG_HEADER_PATTERN = re.compile(
    r"^###\s*\[LOG-(\d+)\]\s*-\s*\[([A-Z]+)\]\s*-\s*(.*?)\s*-\s*Task:\s*([A-Za-z][A-Za-z0-9_-]*)",
    re.MULTILINE
)

# Simpler fallback if Task: is missing
LOG_HEADER_FALLBACK = re.compile(
    r"^###\s*\[LOG-(\d+)\]\s*-\s*\[([A-Z]+)\]\s*-\s*(.+?)(?:\s*-\s*Task:\s*([A-Za-z][A-Za-z0-9_-]*))?$",
    re.MULTILINE
)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Signal:
    """A detected semantic signal."""
    line: int
    signal_type: str
    tier: int
    match_text: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LogEntry:
    """A parsed GSD-Lite log entry with detected signals."""
    log_id: str
    entry_type: str
    title: str
    task: Optional[str]
    start_line: int
    end_line: int
    tokens: int = 0
    signals: dict = field(default_factory=lambda: {"tier_1": [], "tier_2": []})
    
    def to_dict(self) -> dict:
        return {
            "log_id": self.log_id,
            "type": self.entry_type,
            "title": self.title,
            "task": self.task,
            "tokens": self.tokens,
            "lines": [self.start_line, self.end_line],
            "signals": self.signals,
        }


@dataclass
class AnalysisResult:
    """Complete analysis result for a WORK.md file."""
    file_path: str
    total_tokens: int = 0
    total_logs: int = 0
    tier_1_flags: int = 0
    tier_2_flags: int = 0
    logs: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "summary": {
                "file_path": self.file_path,
                "total_tokens": self.total_tokens,
                "total_logs": self.total_logs,
                "tier_1_flags": self.tier_1_flags,
                "tier_2_flags": self.tier_2_flags,
            },
            "logs": [log.to_dict() for log in self.logs],
        }


# ============================================================================
# MASKING PIPELINE (LOG-026 Fix)
# ============================================================================

def mask_exclusion_zones(text: str) -> tuple[str, list[str]]:
    """
    Replaces code blocks with placeholders to prevent regex matching on examples.
    
    This is the core fix for the "Quine Paradox" - when documentation contains
    examples of the very patterns we're trying to detect.
    
    Crucially: Preserves newlines so line numbers remain accurate.
    
    Args:
        text: Raw markdown content
        
    Returns:
        tuple of (masked_text, list_of_placeholders)
        
    Example:
        >>> text = "See `~~example~~` for strikethrough"
        >>> masked, _ = mask_exclusion_zones(text)
        >>> "~~" in masked
        False  # The inline code was masked
    """
    placeholders = []
    
    def create_placeholder(match: re.Match) -> str:
        content = match.group(0)
        placeholders.append(content)
        # Replace with safe string, keeping newlines for accurate line counts
        placeholder = f"__MASKED_{len(placeholders)-1}__"
        newline_count = content.count("\n")
        return placeholder + ("\n" * newline_count)
    
    # Order matters: mask fenced blocks first (they may contain inline code)
    
    # 1. Mask Fenced Code Blocks (```...```)
    # Pattern: Triple backticks, optional language, content, triple backticks
    text = re.sub(r"```[\s\S]*?```", create_placeholder, text)
    
    # 2. Mask Inline Code (`...`)
    # Pattern: Single/double backticks, non-backtick content, matching backticks
    # Handles both `code` and ``code with `backticks` inside``
    text = re.sub(r"``[^`]+``", create_placeholder, text)  # Double backticks first
    text = re.sub(r"`[^`\n]+`", create_placeholder, text)   # Then single backticks
    
    # 3. (Optional) Mask blockquotes if they contain examples
    # Currently not masking blockquotes as they often contain real signals
    # Uncomment if false positives appear in blockquotes:
    # text = re.sub(r"^>.*$", create_placeholder, text, flags=re.MULTILINE)
    
    return text, placeholders


def unmask_content(masked_text: str, placeholders: list[str]) -> str:
    """
    Restores masked content (for debugging/verification).
    
    Args:
        masked_text: Text with __MASKED_N__ placeholders
        placeholders: Original content list from mask_exclusion_zones
        
    Returns:
        Original text with placeholders restored
    """
    result = masked_text
    for i, original in enumerate(placeholders):
        # Only replace the placeholder part, preserve any trailing newlines
        placeholder = f"__MASKED_{i}__"
        # Find and replace, accounting for newlines that were added
        result = result.replace(placeholder, original.replace("\n", ""), 1)
    return result


# ============================================================================
# SIGNAL DETECTION
# ============================================================================

def detect_signals_in_content(
    content: str,
    start_line_offset: int = 0,
    header_line: Optional[str] = None
) -> dict:
    """
    Detects Tier 1 and Tier 2 signals in masked content.
    
    Args:
        content: The log entry content (should be pre-masked)
        start_line_offset: Line number where this content starts in the file
        header_line: The header line (for header-only signal detection)
        
    Returns:
        dict with "tier_1" and "tier_2" lists of signal descriptions
    """
    signals = {"tier_1": [], "tier_2": []}
    
    # Mask the content to prevent false positives
    masked_content, _ = mask_exclusion_zones(content)
    lines = masked_content.split("\n")
    
    for i, line in enumerate(lines):
        line_num = start_line_offset + i + 1  # 1-indexed
        is_header = line.strip().startswith("### [LOG-")
        
        # Tier 1 patterns
        for signal_name, pattern in TIER_1_PATTERNS.items():
            # Header-only signals must be on header lines
            if signal_name in HEADER_ONLY_SIGNALS and not is_header:
                continue
                
            matches = re.findall(pattern, line)
            for match in matches:
                match_text = match if isinstance(match, str) else match[0] if match else ""
                signals["tier_1"].append(f"{signal_name}: {match_text} (L{line_num})")
        
        # Tier 2 patterns (always check body, flag for review)
        for signal_name, pattern in TIER_2_PATTERNS.items():
            matches = re.findall(pattern, line)
            for match in matches:
                match_text = match if isinstance(match, str) else match[0] if match else ""
                signals["tier_2"].append(f"{signal_name}: {match_text} (L{line_num})")
    
    return signals


def detect_signals_in_header(header_line: str, line_num: int) -> dict:
    """
    Detects signals specifically in a log header line.
    
    Header-only signals (strikethrough, superseded_by) are only valid here.
    This is the "Structural Anchoring" strategy from LOG-026.
    
    Args:
        header_line: The full header line text
        line_num: 1-indexed line number
        
    Returns:
        dict with "tier_1" and "tier_2" lists of signal descriptions
    """
    signals = {"tier_1": [], "tier_2": []}
    
    # Header-only Tier 1 signals
    for signal_name in HEADER_ONLY_SIGNALS:
        pattern = TIER_1_PATTERNS[signal_name]
        matches = re.findall(pattern, header_line)
        for match in matches:
            match_text = match if isinstance(match, str) else str(match)
            signals["tier_1"].append(f"{signal_name}: {match_text}")
    
    return signals


# ============================================================================
# LOG PARSING
# ============================================================================

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Estimates token count for a text string.
    
    Uses tiktoken if available, falls back to char/4 estimate.
    """
    try:
        import tiktoken
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        # Fallback: rough estimate of 1 token per 4 characters
        return len(text) // 4


def parse_log_entries(content: str) -> list[LogEntry]:
    """
    Parses all LOG entries from WORK.md content.
    
    Finds all `### [LOG-NNN]` headers and extracts:
    - Log ID, type, title, task
    - Line range (start to next header or EOF)
    - Token count for the entry
    
    Args:
        content: Full WORK.md file content
        
    Returns:
        List of LogEntry objects
    """
    lines = content.split("\n")
    entries = []
    
    # Find all header positions
    header_positions = []
    for i, line in enumerate(lines):
        if line.strip().startswith("### [LOG-"):
            header_positions.append(i)
    
    # Parse each header and determine range
    for idx, header_line_idx in enumerate(header_positions):
        header_line = lines[header_line_idx]
        
        # Try full pattern first
        match = LOG_HEADER_PATTERN.match(header_line.strip())
        if not match:
            match = LOG_HEADER_FALLBACK.match(header_line.strip())
        
        if match:
            log_num = match.group(1)
            log_type = match.group(2)
            title = match.group(3).strip()
            task = match.group(4) if len(match.groups()) >= 4 and match.group(4) else None
            
            # Determine end line (next header or EOF)
            if idx + 1 < len(header_positions):
                end_line_idx = header_positions[idx + 1] - 1
            else:
                end_line_idx = len(lines) - 1
            
            # Extract content for this entry
            entry_content = "\n".join(lines[header_line_idx:end_line_idx + 1])
            tokens = count_tokens(entry_content)
            
            # Detect signals
            header_signals = detect_signals_in_header(header_line, header_line_idx + 1)
            body_signals = detect_signals_in_content(
                entry_content, 
                start_line_offset=header_line_idx
            )
            
            # Merge signals
            combined_signals = {
                "tier_1": header_signals["tier_1"] + body_signals["tier_1"],
                "tier_2": header_signals["tier_2"] + body_signals["tier_2"],
            }
            
            entry = LogEntry(
                log_id=f"LOG-{log_num}",
                entry_type=log_type,
                title=title,
                task=task,
                start_line=header_line_idx + 1,  # 1-indexed
                end_line=end_line_idx + 1,        # 1-indexed
                tokens=tokens,
                signals=combined_signals,
            )
            entries.append(entry)
    
    return entries


# ============================================================================
# MAIN API
# ============================================================================

def analyze_gsd_logs(
    file_path: str,
    format: str = "json"
) -> dict | str:
    """
    Main entry point: Analyze a GSD-Lite WORK.md file.
    
    Implements the full pipeline from LOG-025/026:
    1. Read file
    2. Parse log headers
    3. Mask exclusion zones (code blocks, inline code)
    4. Detect Tier 1/2 signals
    5. Return structured output
    
    Args:
        file_path: Path to WORK.md file
        format: "json" (dict) or "table" (formatted string)
        
    Returns:
        Analysis result as dict (json) or formatted string (table)
        
    Example:
        >>> result = analyze_gsd_logs("gsd-lite/WORK.md")
        >>> print(result["summary"]["tier_1_flags"])
        3
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    content = path.read_text(encoding="utf-8")
    
    # Parse all log entries
    entries = parse_log_entries(content)
    
    # Build result
    result = AnalysisResult(
        file_path=str(path),
        total_logs=len(entries),
        logs=entries,
    )
    
    # Calculate totals
    for entry in entries:
        result.total_tokens += entry.tokens
        result.tier_1_flags += len(entry.signals["tier_1"])
        result.tier_2_flags += len(entry.signals["tier_2"])
    
    if format == "json":
        return result.to_dict()
    elif format == "table":
        return _format_as_table(result)
    else:
        return result.to_dict()


def _format_as_table(result: AnalysisResult) -> str:
    """Format analysis result as a human-readable table."""
    lines = [
        f"# Analysis: {result.file_path}",
        f"",
        f"**Summary:** {result.total_logs} logs | {result.total_tokens:,} tokens | {result.tier_1_flags} T1 flags | {result.tier_2_flags} T2 flags",
        f"",
        f"| Log ID | Type | Task | Tokens | T1 Signals | T2 Signals |",
        f"|--------|------|------|--------|------------|------------|",
    ]
    
    for log in result.logs:
        t1_count = len(log.signals["tier_1"])
        t2_count = len(log.signals["tier_2"])
        t1_display = f"⚠️ {t1_count}" if t1_count > 0 else "0"
        t2_display = f"📋 {t2_count}" if t2_count > 0 else "0"
        
        lines.append(
            f"| {log.log_id} | {log.entry_type} | {log.task or '-'} | {log.tokens:,} | {t1_display} | {t2_display} |"
        )
    
    # Add flagged entries detail
    flagged = [log for log in result.logs if log.signals["tier_1"]]
    if flagged:
        lines.extend([
            f"",
            f"## ⚠️ Tier 1 Flags (High Confidence)",
            f"",
        ])
        for log in flagged:
            lines.append(f"### {log.log_id}")
            for signal in log.signals["tier_1"]:
                lines.append(f"- {signal}")
    
    return "\n".join(lines)


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python -m fs_mcp.gsd_lite_analyzer <path/to/WORK.md> [--format json|table]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    output_format = "json"
    
    if "--format" in sys.argv:
        idx = sys.argv.index("--format")
        if idx + 1 < len(sys.argv):
            output_format = sys.argv[idx + 1]
    
    try:
        result = analyze_gsd_logs(file_path, format=output_format)
        if isinstance(result, dict):
            print(json.dumps(result, indent=2))
        else:
            print(result)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)