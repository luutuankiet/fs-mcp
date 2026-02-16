"""
CI Guard: Gemini Schema Compatibility Tests

Ensures all fs-mcp tool schemas are compatible with Gemini's strict OpenAPI 3.0 subset.
This test suite will FAIL if any tool emits schemas containing forbidden patterns
like $ref, $defs, title, default, etc.

Reference: LOG-001 (root cause), LOG-002 (22 forbidden patterns), LOG-003 (implementation plan)

Why this matters:
- Gemini silently corrupts tool schemas with $ref → degrades to STRING type
- This causes nested objects (FileReadRequest, EditPair) to become unusable
- CI must catch this BEFORE release, not when users report broken tool calls
"""

import pytest
import tempfile
import json
from typing import Any

from fs_mcp import server

# Import the schema_compat tooling
import sys
from pathlib import Path

# Add scripts to path for imports
scripts_path = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_path))

from schema_compat.validator import validate_schema, SEVERITY
from schema_compat.transforms import transform_for_gemini


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def initialized_server():
    """Initialize the server once for all tests in this module with all tools enabled."""
    with tempfile.TemporaryDirectory() as tmp:
        server.initialize([tmp], use_all_tools=True)
        yield server.mcp


@pytest.fixture(scope="module")
def all_tool_schemas(initialized_server) -> dict[str, dict]:
    """Extract all tool schemas from the initialized server."""
    schemas = {}
    tool_manager = initialized_server._tool_manager
    
    for tool_name, tool in tool_manager._tools.items():
        schemas[tool_name] = tool.parameters
    
    return schemas


# ============================================================================
# Core Compatibility Tests
# ============================================================================

class TestNoForbiddenPatterns:
    """
    Verify that NO tool schema contains Gemini-incompatible patterns.
    
    These tests are the CI guard - they fail fast if any schema breaks Gemini.
    """
    
    def test_no_ref_in_any_schema(self, all_tool_schemas):
        """CRITICAL: $ref must never appear in any tool schema.
        
        Why: Gemini cannot resolve $ref and silently degrades to STRING type.
        This is the root cause identified in LOG-001.
        """
        violations = []
        
        for tool_name, schema in all_tool_schemas.items():
            schema_str = json.dumps(schema)
            if '"$ref"' in schema_str:
                violations.append(f"{tool_name}: Contains $ref (will degrade to STRING)")
        
        assert not violations, (
            f"CRITICAL: Found $ref in tool schemas - Gemini will break!\n"
            f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )
    
    def test_no_defs_in_any_schema(self, all_tool_schemas):
        """CRITICAL: $defs must never appear in any tool schema.
        
        Why: $defs only makes sense with $ref. If $ref is dereferenced,
        $defs becomes dead weight and may confuse Gemini.
        """
        violations = []
        
        for tool_name, schema in all_tool_schemas.items():
            if "$defs" in schema or "definitions" in schema:
                violations.append(f"{tool_name}: Contains $defs or definitions")
        
        assert not violations, (
            f"Found $defs in tool schemas - should be removed after dereferencing!\n"
            f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )
    
    def test_no_title_in_any_schema(self, all_tool_schemas):
        """MEDIUM: 'title' may cause Gemini validation errors.
        
        Why: Gemini Schema spec doesn't include 'title' in allowed fields.
        """
        violations = []
        
        for tool_name, schema in all_tool_schemas.items():
            schema_str = json.dumps(schema)
            if '"title"' in schema_str:
                violations.append(f"{tool_name}: Contains 'title' field")
        
        assert not violations, (
            f"Found 'title' in tool schemas - may cause Gemini validation errors!\n"
            f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )
    
    def test_no_default_in_any_schema(self, all_tool_schemas):
        """MEDIUM: 'default' is ignored by Gemini, remove for clarity.
        
        Why: Gemini documents 'default' as ignored. Presence may mislead.
        """
        violations = []
        
        for tool_name, schema in all_tool_schemas.items():
            schema_str = json.dumps(schema)
            if '"default"' in schema_str:
                violations.append(f"{tool_name}: Contains 'default' field")
        
        assert not violations, (
            f"Found 'default' in tool schemas - Gemini ignores this field!\n"
            f"Violations:\n" + "\n".join(f"  - {v}" for v in violations)
        )


