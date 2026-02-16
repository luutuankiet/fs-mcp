"""
Schema Compatibility Tooling for fs-mcp

CLI tooling for inspecting, validating, and transforming MCP tool schemas
to ensure Gemini compatibility.

Usage:
    python -m scripts.schema_compat check          # Check all tools
    python -m scripts.schema_compat check --json   # Output JSON report
    python -m scripts.schema_compat diff <tool>    # Show raw vs transformed
    python -m scripts.schema_compat transform <tool>  # Show transformed only

Reference: LOG-001 (root cause), LOG-002 (22 patterns), LOG-003 (this plan)
"""

from .extractor import extract_mcp_schemas
from .transforms import transform_for_gemini
from .validator import validate_schema, FORBIDDEN_PATTERNS
from .reporter import generate_report, print_terminal_report

__all__ = [
    "extract_mcp_schemas",
    "transform_for_gemini",
    "validate_schema",
    "FORBIDDEN_PATTERNS",
    "generate_report",
    "print_terminal_report",
]