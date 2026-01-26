# Technology Stack

**Analysis Date:** 2026-01-26

## Languages

**Primary:**
- Python 3.10+ - Core server and CLI implementation

## Runtime

**Environment:**
- Python 3.10+ (specified in `.python-version`)
- Virtual environment via `.venv` with `uv` package manager

**Package Manager:**
- `uv` - Modern Python package manager with lockfile-based dependency resolution
- Lockfile: `uv.lock` (present)

## Frameworks

**Core MCP Server:**
- FastMCP 2.14.3 - Model Context Protocol server framework with HTTP and Stdio support
  - `stateless_http=True` for stateless HTTP operations

**Web UI:**
- Streamlit 1.30.0+ - Interactive web dashboard at port 8123
- streamlit-js-eval 0.1.5 - JavaScript evaluation within Streamlit

**API & HTTP:**
- FastAPI 0.128.0+ - HTTP server infrastructure (used via FastMCP's transport layer)
- httpx 0.28.1+ - Async HTTP client library

**External API Integration:**
- google-genai 1.56.0+ - Google Generative AI client with schema transformers
  - Used for Gemini API schema conversion and sanitization
  - Transformers: `google.genai._transformers` for JSON schema adaptation

**Data Validation:**
- Pydantic 2.0+ - Type validation and BaseModel definitions

**CLI & Utilities:**
- pyfiglet - ASCII art text rendering for CLI banners
- toml - TOML file parsing for `pyproject.toml` version reading

**HTTP Middleware:**
- Starlette (via FastAPI/FastMCP) - CORS middleware support
- CORSMiddleware - Cross-origin request handling for HTTP mode

## Key Dependencies

**Critical:**
- fastmcp 2.14.3 - Core MCP protocol implementation, enables Stdio and HTTP transports
- pydantic 2.0+ - Request validation using `BaseModel` for file operations
- google-genai 1.56.0+ - Enables Gemini schema sanitization in web UI

**Infrastructure:**
- streamlit 1.30.0+ - Web UI server and interactive testing dashboard
- fastapi 0.128.0+ - HTTP transport foundation for remote MCP connections
- httpx 0.28.1+ - Async HTTP operations for external calls

**Development:**
- pytest 8.0.0+ - Unit testing framework (dev dependency)
- python-semantic-release - Semantic versioning for GitHub releases
- build - Package building for PyPI distribution

## Configuration

**Environment:**
- Configured via CLI arguments passed to `fs-mcp` command
- Allowed directories specified as positional arguments: `fs-mcp /path/to/dir`
- No `.env` files required - configuration is command-line driven

**Build:**
- `pyproject.toml` - Package metadata, dependencies, build configuration
- Build system: `hatchling`
- Package name: `fs-mcp`
- Entry point: `fs-mcp = "fs_mcp.__main__:main"`

**Version Management:**
- Semantic release configuration in `pyproject.toml`
- Version updated in: `pyproject.toml:project.version`
- Version read from: Package metadata or `pyproject.toml` fallback

## Platform Requirements

**Development:**
- Python 3.10+ interpreter
- `uv` package manager installed
- `code` CLI available for VSCode diffs (optional, detected at runtime via `shutil.which('code')`)

**Production:**
- Python 3.10+ runtime
- Network access for Google GenAI (if using Gemini schema conversion)
- Ports 8123 (Streamlit UI) and 8124 (HTTP MCP) configurable via CLI flags

## Transport Modes

**Stdio Mode (Default):**
- Standard input/output for local agent connections (Claude Desktop)
- No HTTP overhead
- Command: `fs-mcp /path/to/dir`

**HTTP Mode (Background Process):**
- Stateless HTTP transport at configurable host/port (default: 0.0.0.0:8124)
- CORS enabled for cross-origin requests
- Starlette CORSMiddleware with `allow_origins=["*"]`
- Transport: `streamable-http`

**Web UI Mode (Foreground):**
- Streamlit dashboard at configurable host/port (default: 0.0.0.0:8123)
- Tool schema inspection and testing interface
- Gemini schema export for copy-paste integration

---

*Stack analysis: 2026-01-26*