class TestCriticalToolsCompatible:
    """
    Test the most important tools individually for detailed error messages.
    
    These are the tools with nested Pydantic models that are most likely
    to have $ref issues.
    """
    
    @pytest.mark.parametrize("tool_name", [
        "read_files",       # Has FileReadRequest nested model
        "propose_and_review",  # Has EditPair nested model
        "grep_content",     # Core tool
        "query_json",       # Core tool
        "query_yaml",       # Core tool
    ])
    def test_tool_passes_full_validation(self, all_tool_schemas, tool_name):
        """Each critical tool must pass full Gemini validation."""
        schema = all_tool_schemas.get(tool_name)
        assert schema is not None, f"Tool '{tool_name}' not found"
        
        issues = validate_schema(schema)
        critical_issues = [i for i in issues if i.get("severity") == "critical"]
        
        assert not critical_issues, (
            f"Tool '{tool_name}' has CRITICAL Gemini compatibility issues:\n"
            + "\n".join(f"  - {i['pattern']}: {i['message']}" for i in critical_issues)
        )


class TestValidatorCoversAllPatterns:
    """
    Verify the validator catches the known forbidden patterns.
    
    This is a meta-test to ensure our validator itself is working correctly.
    """
    
    def test_validator_catches_ref(self):
        """Validator must detect $ref."""
        schema = {
            "type": "object",
            "properties": {
                "items": {"$ref": "#/$defs/Item"}
            },
            "$defs": {"Item": {"type": "string"}}
        }
        issues = validate_schema(schema)
        patterns = [i["pattern"] for i in issues]
        assert "$ref" in patterns, "Validator failed to detect $ref"
    
    def test_validator_catches_defs(self):
        """Validator must detect $defs."""
        schema = {
            "type": "object",
            "$defs": {"Item": {"type": "string"}}
        }
        issues = validate_schema(schema)
        patterns = [i["pattern"] for i in issues]
        assert "$defs" in patterns, "Validator failed to detect $defs"
    
    def test_validator_catches_title(self):
        """Validator must detect title."""
        schema = {
            "type": "object",
            "title": "MySchema"
        }
        issues = validate_schema(schema)
        patterns = [i["pattern"] for i in issues]
        assert "title" in patterns, "Validator failed to detect title"
    
    def test_validator_catches_default(self):
        """Validator must detect default."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "foo"}
            }
        }
        issues = validate_schema(schema)
        patterns = [i["pattern"] for i in issues]
        assert "default" in patterns, "Validator failed to detect default"


class TestTransformProducesValidSchemas:
    """
    Verify that transformed schemas pass validation.
    
    This tests the transformation pipeline itself.
    """
    
    def test_transform_removes_ref(self):
        """Transform must inline $ref."""
        schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/Item"}
            },
            "$defs": {
                "Item": {"type": "string", "description": "An item"}
            }
        }
        transformed, changes = transform_for_gemini(schema)
        
        assert "$ref" not in json.dumps(transformed), "Transform failed to inline $ref"
        assert "$defs" not in transformed, "Transform failed to remove $defs"
        # The inlined content should be present (transforms may uppercase types)
        assert transformed["properties"]["item"]["type"].lower() == "string"
    
    def test_transform_removes_title(self):
        """Transform must remove title."""
        schema = {
            "type": "object",
            "title": "MySchema",
            "properties": {
                "name": {"type": "string", "title": "Name Field"}
            }
        }
        transformed, changes = transform_for_gemini(schema)
        
        assert "title" not in json.dumps(transformed), "Transform failed to remove title"
    
    def test_transform_removes_default(self):
        """Transform must remove default."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "foo"}
            }
        }
        transformed, changes = transform_for_gemini(schema)
        
        assert "default" not in json.dumps(transformed), "Transform failed to remove default"
    
    def test_transformed_schema_passes_validation(self):
        """A transformed schema should have zero critical issues."""
        # Start with a problematic schema
        schema = {
            "type": "object",
            "title": "TestSchema",
            "properties": {
                "items": {"$ref": "#/$defs/Item"},
                "name": {"type": "string", "default": "test"}
            },
            "$defs": {
                "Item": {"type": "string", "title": "ItemType"}
            }
        }
        
        # Transform it
        transformed, changes = transform_for_gemini(schema)
        
        # Validate the result
        issues = validate_schema(transformed)
        critical_issues = [i for i in issues if i.get("severity") == "critical"]
        
        assert not critical_issues, (
            f"Transformed schema still has critical issues:\n"
            + "\n".join(f"  - {i['pattern']}: {i['message']}" for i in critical_issues)
        )


