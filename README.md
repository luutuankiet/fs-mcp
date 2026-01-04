# filesystem-mcp 📂

**A secure, production-grade filesystem server for the Model Context Protocol (MCP).**

*Bridge your local files to LLMs safely. Works with Claude Desktop, Cursor, and any MCP-compliant agent.*

---

## Why This Exists

If you're building agents or using tools like Claude Desktop, you know the struggle: giving an LLM access to your files is often "all or nothing" and setting up a proper server usually involves Node.js dependency hell.

**FS-MCP solves this.** It's a single, dependency-free (via `uv`) Python package that gives you:
1.  **Strict Security**: Sandbox enforcement so agents can't touch `/etc/passwd` or escape via symlinks.
2.  **Dual Mode**: A standard MCP server for agents, PLUS a built-in Streamlit Web UI for *you* to inspect and debug.
3.  **Zero Config**: Run it instantly with `uvx`. No cloning required.

**The goal:** A filesystem tool that is robust enough for production agents but friendly enough for quick local debugging.

---

## What You Get

### 🤖 For Agents (Stdio Mode)
A full suite of tools optimized for LLM consumption:
- **`read_multiple_files`**: Read 10+ files in one turn (saves tokens & round-trips).
- **`edit_file`**: Git-style diff patching (safer than overwriting).
- **`search_files`**: Smart globbing that respects `.gitignore` patterns.
- **`directory_tree`**: Recursive JSON tree views for understanding project structure.

### 👨‍💻 For Humans (Web UI Mode)
Run with `--ui` and get a full-blown file explorer in your browser:
- **Live Tool Testing**: Run tools manually before giving them to an agent.
- **Protocol View**: See exactly what JSON the agent receives (great for debugging hallucinations).
- **Schema Export**: One-click copy JSON schemas for your agent configuration.
- **Remote Access**: Host it on a server (`0.0.0.0`) and debug files remotely.

### 🛡️ Security First
- **Allowlist Only**: You must explicitly list allowed directories.
- **Path Traversal Protection**: Blocks `../../` attacks.
- **Symlink Resolution**: Prevents symlinks from pointing outside the sandbox.

---

## Quick Start

### 1. Run Instantly (No Install)
Using `uvx` (recommended), you can run this anywhere without polluting your python environment.

**Agent Mode (Stdio):**
```bash
# Allow access only to your current project
uvx --from fs-mcp fs-mcp .
```

**Web UI Mode (Interactive):**
```bash
# Launch the explorer on localhost:8501
uvx --from fs-mcp fs-mcp --ui .
```

### 2. Configure Claude Desktop
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "my-files": {
      "command": "uvx",
      "args": [
        "--from", "fs-mcp", "fs-mcp",
        "/Users/me/Projects/my-app",
        "/Users/me/Documents/notes"
      ]
    }
  }
}
```

---

## The Toolbox 🧰

| Tool | Description |
|------|-------------|
| `read_multiple_files` | Reads content of multiple files. Essential for context loading. |
| `write_file` | Creates or overwrites files (atomic operations). |
| `edit_file` | Precise string replacement with diff output. |
| `search_files` | Finds files matching glob patterns (e.g., `**/*.py`). |
| `directory_tree` | Returns a nested JSON structure of folders. |
| `list_directory_with_sizes` | Detailed listing with file sizes. |
| `read_media_file` | Returns base64 encoded images/audio. |
| `move_file` | Renames or moves files. |
| `create_directory` | Recursive directory creation (`mkdir -p`). |

---

## Remote Usage (SSH)

Want to expose a remote server's filesystem to your local browser securely?

1.  **On Remote Server:**
    ```bash
    uvx --from fs-mcp fs-mcp --ui --host 0.0.0.0 --port 9090 /path/to/expose
    ```

2.  **On Local Machine (SSH Tunnel):**
    ```bash
    ssh -L 9090:localhost:9090 user@remote-server
    ```

3.  **Open Browser:**
    Go to `http://localhost:9090`. You now have a full GUI for your remote files.

---

## Development

Want to hack on this?

```bash
# Clone it
git clone https://github.com/yourusername/fs-mcp.git
cd fs-mcp

# Install dependencies
uv sync

# Run tests
uv run pytest

# Run locally
uv run fs-mcp --ui .
```

---

## License & Credits

Built with ❤️ for the MCP Community.
Powered by **FastMCP** and **Streamlit**.

**Now go build some agents.** 🚀
