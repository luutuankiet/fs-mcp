"""
Schema Transformation Pipeline for Gemini Compatibility

Implements all 22 transformation patterns from LOG-002 to convert
standard JSON Schema (from Pydantic) to Gemini-compatible format.

Reference: LOG-002 Section 6 (Complete Transformation Checklist)
"""

import copy
from typing import Any

# Optional: jsonref for $ref dereferencing
try:
    import jsonref
    HAS_JSONREF = True
except ImportError:
    HAS_JSONREF = False


# Keys that must be removed from schemas (from LOG-002 Section 4 & 5)
FORBIDDEN_KEYS = frozenset({
    # Not in Gemini Schema spec
    "$id",
    "$schema",
    "additionalProperties",
    "const",  # Will be transformed to enum instead of just removed
    "not",
    "dependentRequired",
    "dependentSchemas",
    "prefixItems",
    "contains",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contentMediaType",
    "contentEncoding",
    "multipleOf",
    "exclusiveMinimum",  # Will be transformed to minimum
    "exclusiveMaximum",  # Will be transformed to maximum
    # Documented but problematic (LOG-002 Section 5)
    "title",
    "default",
    "propertyOrdering",
    "property_ordering",  # snake_case variant
})

# Keys to remove AFTER dereferencing (they contain the definitions)
DEFS_KEYS = frozenset({"$defs", "definitions"})

# Keys for conditional schemas (not supported)
CONDITIONAL_KEYS = frozenset({"if", "then", "else"})


def transform_for_gemini(schema: dict) -> tuple[dict, list[str]]:
    """
    Apply full transformation pipeline to make schema Gemini-compatible.
    
    Args:
        schema: Raw JSON Schema (possibly with $ref, $defs, etc.)
        
    Returns:
        Tuple of (transformed_schema, list_of_changes_made)
        
    Example:
        >>> schema = {"$defs": {...}, "items": {"$ref": "#/$defs/X"}}
        >>> transformed, changes = transform_for_gemini(schema)
        >>> "$ref" not in str(transformed)
        True
    """
    changes = []
    result = copy.deepcopy(schema)
    
    # Phase 1: Dereference $ref (CRITICAL - must be first)
    result, ref_changes = _dereference_refs(result)
    changes.extend(ref_changes)
    
    # Phase 2: Remove $defs/$definitions (after dereferencing)
    result, defs_changes = _remove_defs(result)
    changes.extend(defs_changes)
    
    # Phase 3: Handle anyOf/oneOf/allOf
    result, union_changes = _handle_union_types(result)
    changes.extend(union_changes)
    
    # Phase 4: Convert const to enum
    result, const_changes = _convert_const_to_enum(result)
    changes.extend(const_changes)
    
    # Phase 5: Handle exclusive bounds
    result, bounds_changes = _handle_exclusive_bounds(result)
    changes.extend(bounds_changes)
    
    # Phase 6: Remove forbidden keys
    result, forbidden_changes = _remove_forbidden_keys(result)
    changes.extend(forbidden_changes)
    
    # Phase 7: Remove conditional schemas
    result, cond_changes = _remove_conditional_schemas(result)
    changes.extend(cond_changes)
    
    # Phase 8: Uppercase type values (optional but recommended)
    result, type_changes = _uppercase_types(result)
    changes.extend(type_changes)
    
    return result, changes


def _dereference_refs(schema: dict) -> tuple[dict, list[str]]:
    """
    Dereference all $ref using jsonref library.
    
    This is the CRITICAL transformation - without it, nested objects
    degrade to STRING in Gemini.
    """
    changes = []
    
    if not HAS_JSONREF:
        # Can't dereference without jsonref - just note it
        if _contains_key(schema, "$ref"):
            changes.append("WARNING: jsonref not installed, cannot dereference $ref")
        return schema, changes
    
    # Check if there are any $refs to dereference
    if not _contains_key(schema, "$ref"):
        return schema, changes
    
    # Count refs before dereferencing
    ref_count = _count_key_occurrences(schema, "$ref")
    
    # Use jsonref to inline all references
    try:
        dereferenced = jsonref.replace_refs(schema, lazy_load=False)
        # Convert back to regular dict (jsonref returns proxy objects)
        result = _deep_dict(dereferenced)
        changes.append(f"Dereferenced {ref_count} $ref occurrence(s)")
        return result, changes
    except Exception as e:
        changes.append(f"WARNING: Failed to dereference $ref: {e}")
        return schema, changes


def _remove_defs(schema: dict) -> tuple[dict, list[str]]:
    """Remove $defs and definitions blocks after dereferencing."""
    changes = []
    result = copy.deepcopy(schema)
    
    for key in DEFS_KEYS:
        if key in result:
            del result[key]
            changes.append(f"Removed {key} block")
    
    return result, changes


