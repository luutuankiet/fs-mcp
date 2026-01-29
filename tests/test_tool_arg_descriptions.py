"""
Unit tests for MCP tool argument descriptions.

This module tests that all tool arguments have proper descriptions emitted
to the MCP client via the JSON schema. These tests ensure that:
1. Each tool parameter has a description in the schema
2. The descriptions match the expected content
3. Nested models (like FileReadRequest, EditPair) have descriptions for their fields
"""
import pytest
import tempfile
from fs_mcp import server


def get_description_from_schema(param_schema: dict) -> str | None:
    """Extract description from schema, handling nested anyOf structures."""
    if "description" in param_schema:
        return param_schema["description"]
    # Check nested anyOf structures (common with Optional[Annotated[...]])
    if "anyOf" in param_schema:
        for option in param_schema["anyOf"]:
            if "description" in option:
                return option["description"]
    return None


@pytest.fixture(scope="module")
def initialized_server():
    """Initialize the server once for all tests in this module."""
    with tempfile.TemporaryDirectory() as tmp:
        server.initialize([tmp])
        yield server.mcp


def get_tool_schema(initialized_server, tool_name: str) -> dict:
    """Helper to get the parameter schema for a tool."""
    tool = initialized_server._tool_manager._tools.get(tool_name)
    assert tool is not None, f"Tool '{tool_name}' not found"
    return tool.parameters


class TestReadFilesArgDescriptions:
    """Test argument descriptions for the read_files tool."""

    def test_files_param_has_description(self, initialized_server):
        """The 'files' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "read_files")
        assert "files" in schema["properties"]
        assert "description" in schema["properties"]["files"]
        assert "file read requests" in schema["properties"]["files"]["description"].lower()

    def test_large_file_passthrough_has_description(self, initialized_server):
        """The 'large_file_passthrough' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "read_files")
        assert "large_file_passthrough" in schema["properties"]
        assert "description" in schema["properties"]["large_file_passthrough"]
        assert "json/yaml" in schema["properties"]["large_file_passthrough"]["description"].lower()

    def test_file_read_request_model_has_field_descriptions(self, initialized_server):
        """FileReadRequest nested model should have descriptions for all fields."""
        schema = get_tool_schema(initialized_server, "read_files")

        # FileReadRequest is defined in $defs
        assert "$defs" in schema
        assert "FileReadRequest" in schema["$defs"]

        file_read_request = schema["$defs"]["FileReadRequest"]
        props = file_read_request["properties"]

        # Test each field has a description
        expected_fields = ["path", "head", "tail", "start_line", "end_line", "read_to_next_pattern"]
        for field in expected_fields:
            assert field in props, f"Field '{field}' not found in FileReadRequest"
            assert "description" in props[field], f"Field '{field}' missing description"

    def test_path_field_description_content(self, initialized_server):
        """The 'path' field description should mention relative paths."""
        schema = get_tool_schema(initialized_server, "read_files")
        path_desc = schema["$defs"]["FileReadRequest"]["properties"]["path"]["description"]
        assert "relative" in path_desc.lower()

    def test_read_to_next_pattern_description_mentions_start_line(self, initialized_server):
        """The 'read_to_next_pattern' description should mention it requires start_line."""
        schema = get_tool_schema(initialized_server, "read_files")
        pattern_desc = schema["$defs"]["FileReadRequest"]["properties"]["read_to_next_pattern"]["description"]
        assert "start_line" in pattern_desc.lower()


