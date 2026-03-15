#!/usr/bin/env python3
"""Measure token footprint of MCP tool schemas as clients see them.

Usage:
    python scripts/measure_tool_tokens.py                    # All tools
    python scripts/measure_tool_tokens.py edit_files         # Single tool
    python scripts/measure_tool_tokens.py edit_files propose_and_review  # Compare tools

Measures: description + JSON schema = total body that MCP clients emit to agents.
Token count uses chars/4 approximation (no external deps). Pass --tiktoken for accurate count.
"""
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def extract_tool_info(use_all_tools: bool = True):
    """Extract tool schemas and descriptions from initialized server."""
    import tempfile
    from fs_mcp import server

    with tempfile.TemporaryDirectory() as tmp:
        server.initialize([tmp], use_all_tools=use_all_tools)
        tool_manager = server.mcp._tool_manager
        tools = {}
        for name, tool in tool_manager._tools.items():
            tools[name] = {
                "description": tool.description or "",
                "schema": tool.parameters or {},
            }
        return tools


def count_tokens(text: str, use_tiktoken: bool = False) -> int:
    """Count tokens. Uses tiktoken if available and requested, otherwise chars/4."""
    if use_tiktoken:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            print("Warning: tiktoken not installed, falling back to chars/4", file=sys.stderr)
    return max(1, len(text) // 4)


def measure_tool(name: str, info: dict, use_tiktoken: bool = False) -> dict:
    """Measure token footprint of a single tool."""
    desc = info["description"]
    schema_json = json.dumps(info["schema"], indent=2)
    full_body = desc + "\n" + schema_json

    desc_tokens = count_tokens(desc, use_tiktoken)
    schema_tokens = count_tokens(schema_json, use_tiktoken)
    total_tokens = count_tokens(full_body, use_tiktoken)

    return {
        "name": name,
        "desc_tokens": desc_tokens,
        "schema_tokens": schema_tokens,
        "total_tokens": total_tokens,
        "desc_chars": len(desc),
        "schema_chars": len(schema_json),
        "total_chars": len(full_body),
        "description": desc,
        "schema_json": schema_json,
    }


def main():
    use_tiktoken = "--tiktoken" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    tool_names = [a for a in sys.argv[1:] if not a.startswith("-")]

    # Use --all to get all tools including demoted ones
    tools = extract_tool_info(use_all_tools=True)

    if not tool_names:
        tool_names = sorted(tools.keys())

    method = "tiktoken" if use_tiktoken else "chars/4"
    print(f"Token counting: {method}\n")

    measurements = []
    for name in tool_names:
        if name not in tools:
            print(f"Tool '{name}' not found. Available: {sorted(tools.keys())}")
            continue
        m = measure_tool(name, tools[name], use_tiktoken)
        measurements.append(m)

    # Table output
    print(f"{'Tool':<30} {'Desc':>6} {'Schema':>8} {'Total':>7} {'Chars':>7}")
    print("-" * 62)
    for m in sorted(measurements, key=lambda x: x["total_tokens"], reverse=True):
        print(f"{m['name']:<30} {m['desc_tokens']:>6} {m['schema_tokens']:>8} {m['total_tokens']:>7} {m['total_chars']:>7}")

    if verbose and measurements:
        for m in measurements:
            print(f"\n{'='*60}")
            print(f"Tool: {m['name']}")
            print(f"{'='*60}")
            print(f"\n--- Description ({m['desc_tokens']} tokens) ---")
            print(m["description"])
            print(f"\n--- Schema ({m['schema_tokens']} tokens) ---")
            print(m["schema_json"])


if __name__ == "__main__":
    main()
