"""
Schema Extractor for fs-mcp

Extracts raw MCP tool schemas programmatically without LLM involvement.
Uses the same pattern as tests/test_tool_arg_descriptions.py.

Reference: LOG-003 Section 3.1
"""

import tempfile
from typing import Any


def extract_mcp_schemas(allowed_dirs: list[str] | None = None) -> dict[str, dict]:
    """
    Initialize fs-mcp server and extract all tool schemas.
    
    Args:
        allowed_dirs: Directories to allow access to. If None, uses a temp directory.
    
    Returns:
        Dict mapping tool_name -> raw JSON schema (with $ref, $defs, etc.)
    
    Example:
        >>> schemas = extract_mcp_schemas()
        >>> schemas["read_files"]["properties"]["files"]
        {'type': 'array', 'items': {'$ref': '#/$defs/FileReadRequest'}, ...}
    """
    from fs_mcp import server
    
    # Use temp directory if none provided (for safe extraction)
    if allowed_dirs is None:
        with tempfile.TemporaryDirectory() as tmp:
            server.initialize([tmp])
            return _extract_from_initialized_server(server.mcp)
    else:
        server.initialize(allowed_dirs)
        return _extract_from_initialized_server(server.mcp)


def _extract_from_initialized_server(mcp_instance: Any) -> dict[str, dict]:
    """
    Extract schemas from an already-initialized MCP server instance.
    
    Args:
        mcp_instance: The initialized FastMCP server (server.mcp)
    
    Returns:
        Dict mapping tool_name -> raw JSON schema
    """
    schemas = {}
    
    # Access internal tool manager (same pattern as test_tool_arg_descriptions.py)
    tool_manager = mcp_instance._tool_manager
    
    for tool_name, tool in tool_manager._tools.items():
        # tool.parameters is the raw JSON schema from Pydantic
        schemas[tool_name] = tool.parameters
    
    return schemas


def get_single_schema(tool_name: str, allowed_dirs: list[str] | None = None) -> dict | None:
    """
    Extract schema for a single tool.
    
    Args:
        tool_name: Name of the tool to extract
        allowed_dirs: Directories to allow access to
    
    Returns:
        Raw JSON schema for the tool, or None if not found
    """
    schemas = extract_mcp_schemas(allowed_dirs)
    return schemas.get(tool_name)


def list_tool_names(allowed_dirs: list[str] | None = None) -> list[str]:
    """
    Get list of all registered tool names.
    
    Returns:
        Sorted list of tool names
    """
    schemas = extract_mcp_schemas(allowed_dirs)
    return sorted(schemas.keys())