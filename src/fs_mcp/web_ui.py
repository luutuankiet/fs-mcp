import streamlit as st
import sys
import inspect
import json
import base64
import asyncio
import copy
from typing import Optional, Union, List, Dict, Any
from pathlib import Path
from dataclasses import asdict
from fastmcp.utilities.inspect import inspect_fastmcp
from streamlit_js_eval import streamlit_js_eval

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="FS-MCP", layout="wide", page_icon="📂")

# [NEW] Import Google GenAI transformers for schema standardization
try:
    from google.genai import _transformers
except ImportError:
    st.error("❌ 'google-genai' library not found. Please run: uv add google-genai")
    st.stop()

try:
    from fs_mcp import server
except ImportError:
    st.error("❌ Could not import 'fs_mcp.server'. Is the package installed?")
    st.stop()

# Initialize Config from CLI Args
try:
    if "--" in sys.argv:
        raw_args = sys.argv[sys.argv.index("--") + 1:]
    else:
        raw_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    server.initialize(raw_args)
except Exception as e:
    st.error(f"❌ Configuration Error: {e}")
    st.stop()

# --- 2. HEADER ---
st.title("📂 FS-MCP Explorer")
if not server.ALLOWED_DIRS:
    st.warning("⚠️ No directories configured! Defaulting to CWD.")

st.sidebar.header("Active Configuration")
st.sidebar.code("\n".join(str(d) for d in server.ALLOWED_DIRS))

# --- 3. TOOL DISCOVERY & SCHEMA EXPORT ---
tools = {}
tool_schemas = []
gemini_schemas = []

def prune_for_gemini_strictness(obj: Any) -> Any:
    """
    Recursively removes keys that are valid in JSON Schema/OpenAPI 
    but strictly forbidden by the Gemini Function Calling API.
    """
    # Keys forbidden by Gemini's strict validator
    FORBIDDEN_KEYS = {"default", "title", "property_ordering", "propertyOrdering"}

    if isinstance(obj, dict):
        return {
            k: prune_for_gemini_strictness(v) 
            for k, v in obj.items() 
            if k not in FORBIDDEN_KEYS
        }
    elif isinstance(obj, list):
        return [prune_for_gemini_strictness(i) for i in obj]
    return obj

