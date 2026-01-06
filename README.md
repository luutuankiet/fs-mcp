# fs-mcp 📂

**The "Human-in-the-Loop" Filesystem MCP Server**

---

https://github.com/user-attachments/assets/132acdd9-014c-4ba0-845a-7db74644e655

## 💡 Why This Exists

I built this because I was tired of jumping through hoops.

The promise of the Model Context Protocol (MCP) is incredible, but the reality of using the standard filesystem server hit a few walls for my workflow:

1. **The Container Gap:** I do most of my work in Docker. Connecting a local agent (like Claude Desktop) to a filesystem inside a container via Stdio is a networking nightmare.
2. **The Free Tier Lockout:** I wanted to use the free tier of [Google AI Studio](https://aistudio.google.com/) to edit code, but you can't easily plug MCP into a web interface.
3. **Schema Hell:** Even if you *do* copy-paste schemas into Gemini, they often break because Gemini's strict validation is only a [subset of the standard OpenAPI spec](https://ai.google.dev/gemini-api/docs/function-calling).

**fs-mcp solves this.** It is a Python-based server built on `fastmcp` that treats "Human-in-the-Loop" as a first-class citizen.

---

## 🚀 Key Features

### 1. HTTP by Default (Remote Ready)

It runs a background HTTP server alongside the CLI. You can finally connect agents to remote environments or containers without SSH tunneling wizardry.

### 2. Zero-Config Inspector

No `npm install inspector`. I baked a **Streamlit Web UI** directly into the package. Launch it, and you instantly have a visual form to test tools, view results, and generate configs.

### 3. Copy-Paste Gemini Schemas 📋

The UI automatically sanitizes and translates your tool schemas specifically for **Google GenAI**. It strips forbidden keys (`default`, `title`, etc.) so you can paste function definitions directly into AI Studio and start coding for free.

### 4. Agent-Safe Editing 🛡️

Includes a **Roo-Code style `edit_file` tool** with `expected_replacements` validation. This prevents the agent from accidentally mangling your code if it hallucinates line numbers or context.

---

## ⚡ Quick Start

### Run Instantly

By default, this command launches the **Web UI (8123)** and a **Background HTTP Server (8124)**.

```bash
# Allow access to the current dir
uvx fs-mcp .
```

### Selective Launch

Want to disable a component? Use the flags:

```bash
# UI Only (No background HTTP)
fs-mcp --no-http .

# HTTP Only (Headless / Docker mode)
fs-mcp --no-ui .
```

---

## 🔌 Configuration

### Claude Desktop (Stdio Mode)

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fs-mcp": {
      "command": "uvx",
      "args": [
        "fs-mcp",
        "/absolute/path/to/your/project"
      ]
    }
  }
}
```

### Docker (HTTP Mode)

To run inside a container and expose the filesystem to a local agent:

```bash
# In your entrypoint or CMD
uvx fs-mcp --no-ui --http-host 0.0.0.0 --http-port 8124 /app
```

---

## The Toolbox 🧰

| Tool                       | Description                                                                |
| -------------------------- | -------------------------------------------------------------------------- |
| `edit_file`                | **Star Feature:** Robust find/replace with occurrence safety checks.       |
| `read_multiple_files`      | Reads content of multiple files to save context window.                    |
| `directory_tree`           | **Fast:** Returns recursive JSON tree. Skips `.venv`/`.git` automatically. |
| `search_files`             | Recursive pattern discovery using `rglob`.                                 |
| `list_allowed_directories` | List security-approved paths.                                              |
| `list_directory`           | Detailed file listings.                                                    |
| `get_file_info`            | Metadata retrieval (size, modified time).                                  |
| `read_media_file`          | Returns base64 encoded images/audio.                                       |
| `write_file`               | Creates or overwrites files (atomic operations).                           |
| `create_directory`         | Create a new directory.                                                    |
| `move_file`                | Move or rename files.                                                      |
| `append_text`              | Safe fallback for appending content to EOF.                                |

---

## License & Credits

Built with ❤️ for the MCP Community by **luutuankiet**.
Powered by **FastMCP** and **Streamlit**.

**Now go build some agents.** 🚀