class TestAllToolsPassFullValidation:
    """
    Comprehensive test: every single tool must pass full validation.
    
    This is the ultimate CI guard.
    """
    
    def test_all_tools_have_zero_critical_issues(self, all_tool_schemas):
        """Every tool must have zero CRITICAL issues."""
        all_violations = {}
        
        for tool_name, schema in all_tool_schemas.items():
            issues = validate_schema(schema)
            critical = [i for i in issues if i.get("severity") == "critical"]
            if critical:
                all_violations[tool_name] = critical
        
        if all_violations:
            msg = "CRITICAL: Tools with Gemini-incompatible schemas:\n"
            for tool, issues in all_violations.items():
                msg += f"\n  {tool}:\n"
                for issue in issues:
                    msg += f"    - {issue['pattern']}: {issue['message']}\n"
            pytest.fail(msg)
    
    def test_all_tools_have_zero_medium_issues(self, all_tool_schemas):
        """Every tool should have zero MEDIUM issues (may cause errors)."""
        all_violations = {}
        
        for tool_name, schema in all_tool_schemas.items():
            issues = validate_schema(schema)
            medium = [i for i in issues if i.get("severity") == "medium"]
            if medium:
                all_violations[tool_name] = medium
        
        if all_violations:
            msg = "WARNING: Tools with potentially problematic schemas:\n"
            for tool, issues in all_violations.items():
                msg += f"\n  {tool}:\n"
                for issue in issues:
                    msg += f"    - {issue['pattern']}: {issue['message']}\n"
            pytest.fail(msg)


# ============================================================================
# Regression Tests
# ============================================================================

class TestRegressionLOG001:
    """
    Regression tests for the specific issue discovered in LOG-001.
    
    The bug: read_files tool's FileReadRequest nested model was sent to Gemini
    with $ref unresolved, causing Gemini to degrade it to STRING type.
    """
    
    def test_read_files_items_is_not_ref(self, all_tool_schemas):
        """read_files.files.items must be inlined, not a $ref.
        
        This is the exact pattern that broke Gemini in LOG-001.
        """
        schema = all_tool_schemas.get("read_files")
        assert schema is not None
        
        items_schema = schema.get("properties", {}).get("files", {}).get("items", {})
        
        assert "$ref" not in items_schema, (
            "REGRESSION: read_files.files.items still contains $ref!\n"
            "This is the exact bug from LOG-001 that breaks Gemini.\n"
            f"Got: {items_schema}"
        )
        
        # It should be an inlined object with properties
        assert items_schema.get("type") == "object" or "properties" in items_schema, (
            "read_files.files.items should be an inlined object schema"
        )
    
    def test_propose_and_review_edits_items_is_not_ref(self, all_tool_schemas):
        """propose_and_review.edits.items must be inlined, not a $ref.
        
        Similar to read_files, EditPair nested model must be inlined.
        """
        schema = all_tool_schemas.get("propose_and_review")
        assert schema is not None
        
        # edits is Optional[List[EditPair]], so it might be in anyOf
        edits_schema = schema.get("properties", {}).get("edits", {})
        
        # Navigate through anyOf if present
        if "anyOf" in edits_schema:
            for option in edits_schema["anyOf"]:
                if option.get("type") == "array":
                    items = option.get("items", {})
                    assert "$ref" not in items, (
                        "REGRESSION: propose_and_review.edits.items still contains $ref!"
                    )
        elif "items" in edits_schema:
            assert "$ref" not in edits_schema["items"], (
                "REGRESSION: propose_and_review.edits.items still contains $ref!"
            )