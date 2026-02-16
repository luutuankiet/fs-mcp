"""
Schema Validator for Gemini Compatibility

Checks if a schema contains any Gemini-incompatible patterns.
Used for both pre-transform detection and post-transform verification.

Reference: LOG-002 Section 4 (Forbidden Fields), LOG-003 Section 3.3
"""

from typing import Any


# Forbidden patterns with explanations (from LOG-002)
FORBIDDEN_PATTERNS = {
    "$ref": "References not supported — will degrade to STRING",
    "$defs": "Definitions block not supported",
    "definitions": "Definitions block not supported (legacy key)",
    "$id": "Schema identifier not supported",
    "$schema": "Schema version not supported",
    "title": "May cause validation errors",
    "default": "Documented as ignored, remove for safety",
    "additionalProperties": "Not in Gemini Schema spec",
    "oneOf": "Only anyOf is supported",
    "allOf": "Not supported, must merge manually",
    "not": "Negation not supported",
    "if": "Conditional schemas not supported",
    "then": "Conditional schemas not supported",
    "else": "Conditional schemas not supported",
    "const": "Use single-value enum instead",
    "propertyOrdering": "Causes validation errors",
    "property_ordering": "Causes validation errors (snake_case variant)",
    "exclusiveMinimum": "Use minimum instead",
    "exclusiveMaximum": "Use maximum instead",
    "multipleOf": "Not in Gemini Schema spec",
    "dependentRequired": "Not in Gemini Schema spec",
    "dependentSchemas": "Not in Gemini Schema spec",
    "prefixItems": "Not in Gemini Schema spec",
    "contains": "Not in Gemini Schema spec",
    "unevaluatedProperties": "Not in Gemini Schema spec",
    "unevaluatedItems": "Not in Gemini Schema spec",
    "contentMediaType": "Not in Gemini Schema spec",
    "contentEncoding": "Not in Gemini Schema spec",
}

# Severity levels for prioritization
SEVERITY = {
    # Critical: Causes tool calls to fail (wrong argument types)
    "$ref": "critical",
    "$defs": "critical",
    "definitions": "critical",
    # Medium: May cause API errors or unexpected behavior
    "$id": "medium",
    "$schema": "medium",
    "title": "medium",
    "default": "medium",
    "additionalProperties": "medium",
    "oneOf": "medium",
    "allOf": "medium",
    "propertyOrdering": "medium",
    "property_ordering": "medium",
    # Low: Unlikely to cause issues but not spec-compliant
    "not": "low",
    "if": "low",
    "then": "low",
    "else": "low",
    "const": "low",
    "exclusiveMinimum": "low",
    "exclusiveMaximum": "low",
    "multipleOf": "low",
    "dependentRequired": "low",
    "dependentSchemas": "low",
    "prefixItems": "low",
    "contains": "low",
    "unevaluatedProperties": "low",
    "unevaluatedItems": "low",
    "contentMediaType": "low",
    "contentEncoding": "low",
}


def validate_schema(schema: dict) -> list[dict]:
    """
    Check schema for Gemini-incompatible patterns.
    
    Args:
        schema: JSON Schema to validate
        
    Returns:
        List of issues found, each with:
        - path: JSONPath to the issue (e.g., "$.properties.files.items.$ref")
        - pattern: The forbidden pattern found
        - message: Explanation of why it's problematic
        - severity: "critical", "medium", or "low"
        
    Example:
        >>> issues = validate_schema({"$ref": "#/$defs/X"})
        >>> issues[0]["pattern"]
        '$ref'
    """
    issues = []
    _find_issues(schema, "$", issues)
    
    # Sort by severity (critical first)
    severity_order = {"critical": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: severity_order.get(x["severity"], 3))
    
    return issues


def _find_issues(node: Any, path: str, issues: list[dict]) -> None:
    """Recursively find forbidden patterns in schema."""
    if not isinstance(node, dict):
        return
    
    for key, value in node.items():
        current_path = f"{path}.{key}"
        
        # Check if this key is forbidden
        if key in FORBIDDEN_PATTERNS:
            issues.append({
                "path": current_path,
                "pattern": key,
                "message": FORBIDDEN_PATTERNS[key],
                "severity": SEVERITY.get(key, "low"),
            })
        
        # Recurse into nested structures
        if isinstance(value, dict):
            _find_issues(value, current_path, issues)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    _find_issues(item, f"{current_path}[{i}]", issues)


def is_compatible(schema: dict) -> bool:
    """
    Quick check if schema is Gemini-compatible.
    
    Returns:
        True if no issues found, False otherwise
    """
    return len(validate_schema(schema)) == 0


def find_all_refs(schema: dict) -> list[str]:
    """
    Find all $ref occurrences in schema.
    
    Returns:
        List of JSONPaths where $ref was found
    """
    refs = []
    
    def _find_refs(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(path)
            for key, value in node.items():
                _find_refs(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _find_refs(item, f"{path}[{i}]")
    
    _find_refs(schema, "$")
    return refs


def get_compatibility_summary(schema: dict) -> dict:
    """
    Get a summary of schema compatibility.
    
    Returns:
        Dict with:
        - compatible: bool
        - critical_count: int
        - medium_count: int
        - low_count: int
        - issues: list of issues
    """
    issues = validate_schema(schema)
    
    return {
        "compatible": len(issues) == 0,
        "critical_count": sum(1 for i in issues if i["severity"] == "critical"),
        "medium_count": sum(1 for i in issues if i["severity"] == "medium"),
        "low_count": sum(1 for i in issues if i["severity"] == "low"),
        "issues": issues,
    }