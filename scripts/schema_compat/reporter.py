"""
Schema Compatibility Reporter

Generates output in formats useful for both engineers and agents:
- JSON report for programmatic consumption
- Terminal diff for human DX

Reference: LOG-003 Section 3.4, Section 5
"""

import json
from datetime import datetime, timezone
from typing import Any


def generate_report(
    tool_name: str,
    original: dict,
    transformed: dict,
    issues: list[dict],
    changes: list[str],
) -> dict:
    """
    Generate JSON report for a single tool.
    
    Args:
        tool_name: Name of the tool
        original: Raw schema before transformation
        transformed: Schema after transformation
        issues: List of issues found in original schema
        changes: List of transformations applied
        
    Returns:
        Structured report dict suitable for JSON serialization
    """
    return {
        "tool": tool_name,
        "status": "COMPATIBLE" if not issues else "INCOMPATIBLE",
        "issues": issues,
        "transforms_applied": changes,
        "original_schema": original,
        "transformed_schema": transformed,
    }


def generate_summary_report(tool_reports: list[dict]) -> dict:
    """
    Generate summary report for all tools.
    
    Args:
        tool_reports: List of individual tool reports from generate_report()
        
    Returns:
        Full report with summary and tool details
    """
    compatible = sum(1 for r in tool_reports if r["status"] == "COMPATIBLE")
    incompatible = len(tool_reports) - compatible
    
    return {
        "summary": {
            "total_tools": len(tool_reports),
            "compatible": compatible,
            "incompatible": incompatible,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "tools": tool_reports,
    }


def print_terminal_report(report: dict, use_color: bool = True) -> None:
    """
    Pretty-print report to terminal with optional coloring.
    
    Args:
        report: Report dict from generate_report()
        use_color: Whether to use ANSI color codes
    """
    # Color codes
    if use_color:
        RED = "\033[91m"
        GREEN = "\033[92m"
        YELLOW = "\033[93m"
        BLUE = "\033[94m"
        BOLD = "\033[1m"
        RESET = "\033[0m"
    else:
        RED = GREEN = YELLOW = BLUE = BOLD = RESET = ""
    
    tool_name = report["tool"]
    status = report["status"]
    issues = report["issues"]
    changes = report["transforms_applied"]
    
    # Header
    print(f"\n{BOLD}{'═' * 68}{RESET}")
    print(f"{BOLD}🔍 TOOL: {tool_name}{RESET}")
    print(f"{'═' * 68}")
    
    # Status
    if status == "COMPATIBLE":
        print(f"{GREEN}✅ STATUS: COMPATIBLE{RESET}")
    else:
        print(f"{RED}❌ STATUS: INCOMPATIBLE{RESET}")
    
    # Issues
    if issues:
        print(f"\n{YELLOW}⚠️  ISSUES FOUND:{RESET}")
        for i, issue in enumerate(issues, 1):
            severity_color = RED if issue["severity"] == "critical" else YELLOW if issue["severity"] == "medium" else BLUE
            print(f"   [{i}] {severity_color}{issue['path']}{RESET}")
            print(f"       Pattern: {issue['pattern']}")
            print(f"       Message: {issue['message']}")
            print(f"       Severity: {issue['severity']}")
    
    # Transforms
    if changes:
        print(f"\n{GREEN}🔧 TRANSFORMS APPLIED:{RESET}")
        for change in changes:
            print(f"   - {change}")
    
    print()


def print_summary_report(summary_report: dict, use_color: bool = True) -> None:
    """
    Print summary of all tools to terminal.
    
    Args:
        summary_report: Report from generate_summary_report()
        use_color: Whether to use ANSI color codes
    """
    if use_color:
        RED = "\033[91m"
        GREEN = "\033[92m"
        BOLD = "\033[1m"
        RESET = "\033[0m"
    else:
        RED = GREEN = BOLD = RESET = ""
    
    summary = summary_report["summary"]
    
    print(f"\n{BOLD}{'═' * 68}{RESET}")
    print(f"{BOLD}📊 SCHEMA COMPATIBILITY SUMMARY{RESET}")
    print(f"{'═' * 68}")
    print(f"Total tools: {summary['total_tools']}")
    print(f"{GREEN}Compatible: {summary['compatible']}{RESET}")
    print(f"{RED}Incompatible: {summary['incompatible']}{RESET}")
    print(f"Timestamp: {summary['timestamp']}")
    print(f"{'═' * 68}\n")
    
    # List tools by status
    compatible_tools = [r["tool"] for r in summary_report["tools"] if r["status"] == "COMPATIBLE"]
    incompatible_tools = [r["tool"] for r in summary_report["tools"] if r["status"] == "INCOMPATIBLE"]
    
    if incompatible_tools:
        print(f"{RED}❌ Incompatible tools:{RESET}")
        for tool in incompatible_tools:
            print(f"   - {tool}")
    
    if compatible_tools:
        print(f"\n{GREEN}✅ Compatible tools:{RESET}")
        for tool in compatible_tools:
            print(f"   - {tool}")
    
    print()


def print_diff(original: dict, transformed: dict, tool_name: str, use_color: bool = True) -> None:
    """
    Print side-by-side diff of original vs transformed schema.
    
    Args:
        original: Raw schema before transformation
        transformed: Schema after transformation
        tool_name: Name of the tool (for header)
        use_color: Whether to use ANSI color codes
    """
    if use_color:
        RED = "\033[91m"
        GREEN = "\033[92m"
        BOLD = "\033[1m"
        RESET = "\033[0m"
    else:
        RED = GREEN = BOLD = RESET = ""
    
    print(f"\n{BOLD}{'═' * 68}{RESET}")
    print(f"{BOLD}📊 SCHEMA DIFF: {tool_name}{RESET}")
    print(f"{'═' * 68}")
    
    # Simple key-level diff (not a full unified diff, but useful for overview)
    orig_str = json.dumps(original, indent=2, sort_keys=True)
    trans_str = json.dumps(transformed, indent=2, sort_keys=True)
    
    print(f"\n{RED}--- ORIGINAL{RESET}")
    print(orig_str[:2000] + ("..." if len(orig_str) > 2000 else ""))
    
    print(f"\n{GREEN}+++ TRANSFORMED{RESET}")
    print(trans_str[:2000] + ("..." if len(trans_str) > 2000 else ""))
    
    print()


def format_json_report(report: dict, indent: int = 2) -> str:
    """
    Format report as JSON string.
    
    Args:
        report: Report dict
        indent: JSON indentation level
        
    Returns:
        JSON string
    """
    return json.dumps(report, indent=indent, default=str)