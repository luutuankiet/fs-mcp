# filesystem-mcp 📂

**An interactive filesystem MCP server**

---


https://github.com/user-attachments/assets/132acdd9-014c-4ba0-845a-7db74644e655


## Why This Exists

If you're building agents or using tools like gemini chat / google ai studio, you know the struggle: the webapp doesn't give you direct MCP tool use. Getting Gemini access to your project files is non-trivial and often involve manual copy-pasting.

**FS-MCP solves this.** It's a single, dependency-free (via `uv`) Python package that gives you:
1.  **Strict Security**: Sandbox enforcement so agents can't touch `/etc/passwd` or escape via symlinks.
2.  **Dual Mode by Default**: Launch a standard MCP server PLUS a built-in inspector Streamlit Web UI simultaneously. No more jumping through hoops with npm inspector clients.
4.  **Zero Config**: Run it instantly with `uvx`. No cloning required.

**The goal:** A filesystem tool that is robust enough for production agents but friendly enough for quick local debugging.

---

## What You Get

### 🤖 For Agents (HTTP/Stdio Mode)
A full suite of tools optimized for LLM consumption:
- **`edit_file`**: Precise "Find and Replace" with `expected_replacements` validation. No more accidental file mangling.
- **`append_text`**: A reliable fallback for dumping content to the end of files when diffs get too complex.
- **`read_multiple_files`**: Read 10+ files in one turn (saves tokens & round-trips).
- **`directory_tree`**: High-performance recursive views with smart ignores (`.venv`, `.git`) and depth limits.

### 👨‍💻 For Humans (Web UI Explorer)
The built-in UI is now a first-class citizen:
- **Auto-Copy Clipboard**: Successful tool responses are instantly copied to your clipboard. Run a tool in the UI, paste the result into Claude. Done.
- **Native Schema Discovery**: Uses FastMCP's internal inspection to export 100% accurate JSON schemas for your agent configuration.
- **Live Tool Testing**: Run tools manually with an interactive form to verify behavior.

---

## Quick Start

### 1. Run Instantly
By default, this command launches the **Web UI (8123)** and a **Background HTTP Server (8124)**.

```bash
# Allow access to the current dir
uvx fs-mcp .
```

### 2. Selective Launch (Flags)
Want to disable a component? Use the inverted "No" flags:
```bash
# UI Only
fs-mcp --no-http .

# HTTP Only (Headless)
fs-mcp --no-ui .
```

### 3. Configure Claude Desktop
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fs-mcp": {
      "command": "uvx",
      "args": [
        "--from", "fs-mcp", "fs-mcp", "--no-ui",
        "/absolute/path/to/your/project"
      ]
    }
  }
}
```

---

## The Toolbox 🧰

| Tool | Description |
|------|-------------|
| `list_allowed_directories` | List the directories this server is allowed to access. |
| `list_directory` | Get a detailed listing of all files and directories. |
| `list_directory_with_sizes` | Get listing with file sizes. |
| `directory_tree` | **Fast:** Returns recursive JSON tree. Skips `.venv`/`.git` automatically. |
| `search_files` | **Fast:** Recursive pattern discovery using `rglob`. |
| `get_file_info` | Metadata retrieval (size, modified time, etc.). |
| `read_text_file` | Read text file contents. |
| `read_multiple_files` | Reads content of multiple files. Essential for context loading. |
| `read_media_file` | Returns base64 encoded images/audio. |
| `write_file` | Creates or overwrites files (atomic operations). |
| `create_directory` | Create a new directory or ensure it exists. |
| `move_file` | Move or rename files. |
| `edit_file` | Robust find/replace with occurrence safety checks. |
| `append_text` | Safe fallback for appending content to EOF. |
| `grounding_search` | Placeholder for custom RAG/Search implementations. |

---

## License & Credits

Built with ❤️ for the MCP Community by **luutuankiet**.
Powered by **FastMCP** and **Streamlit**.

**Now go build some agents.** 🚀