def convert_to_gemini_schema(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses official google-genai transformers + strict pruning to adapt 
    schemas for Gemini Function Declarations.
    """
    # 1. Deep copy the input schema
    raw_schema = copy.deepcopy(tool_dict.get("input_schema", {}))
    
    # 2. Use the official library transformer to handle anyOf -> nullable
    # This handles the complex logic.
    _transformers.process_schema(raw_schema, client=None)
    
    # 3. [NEW] Strict Pruning
    # Gemini rejects "default", "title", and "property_ordering"
    clean_schema = prune_for_gemini_strictness(raw_schema)
    
    # 4. Ensure root type is object
    if "type" not in clean_schema:
        clean_schema["type"] = "object"
    if "properties" not in clean_schema:
        clean_schema["properties"] = {}

    return {
        "name": tool_dict["name"],
        "description": tool_dict.get("description", ""),
        "parameters": clean_schema
    }


try:
    # 1. Use the official inspect utility to get a structured server blueprint
    server_info = asyncio.run(inspect_fastmcp(server.mcp))

    # 2. Convert the ToolInfo dataclasses to dictionaries
    tool_schemas = [asdict(tool) for tool in server_info.tools]

    # 3. [NEW] Generate Gemini-compatible schemas using the official library
    gemini_schemas = [convert_to_gemini_schema(ts) for ts in tool_schemas]

    # 4. Map the functions for the UI to execute
    for tool_info in server_info.tools:
        name = tool_info.name
        if hasattr(server, name):
            wrapper = getattr(server, name)
            # Unwrap FastMCP decorators if needed
            fn = wrapper.fn if hasattr(wrapper, 'fn') else wrapper
            tools[name] = fn
        else:
            st.warning(f"Tool '{name}' has a schema but no matching function found in server.py")

except Exception as e:
    st.error(f"Failed to inspect MCP server: {e}")
    st.exception(e) 
    st.stop()

# --- SIDEBAR: EXPORT SECTION ---
with st.sidebar.expander("🔌 Gemini API Schemas", expanded=True):
    st.caption("Copy this JSON for Gemini Function Declarations:")
    st.code(json.dumps(gemini_schemas, indent=2), language="json")

with st.sidebar.expander("⚙️ Raw OpenAI MCP Schemas", expanded=False):
    st.caption("Internal MCP representation:")
    st.code(json.dumps(tool_schemas, indent=2), language="json")

# --- 4. EXECUTION HANDLER ---
def execute_tool(func, args):
    """Executes tool and returns both raw result and protocol view"""
    try:
        # Run the actual function
        result = func(**args)
        
        # Simulate Protocol Response (Agent View)
        protocol_response = {
            "content": [],
            "isError": False
        }
        
        # Format Content Block
        if isinstance(result, dict) and result.get("type") == "image":
            # Image protocol format
            protocol_response["content"].append({
                "type": "image",
                "data": result["data"],
                "mimeType": result.get("mimeType", "image/png")
            })
            display_type = "image"
        elif isinstance(result, (dict, list)):
            # Structured data usually sent as embedded text JSON
            text_content = json.dumps(result, indent=2)
            protocol_response["content"].append({
                "type": "text",
                "text": text_content
            })
            display_type = "json"
        else:
            # Plain text
            text_result = str(result)
            protocol_response["content"].append({
                "type": "text",
                "text": text_result
            })
            display_type = "text"
            
        return result, protocol_response, display_type, None
        
    except Exception as e:
        error_resp = {
            "content": [{"type": "text", "text": str(e)}],
            "isError": True
        }
        return None, error_resp, "error", str(e)


# --- 5. UI LOGIC ---
if not tools:
    st.error("No tools found.")
    st.stop()

selected = st.sidebar.radio("Available Tools", sorted(tools.keys()))
fn = tools[selected]
sig = inspect.signature(fn)

st.header(f"🔧 {selected}")
if inspect.getdoc(fn):
    st.info(inspect.getdoc(fn))

# INPUT TABS
tab_raw, tab_compact, tab_form = st.tabs(["📄 Raw JSON", "⚡ Compact JSON", "📝 Interactive Form"])

execution_args = None
trigger_run = False

# --- TAB 1: INTERACTIVE FORM ---
with tab_form:
    with st.form("interactive_form"):
        form_inputs = {}
        for name, param in sig.parameters.items():
            if name in ['ctx', 'context']: continue
            
            # Type Checking
            annotation = param.annotation
            is_number = (annotation in [int, float]) or (getattr(annotation, "__origin__", None) is Union and int in getattr(annotation, "__args__", []))
            is_bool = (annotation == bool) or (getattr(annotation, "__origin__", None) is Union and bool in getattr(annotation, "__args__", []))
            
            if name in ['path', 'source', 'destination']:
                def_val = str(server.ALLOWED_DIRS[0]) if server.ALLOWED_DIRS else ""
                form_inputs[name] = st.text_input(name, value=def_val)
            elif name == 'content':
                st.caption("Literal Content (WYSIWYG - Enter creates newlines)")
                form_inputs[name] = st.text_area(name, height=200)
            elif name == 'edits':
                st.write("Edits (JSON List)")
                val = st.text_area("JSON", value='[{"oldText": "foo", "newText": "bar"}]')
                form_inputs[name] = val # Parse later
            elif name in ['exclude_patterns', 'paths']:
                val = st.text_area(f"{name} (one per line)")
                form_inputs[name] = val
            elif is_bool:
                form_inputs[name] = st.checkbox(name)
            elif is_number:
                form_inputs[name] = st.number_input(name, value=0)
            else:
                form_inputs[name] = st.text_input(name)
        
        if st.form_submit_button("Run Form"):
            # Process Form Inputs
            try:
                processed = {}
                for k, v in form_inputs.items():
                    # Handle lists
                    if k in ['exclude_patterns', 'paths']:
                        processed[k] = [x.strip() for x in v.split('\n') if x.strip()]
                    # Handle JSON fields
                    elif k == 'edits':
                        processed[k] = json.loads(v)
                    # Handle Optionals
                    elif v == 0 and k in ['head', 'tail']:
                        processed[k] = None
                    else:
                        processed[k] = v
                execution_args = processed
                trigger_run = True
            except Exception as e:
                st.error(f"Form Error: {e}")

# --- TAB 2 & 3: JSON INPUTS ---
# Helper to generate template
default_args = {}
for name, param in sig.parameters.items():
    if name in ['ctx', 'context']: continue
    if name in ['path', 'source', 'destination']:
        default_args[name] = str(server.ALLOWED_DIRS[0]) if server.ALLOWED_DIRS else ""
    elif name == 'content': default_args[name] = "Line 1\nLine 2"
    elif name == 'paths': default_args[name] = [str(server.ALLOWED_DIRS[0])] if server.ALLOWED_DIRS else []
    else: default_args[name] = ""

json_template = json.dumps(default_args, indent=2)

with tab_raw:
    with st.form("json_raw_form"):
        raw_text = st.text_area("JSON Input", value=json_template, height=300)
        if st.form_submit_button("Run Raw JSON"):
            try:
                execution_args = json.loads(raw_text)
                trigger_run = True
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

with tab_compact:
    with st.form("json_compact_form"):
        compact_text = st.text_input("One-line JSON", value=json.dumps(default_args))
        if st.form_submit_button("Run Compact JSON"):
            try:
                execution_args = json.loads(compact_text)
                trigger_run = True
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

# --- OUTPUT DISPLAY ---
if trigger_run and execution_args is not None:
    st.divider()
    
    with st.spinner("Running tool..."):
        res_raw, res_proto, dtype, err = execute_tool(fn, execution_args)

    json_response = json.dumps(res_proto, indent=None)
    escaped_json = json.dumps(json_response)
    streamlit_js_eval(js_expressions=f"navigator.clipboard.writeText({escaped_json})")
    if err:
        st.error("Tool Execution Failed")
        st.toast("Something went wrong - error copied to clipboard", icon="❌")
    else:
        st.success("Tool Execution Successful")
        st.toast("Tool response copied to clipboard!", icon="✅")

    col_human, col_agent = st.columns(2)
    
    with col_human:
        st.subheader("👀 Human View")
        if err:
            st.error(err)
        elif dtype == "image":
            st.image(base64.b64decode(res_proto["content"][0]["data"]))
        elif dtype == "json":
            st.json(res_raw)
        else:
            text = str(res_raw)
            if text.startswith("---") or text.startswith("+++"):
                st.code(text, language="diff")
            else:
                st.code(text)

    with col_agent:
        st.subheader("🤖 Agent Protocol View")
        st.caption("This is exactly what the LLM receives.")
        st.code(json.dumps(res_proto, indent=None), language="json")