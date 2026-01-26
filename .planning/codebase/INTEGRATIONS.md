# External Integrations

**Analysis Date:** 2026-01-26

## APIs & External Services

**Google Generative AI (Gemini):**
- google-genai 1.56.0+
- Purpose: Schema transformation for Gemini Function Declarations
- SDK/Client: `google.genai` with `_transformers` module
- Usage: `web_ui.py` converts OpenAPI/JSON Schema to Gemini-compatible format
- Auth: Assumed external (not handled by fs-mcp, client responsibility)
- Key function: `_transformers.process_schema()` for schema adaptation

## Data Storage

**Databases:**
- None detected - Stateless filesystem server only
- No ORM or database client dependencies

**File Storage:**
- Local filesystem only
- Security: Sandboxed access via `ALLOWED_DIRS` validation
- Temporary storage: System temp directory (`tempfile.gettempdir()`) for review sessions
- Session paths: `mcp_review_*` directories for interactive diff sessions

**Caching:**
- None detected - No caching framework or service

## Authentication & Identity

**Auth Provider:**
- Custom - No third-party auth service
- Implementation: Directory-based access control
  - `USER_ACCESSIBLE_DIRS` - user-specified paths
  - `ALLOWED_DIRS` - union of user dirs + temp directory
  - Path validation: `validate_path()` checks canonical path is within allowed bounds
  - Symlink resolution: `.resolve()` canonicalizes paths, preventing directory traversal

**Security Considerations:**
- Relative paths resolved against first allowed directory
- Temp directory access restricted to `mcp_review_*` and `pytest-*` subdirectories
- Strict checking on temp dir contents for review files

## Monitoring & Observability

**Error Tracking:**
- None detected - No error tracking service integrated

**Logs:**
- Console output via stderr
- Log messages prefixed with emoji indicators
- Status messages: `print(..., file=sys.stderr)`
- Subprocess output: HTTP server stdout/stderr piped to main stderr

## CI/CD & Deployment

**Hosting:**
- PyPI package distribution
- GitHub releases via semantic versioning

**CI Pipeline:**
- GitHub Actions (`release.yaml`)
- Trigger: Push to `main` branch or manual `workflow_dispatch`
- Steps:
  1. Checkout repository (full history for versioning)
  2. Python 3.11 setup
  3. Install release tools: `python-semantic-release`, `build`
  4. Semantic version bump and commit
  5. Build wheel package
  6. Create GitHub Release
  7. Publish to PyPI using `pypa/gh-action-pypi-publish`
- Secrets: `GITHUB_TOKEN` (automatic), `PYPI_TOKEN` (must be set)
- Permissions: `contents:write` (for git commits/tags), `id-token:write` (PyPI trusted publishing)

## Environment Configuration

**Required env vars:**
- None - All configuration via CLI arguments
- VSCode integration: Detected dynamically (optional)
- No API keys needed for core filesystem operations
- Google GenAI key: Client-side (not handled by fs-mcp)

**Secrets location:**
- No secrets stored by fs-mcp
- GitHub: Secrets stored in repository settings
  - `PYPI_TOKEN` - Personal access token for PyPI

## Webhooks & Callbacks

**Incoming:**
- None detected - No webhook endpoints

**Outgoing:**
- VSCode diff window: Opens via `code --diff <old> <new>` subprocess call
  - Trigger: `propose_and_review` tool activation
  - Used by: Human-in-the-loop review workflow

## Tool Schema Transformation Pipeline

**Flow:**
1. FastMCP introspection: `inspect_fastmcp()` extracts tool metadata
2. OpenAPI schema export: Tool definitions with JSON Schema parameters
3. Gemini transformation: `convert_to_gemini_schema()` prepares schemas
   - Calls: `_transformers.process_schema()` for anyOf → nullable conversion
   - Prunes forbidden keys: `default`, `title`, `property_ordering`, `propertyOrdering`
4. Web UI export: User copies Gemini-compatible JSON for Function Declarations
5. Agent integration: Schema pasted directly into Google AI Studio or other Gemini clients

## Subprocess Integrations

**HTTP Server Subprocess:**
- Launched via `subprocess.Popen()` in background
- Process management: `terminate()` on exit, fallback to `kill()`
- Timeout: 5 seconds for graceful shutdown
- Inherit parent's allowed directories and configuration

**Streamlit UI Subprocess:**
- Launched via `subprocess.run()` (blocking)
- Args passed via CLI: port, host, directories
- Subprocess inherits sys.argv with `--` separator

**VSCode Diff Editor:**
- Launched via `subprocess.Popen()` with `code --diff` command
- Blocks and waits for user to save
- File watch loop: Checks modification time every second (configurable)
- Session management: Temp files cleaned up after review

---

*Integration audit: 2026-01-26*