class TestGrepContentArgDescriptions:
    """Test argument descriptions for the grep_content tool."""

    def test_pattern_has_description(self, initialized_server):
        """The 'pattern' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "grep_content")
        assert "pattern" in schema["properties"]
        assert "description" in schema["properties"]["pattern"]
        assert "regex" in schema["properties"]["pattern"]["description"].lower()

    def test_search_path_has_description_and_default(self, initialized_server):
        """The 'search_path' parameter should have description and default value."""
        schema = get_tool_schema(initialized_server, "grep_content")
        search_path = schema["properties"]["search_path"]
        assert "description" in search_path
        assert search_path["default"] == "."
        assert "directory" in search_path["description"].lower()

    def test_case_insensitive_has_description(self, initialized_server):
        """The 'case_insensitive' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "grep_content")
        case_insensitive = schema["properties"]["case_insensitive"]
        assert "description" in case_insensitive
        assert case_insensitive["default"] == False
        assert "case" in case_insensitive["description"].lower()

    def test_context_lines_has_description_and_default(self, initialized_server):
        """The 'context_lines' parameter should have description and default value."""
        schema = get_tool_schema(initialized_server, "grep_content")
        context_lines = schema["properties"]["context_lines"]
        assert "description" in context_lines
        assert context_lines["default"] == 2
        assert "context" in context_lines["description"].lower()

    def test_section_patterns_has_description(self, initialized_server):
        """The 'section_patterns' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "grep_content")
        section_patterns = schema["properties"]["section_patterns"]
        desc = get_description_from_schema(section_patterns)
        assert desc is not None, "section_patterns missing description"
        assert "section" in desc.lower() or "def" in desc.lower()


class TestQueryJsonArgDescriptions:
    """Test argument descriptions for the query_json tool."""

    def test_file_path_has_description(self, initialized_server):
        """The 'file_path' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "query_json")
        assert "file_path" in schema["properties"]
        assert "description" in schema["properties"]["file_path"]
        assert "json" in schema["properties"]["file_path"]["description"].lower()

    def test_jq_expression_has_description_with_examples(self, initialized_server):
        """The 'jq_expression' parameter should have a description with examples."""
        schema = get_tool_schema(initialized_server, "query_json")
        jq_expr = schema["properties"]["jq_expression"]
        assert "description" in jq_expr
        # Should contain example patterns
        desc = jq_expr["description"]
        assert ".field_name" in desc or "select" in desc

    def test_timeout_has_description_and_default(self, initialized_server):
        """The 'timeout' parameter should have description and default value."""
        schema = get_tool_schema(initialized_server, "query_json")
        timeout = schema["properties"]["timeout"]
        assert "description" in timeout
        assert timeout["default"] == 30
        assert "timeout" in timeout["description"].lower() or "second" in timeout["description"].lower()

    def test_required_parameters(self, initialized_server):
        """file_path and jq_expression should be required."""
        schema = get_tool_schema(initialized_server, "query_json")
        assert "required" in schema
        assert "file_path" in schema["required"]
        assert "jq_expression" in schema["required"]


