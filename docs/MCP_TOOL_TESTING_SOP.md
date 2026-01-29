# MCP Tool Testing Standard Operating Procedure

This document outlines the testing methodology for MCP tool changes, combining industry best practices with our specific testing approach.

## Overview

When modifying MCP tool schemas (parameters, descriptions, docstrings), we use a two-pronged testing approach:

1. **Intern Test** - LLM-based usability validation
2. **Unit Tests** - Code-based regression testing

---

## 1. The Intern Test (LLM Usability Validation)

### What is it?

The "Intern Test" is based on OpenAI's recommendation:

> "Pass the intern test: Can an intern/human correctly use the function given nothing but what you gave the model?"

We extend this by using a smaller LLM model (e.g., Claude Haiku) to simulate an agent reading your tool schema for the first time.

### Why use it?

- Schemas define what's **structurally valid**, but can't express **usage patterns**
- LLMs may "infer" missing parameters or make type-level mistakes
- The test reveals ambiguities, confusing descriptions, and potential footguns

### How to run it

1. **Extract the tool schema** (parameter names, types, descriptions, docstring)

2. **Spawn a Haiku agent** with a prompt like:

```
You are a new developer who has never used this tool before.
You're given ONLY the tool schema below - no other context.

Read the tool definition carefully, then answer:

1. [Concrete scenario]: What values would you provide for each parameter?
2. [Edge case]: Based on the description, what would happen if [edge case]?
3. What is confusing or unclear about the [parameter] description?
4. What's the MOST COMMON mistake a new user might make?
5. What would make the description clearer?

Be brutally honest - this is a usability test.
```

3. **Analyze results** for:
   - Correct understanding of basic usage
   - Identification of potential footguns
   - Confusion points in descriptions
   - Suggested improvements

### Example: The `match_text` parameter

When we ran the intern test on the `propose_and_review` tool, Haiku correctly identified:

| Finding | Severity |
|---------|----------|
| Empty `match_text` is a footgun | Critical |
| Description leads with constraints, not purpose | Medium |
| "Leave empty" phrase creates an escape hatch | Medium |

This led to restructuring the description to:
- Lead with **"REQUIRED for editing existing files"**
- Add explicit **"COMMON MISTAKE"** warning
- Provide a **"QUICK START"** section in the docstring

---

## 2. Unit Tests (Code-Based Validation)

### Test file structure

```
tests/
├── test_propose_and_review_validation.py  # Parameter validation tests
├── test_edit_tool.py                       # Core edit logic tests
├── test_server.py                          # MCP server integration
└── test_tool_arg_descriptions.py           # Schema/description tests
```

### Test categories

#### A. Validation Tests

Test that parameter validation catches errors correctly:

```python
class TestMatchTextLengthValidation:
    async def test_match_text_over_2000_chars_raises_error(self, temp_env):
        with pytest.raises(ValueError) as exc_info:
            await propose_and_review_logic(
                match_text="x" * 2001,  # Over limit
                ...
            )
        assert "ERROR: match_text is too long" in str(exc_info.value)
```

#### B. Error Message Tests

Verify error messages are helpful and suggest solutions:

```python
async def test_error_message_suggests_bypass(self, temp_env):
    error_message = str(exc_info.value)
    assert "edits" in error_message.lower()  # Suggests primary workaround
    assert "bypass_match_text_limit=True" in error_message  # Suggests last resort
    assert "LAST RESORT" in error_message  # Proper framing
```

#### C. Bypass/Override Tests

Test that safety bypasses work correctly:

```python
async def test_long_match_text_allowed_with_bypass(self, temp_env):
    # Should NOT raise "too long" error with bypass=True
    try:
        await asyncio.wait_for(
            propose_and_review_logic(
                match_text=long_content,
                bypass_match_text_limit=True  # Override
            ),
            timeout=2.0
        )
    except asyncio.TimeoutError:
        pass  # Validation passed, reached user wait
```

### Running tests

```bash
# Run all validation tests
python -m pytest tests/test_propose_and_review_validation.py -v

# Run specific test class
python -m pytest tests/test_propose_and_review_validation.py::TestBypassMatchTextLimit -v

# Run with coverage
python -m pytest tests/ --cov=fs_mcp --cov-report=term-missing
```

---

## 3. Testing Workflow for Tool Changes

### Before making changes

1. **Run existing tests** to establish baseline
2. **Document current behavior** you're modifying

### Making the change

1. **Update the code** (parameter names, validation logic, etc.)
2. **Update descriptions** to be clear and actionable
3. **Apply description best practices**:
   - Lead with purpose/requirement, not constraints
   - Include "COMMON MISTAKE" warnings for footguns
   - Provide concrete examples in docstrings
   - Use decision tree format for complex tools

### After changes

1. **Update unit tests** to match new parameter names/behavior
2. **Run all tests** to verify no regressions
3. **Run intern test** with the new schema
4. **Iterate** if the intern test reveals issues

---

## 4. Description Writing Best Practices

Based on Anthropic's tool use documentation:

### Do

- **Lead with purpose**: "REQUIRED for editing existing files: The exact text to find..."
- **Aim for 3-4+ sentences** for complex parameters
- **Include when to use AND when not to use**
- **Add concrete examples** in descriptions or docstrings
- **Warn about footguns explicitly**: "COMMON MISTAKE: Leaving this empty will FAIL..."

### Don't

- Lead with limits/constraints before explaining purpose
- Bury critical requirements at the end
- Assume the agent will read the full description
- Mix unrelated concerns (e.g., session handling in a parameter description)

### Example: Good vs Bad

**Bad** (leads with constraint):
```
"HARD LIMIT: Must be under 2000 characters. The text to find and replace..."
```

**Good** (leads with requirement):
```
"REQUIRED for editing existing files: The exact text currently in the file that you want to replace.

HOW TO USE:
1. First, use read_files to see the current content
2. Copy the EXACT lines you want to change into this parameter

COMMON MISTAKE: Leaving this empty will FAIL for existing files."
```

---

## 5. Checklist

Before merging tool schema changes:

- [ ] All existing unit tests pass
- [ ] New tests added for new functionality
- [ ] Error messages suggest solutions (not just state problems)
- [ ] Intern test completed with Haiku agent
- [ ] Descriptions lead with purpose, not constraints
- [ ] Footguns have explicit warnings
- [ ] Docstring includes quick start / common usage example

---

## References

- [Anthropic - Implement Tool Use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use)
- [Anthropic - Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [OpenAI - Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling)