def _handle_union_types(schema: dict) -> tuple[dict, list[str]]:
    """
    Handle anyOf, oneOf, and allOf constructs.
    
    - anyOf with null: Convert to {type: T, nullable: true}
    - oneOf: Convert to anyOf
    - allOf: Merge schemas
    """
    changes = []
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        
        for key, value in node.items():
            if key == "anyOf" and isinstance(value, list):
                # Check for nullable pattern: anyOf[{type: X}, {type: null}]
                non_null = [v for v in value if not _is_null_type(v)]
                has_null = any(_is_null_type(v) for v in value)
                
                if has_null and len(non_null) == 1:
                    # Convert to nullable
                    inner = process_node(non_null[0], f"{path}.anyOf[0]")
                    result.update(inner)
                    result["nullable"] = True
                    changes.append(f"Converted anyOf[T, null] to nullable at {path}")
                elif len(value) == 1:
                    # Single-item anyOf, just unwrap
                    result.update(process_node(value[0], f"{path}.anyOf[0]"))
                    changes.append(f"Unwrapped single-item anyOf at {path}")
                else:
                    # Keep anyOf but process children
                    result["anyOf"] = [process_node(v, f"{path}.anyOf[{i}]") 
                                       for i, v in enumerate(value)]
            
            elif key == "oneOf" and isinstance(value, list):
                # Convert oneOf to anyOf (Gemini only supports anyOf)
                result["anyOf"] = [process_node(v, f"{path}.oneOf[{i}]") 
                                   for i, v in enumerate(value)]
                changes.append(f"Converted oneOf to anyOf at {path}")
            
            elif key == "allOf" and isinstance(value, list):
                # Merge all schemas in allOf
                merged = {}
                for i, sub in enumerate(value):
                    processed = process_node(sub, f"{path}.allOf[{i}]")
                    merged = _merge_schemas(merged, processed)
                result.update(merged)
                changes.append(f"Merged allOf schemas at {path}")
            
            elif key == "properties" and isinstance(value, dict):
                result["properties"] = {
                    k: process_node(v, f"{path}.properties.{k}")
                    for k, v in value.items()
                }
            
            elif key == "items" and isinstance(value, dict):
                result["items"] = process_node(value, f"{path}.items")
            
            elif isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


def _convert_const_to_enum(schema: dict) -> tuple[dict, list[str]]:
    """Convert const to single-value enum."""
    changes = []
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        for key, value in node.items():
            if key == "const":
                result["enum"] = [value]
                changes.append(f"Converted const to enum at {path}")
            elif isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


def _handle_exclusive_bounds(schema: dict) -> tuple[dict, list[str]]:
    """Convert exclusiveMinimum/exclusiveMaximum to minimum/maximum."""
    changes = []
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        for key, value in node.items():
            if key == "exclusiveMinimum":
                result["minimum"] = value
                changes.append(f"Converted exclusiveMinimum to minimum at {path}")
            elif key == "exclusiveMaximum":
                result["maximum"] = value
                changes.append(f"Converted exclusiveMaximum to maximum at {path}")
            elif isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


def _remove_forbidden_keys(schema: dict) -> tuple[dict, list[str]]:
    """Remove all forbidden keys recursively."""
    changes = []
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        for key, value in node.items():
            if key in FORBIDDEN_KEYS:
                changes.append(f"Removed forbidden key '{key}' at {path}")
                continue
            
            if isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


def _remove_conditional_schemas(schema: dict) -> tuple[dict, list[str]]:
    """Remove if/then/else constructs."""
    changes = []
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        for key, value in node.items():
            if key in CONDITIONAL_KEYS:
                changes.append(f"Removed conditional key '{key}' at {path}")
                continue
            
            if isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


def _uppercase_types(schema: dict) -> tuple[dict, list[str]]:
    """Convert lowercase type values to uppercase for Gemini consistency."""
    changes = []
    type_map = {
        "string": "STRING",
        "number": "NUMBER",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
        "null": "NULL",
    }
    
    def process_node(node: Any, path: str = "$") -> Any:
        if not isinstance(node, dict):
            return node
        
        result = {}
        for key, value in node.items():
            if key == "type" and isinstance(value, str):
                upper = type_map.get(value.lower(), value)
                if upper != value:
                    changes.append(f"Uppercased type '{value}' to '{upper}' at {path}")
                result[key] = upper
            elif isinstance(value, dict):
                result[key] = process_node(value, f"{path}.{key}")
            elif isinstance(value, list):
                result[key] = [
                    process_node(v, f"{path}.{key}[{i}]") if isinstance(v, dict) else v
                    for i, v in enumerate(value)
                ]
            else:
                result[key] = value
        
        return result
    
    return process_node(schema), changes


# ============== Helper Functions ==============

def _is_null_type(schema: dict) -> bool:
    """Check if schema represents null type."""
    if not isinstance(schema, dict):
        return False
    return schema.get("type") in ("null", "NULL")


def _contains_key(obj: Any, key: str) -> bool:
    """Recursively check if key exists in nested structure."""
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_contains_key(v, key) for v in obj.values())
    elif isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


def _count_key_occurrences(obj: Any, key: str) -> int:
    """Count occurrences of key in nested structure."""
    count = 0
    if isinstance(obj, dict):
        if key in obj:
            count += 1
        for v in obj.values():
            count += _count_key_occurrences(v, key)
    elif isinstance(obj, list):
        for v in obj:
            count += _count_key_occurrences(v, key)
    return count


def _deep_dict(obj: Any) -> Any:
    """Convert jsonref proxy objects back to regular dicts."""
    if isinstance(obj, dict):
        return {k: _deep_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_dict(v) for v in obj]
    else:
        return obj


def _merge_schemas(base: dict, overlay: dict) -> dict:
    """Merge two schemas for allOf handling."""
    result = copy.deepcopy(base)
    
    for key, value in overlay.items():
        if key == "properties" and "properties" in result:
            result["properties"] = {**result["properties"], **value}
        elif key == "required" and "required" in result:
            result["required"] = list(set(result["required"]) | set(value))
        else:
            result[key] = value
    
    return result