class TestQueryYamlArgDescriptions:
    """Test argument descriptions for the query_yaml tool."""

    def test_file_path_has_description(self, initialized_server):
        """The 'file_path' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "query_yaml")
        assert "file_path" in schema["properties"]
        assert "description" in schema["properties"]["file_path"]
        assert "yaml" in schema["properties"]["file_path"]["description"].lower()

    def test_yq_expression_has_description_with_examples(self, initialized_server):
        """The 'yq_expression' parameter should have a description with examples."""
        schema = get_tool_schema(initialized_server, "query_yaml")
        yq_expr = schema["properties"]["yq_expression"]
        assert "description" in yq_expr
        # Should contain example patterns
        desc = yq_expr["description"]
        assert ".field_name" in desc or "select" in desc

    def test_timeout_has_description_and_default(self, initialized_server):
        """The 'timeout' parameter should have description and default value."""
        schema = get_tool_schema(initialized_server, "query_yaml")
        timeout = schema["properties"]["timeout"]
        assert "description" in timeout
        assert timeout["default"] == 30
        assert "timeout" in timeout["description"].lower() or "second" in timeout["description"].lower()

    def test_required_parameters(self, initialized_server):
        """file_path and yq_expression should be required."""
        schema = get_tool_schema(initialized_server, "query_yaml")
        assert "required" in schema
        assert "file_path" in schema["required"]
        assert "yq_expression" in schema["required"]


class TestProposeAndReviewArgDescriptions:
    """Test argument descriptions for the propose_and_review tool."""

    def test_path_has_description(self, initialized_server):
        """The 'path' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        assert "path" in schema["properties"]
        assert "description" in schema["properties"]["path"]
        assert "file" in schema["properties"]["path"]["description"].lower()

    def test_new_string_has_description(self, initialized_server):
        """The 'new_string' parameter should have a description."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        new_string = schema["properties"]["new_string"]
        assert "description" in new_string
        assert "replacement" in new_string["description"].lower() or "content" in new_string["description"].lower()

    def test_match_text_has_description_and_default(self, initialized_server):
        """The 'match_text' parameter should have description and empty default."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        match_text = schema["properties"]["match_text"]
        assert "description" in match_text
        assert match_text["default"] == ""
        # Should mention exact text matching
        assert "exact" in match_text["description"].lower() or "literal" in match_text["description"].lower()

    def test_expected_replacements_has_description(self, initialized_server):
        """The 'expected_replacements' parameter should have description."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        expected = schema["properties"]["expected_replacements"]
        assert "description" in expected
        assert expected["default"] == 1

    def test_session_path_has_description(self, initialized_server):
        """The 'session_path' parameter should have description for continuing sessions."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        session_path = schema["properties"]["session_path"]
        desc = get_description_from_schema(session_path)
        assert desc is not None, "session_path missing description"
        assert "session" in desc.lower()

    def test_edits_has_description(self, initialized_server):
        """The 'edits' parameter should have description for batch changes."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        edits = schema["properties"]["edits"]
        desc = get_description_from_schema(edits)
        assert desc is not None, "edits missing description"
        assert "batch" in desc.lower() or "multiple" in desc.lower()

    def test_edit_pair_model_has_field_descriptions(self, initialized_server):
        """EditPair nested model should have descriptions for all fields."""
        schema = get_tool_schema(initialized_server, "propose_and_review")

        # EditPair is defined in $defs
        assert "$defs" in schema
        assert "EditPair" in schema["$defs"]

        edit_pair = schema["$defs"]["EditPair"]
        props = edit_pair["properties"]

        # Test each field has a description
        assert "match_text" in props
        assert "description" in props["match_text"]
        assert "new_string" in props
        assert "description" in props["new_string"]

    def test_required_parameters(self, initialized_server):
        """path should be required (new_string is now optional with default="")."""
        schema = get_tool_schema(initialized_server, "propose_and_review")
        assert "required" in schema
        assert "path" in schema["required"]


class TestSchemaCompleteness:
    """Test that all parameters have descriptions (no missing descriptions)."""

    @pytest.mark.parametrize("tool_name", [
        "read_files",
        "grep_content",
        "query_json",
        "query_yaml",
        "propose_and_review"
    ])
    def test_all_top_level_params_have_descriptions(self, initialized_server, tool_name):
        """Every top-level parameter should have a description."""
        schema = get_tool_schema(initialized_server, tool_name)

        for param_name, param_schema in schema["properties"].items():
            desc = get_description_from_schema(param_schema)
            assert desc is not None, \
                f"Tool '{tool_name}' parameter '{param_name}' missing description"

    @pytest.mark.parametrize("tool_name,model_name", [
        ("read_files", "FileReadRequest"),
        ("propose_and_review", "EditPair")
    ])
    def test_all_nested_model_fields_have_descriptions(self, initialized_server, tool_name, model_name):
        """Every field in nested models should have a description."""
        schema = get_tool_schema(initialized_server, tool_name)

        assert "$defs" in schema, f"Tool '{tool_name}' has no $defs"
        assert model_name in schema["$defs"], f"Model '{model_name}' not in $defs"

        model_schema = schema["$defs"][model_name]
        for field_name, field_schema in model_schema["properties"].items():
            assert "description" in field_schema, \
                f"Model '{model_name}' field '{field_name}' missing description"


class TestDescriptionQuality:
    """Test that descriptions are meaningful and helpful."""

    def test_descriptions_are_not_empty(self, initialized_server):
        """All descriptions should be non-empty strings."""
        tools = ["read_files", "grep_content", "query_json", "query_yaml", "propose_and_review"]

        for tool_name in tools:
            schema = get_tool_schema(initialized_server, tool_name)

            for param_name, param_schema in schema["properties"].items():
                if "description" in param_schema:
                    desc = param_schema["description"]
                    assert isinstance(desc, str), f"Description for {tool_name}.{param_name} is not a string"
                    assert len(desc.strip()) > 10, f"Description for {tool_name}.{param_name} is too short: '{desc}'"

    def test_descriptions_contain_useful_info(self, initialized_server):
        """Descriptions should contain useful information about the parameter."""
        # Test a few specific descriptions for quality

        # read_files: files param should mention file requests
        schema = get_tool_schema(initialized_server, "read_files")
        files_desc = schema["properties"]["files"]["description"]
        assert any(word in files_desc.lower() for word in ["file", "request", "read"])

        # grep_content: pattern should mention regex
        schema = get_tool_schema(initialized_server, "grep_content")
        pattern_desc = schema["properties"]["pattern"]["description"]
        assert "regex" in pattern_desc.lower() or "pattern" in pattern_desc.lower()

        # query_json: jq_expression should have examples
        schema = get_tool_schema(initialized_server, "query_json")
        jq_desc = schema["properties"]["jq_expression"]["description"]
        assert "." in jq_desc  # Should have jq path examples like .field_name
