"""
CLI for Schema Compatibility Tooling

Entry point for command-line usage of schema validation and transformation.

Usage:
    python -m scripts.schema_compat check              # Check all tools
    python -m scripts.schema_compat check --json       # Output JSON report
    python -m scripts.schema_compat check --tool X     # Check specific tool
    python -m scripts.schema_compat diff <tool>        # Show raw vs transformed
    python -m scripts.schema_compat transform <tool>   # Show transformed only
    python -m scripts.schema_compat list               # List all tool names

Reference: LOG-003 Section 3.5
"""

import argparse
import json
import sys
from typing import NoReturn

from .extractor import extract_mcp_schemas, list_tool_names
from .transforms import transform_for_gemini
from .validator import validate_schema
from .reporter import (
    generate_report,
    generate_summary_report,
    print_terminal_report,
    print_summary_report,
    print_diff,
    format_json_report,
)


def cmd_check(args: argparse.Namespace) -> int:
    """Check tools for Gemini compatibility."""
    schemas = extract_mcp_schemas()
    
    # Filter to specific tool if requested
    if args.tool:
        if args.tool not in schemas:
            print(f"Error: Tool '{args.tool}' not found", file=sys.stderr)
            print(f"Available tools: {', '.join(sorted(schemas.keys()))}", file=sys.stderr)
            return 1
        schemas = {args.tool: schemas[args.tool]}
    
    # Generate reports for each tool
    reports = []
    for tool_name, schema in sorted(schemas.items()):
        issues = validate_schema(schema)
        transformed, changes = transform_for_gemini(schema)
        report = generate_report(tool_name, schema, transformed, issues, changes)
        reports.append(report)
    
    # Output
    if args.json:
        summary = generate_summary_report(reports)
        print(format_json_report(summary))
    else:
        # Terminal output
        use_color = not args.no_color
        
        if len(reports) == 1:
            # Single tool - show detailed report
            print_terminal_report(reports[0], use_color=use_color)
        else:
            # Multiple tools - show summary + details for incompatible
            summary = generate_summary_report(reports)
            print_summary_report(summary, use_color=use_color)
            
            # Show details for incompatible tools
            if args.verbose:
                for report in reports:
                    if report["status"] == "INCOMPATIBLE":
                        print_terminal_report(report, use_color=use_color)
    
    # Exit code: 0 if all compatible, 1 if any incompatible
    incompatible_count = sum(1 for r in reports if r["status"] == "INCOMPATIBLE")
    return 0 if incompatible_count == 0 else 1


def cmd_diff(args: argparse.Namespace) -> int:
    """Show diff between original and transformed schema."""
    schemas = extract_mcp_schemas()
    
    if args.tool not in schemas:
        print(f"Error: Tool '{args.tool}' not found", file=sys.stderr)
        print(f"Available tools: {', '.join(sorted(schemas.keys()))}", file=sys.stderr)
        return 1
    
    schema = schemas[args.tool]
    transformed, _ = transform_for_gemini(schema)
    
    use_color = not args.no_color
    print_diff(schema, transformed, args.tool, use_color=use_color)
    
    return 0


def cmd_transform(args: argparse.Namespace) -> int:
    """Show transformed schema only."""
    schemas = extract_mcp_schemas()
    
    if args.tool not in schemas:
        print(f"Error: Tool '{args.tool}' not found", file=sys.stderr)
        print(f"Available tools: {', '.join(sorted(schemas.keys()))}", file=sys.stderr)
        return 1
    
    schema = schemas[args.tool]
    transformed, changes = transform_for_gemini(schema)
    
    if args.json:
        print(json.dumps(transformed, indent=2))
    else:
        print(f"\n🔧 Transformed schema for '{args.tool}':")
        print(f"   Changes applied: {len(changes)}")
        for change in changes:
            print(f"   - {change}")
        print(f"\n{json.dumps(transformed, indent=2)}")
    
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all registered tool names."""
    tools = list_tool_names()
    
    if args.json:
        print(json.dumps(tools, indent=2))
    else:
        print(f"\n📋 Registered MCP tools ({len(tools)} total):\n")
        for tool in tools:
            print(f"   - {tool}")
        print()
    
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="schema_compat",
        description="Schema compatibility tooling for Gemini",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # check command
    check_parser = subparsers.add_parser(
        "check",
        help="Check tools for Gemini compatibility",
    )
    check_parser.add_argument(
        "--tool",
        help="Check specific tool only",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON report",
    )
    check_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed reports for incompatible tools",
    )
    check_parser.set_defaults(func=cmd_check)
    
    # diff command
    diff_parser = subparsers.add_parser(
        "diff",
        help="Show diff between original and transformed schema",
    )
    diff_parser.add_argument(
        "tool",
        help="Tool name to diff",
    )
    diff_parser.set_defaults(func=cmd_diff)
    
    # transform command
    transform_parser = subparsers.add_parser(
        "transform",
        help="Show transformed schema only",
    )
    transform_parser.add_argument(
        "tool",
        help="Tool name to transform",
    )
    transform_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON only (no header)",
    )
    transform_parser.set_defaults(func=cmd_transform)
    
    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List all registered tool names",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON",
    )
    list_parser.set_defaults(func=cmd_list)
    
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())