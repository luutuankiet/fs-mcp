# fs-mcp v2

**A portal MCP server.** Teleport your AI agent into any directory on any host — and hand it a 9-tool kit that feels like Claude Code's native tools.

Single static Go binary. ~11 MB. Cold-start under 10 ms. No runtime, no venv, no Docker. Linux + macOS (amd64 & arm64).

[![Release](https://img.shields.io/github/v/release/luutuankiet/fs-mcp)](https://github.com/luutuankiet/fs-mcp/releases/latest)

---

## Design

| v1 (Python) | v2 (Go) |
|---|---|
| 23 tools | **9 core tools** |
| 3077-line server.py monolith | Per-tool files, struct-tag schemas |
| Duplicated docstrings + Pydantic `Field(...)` on every param | **Single source of truth** — struct tags |
| Responses stringified with `json.dumps(...)` | Native `structuredContent` JSON objects |
| Required jq/yq/rg pre-installed by user | **Auto-bootstrapped** to `~/.local/bin` (pinned versions) |
| Sandboxed, restricted `run_command` | **Portal trust** — SSH-style: the agent drives the machine |
| Explicit `fs-mcp <dir>` to pick allowed dirs | **Auto-detected** mount root (headless → `/`, dev → `$HOME`) |
| Streamlit UI, Gemini schema layer, HTTP+Stdio dual mode, GSD analyzer, fakeredis | Stripped. Stdio default, optional HTTP. |
| `query_jq`, `query_yq`, `grep_content` | Renamed to `jq`, `yq`, `grep` |
| Two-step `propose_and_review` + `commit_review` | Native-style **single-step `edit`** (atomic find-replace, fails on ambiguity) |

## Install

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/luutuankiet/fs-mcp/v2/scripts/install.sh | sh
# or grab the tarball for your platform from GitHub Releases
```

First run self-installs `jq` 1.8.1, `yq` v4.52.5, `rg` 14.1.1, and `rtk` 0.37.0 into `$HOME/.local/bin`. Subsequent starts take ~10 ms. Prefer your own system copies? set `FS_MCP_PREFER_SYSTEM=1`.

## Quick start

```bash
# stdio (default)
fs-mcp

# HTTP streamable
fs-mcp --http :8124

# point at a specific root
fs-mcp /path/to/project
fs-mcp --print-root   # show what root it picked

# deps probe
fs-mcp --doctor
```

Claude Desktop config:

```json
{
  "mcpServers": {
    "fs-mcp": { "command": "fs-mcp" }
  }
}
```

## The 9 tools

| Tool | Contract |
|---|---|
| `read_files` | `files: [{path, offset?, limit?, tail?, read_to_next_pattern?}]` — batch read, no char cap |
| `grep` | ripgrep. `--no-follow --one-file-system --max-filesize=50M --threads=2`; auto `--max-depth=4` when root is `/` or network FS |
| `jq` | `{file, expression}` — returns all matches as a JSON array, no 100-line cap |
| `yq` | Same contract as `jq`. mikefarah's yq; supports yaml/json/xml/toml/csv/tsv/ini/hcl |
| `run_command` | `sh -c` execution. No allowlist, no sandbox. Portal trust. |
| `directory_tree` | Walk. Same depth guards as grep |
| `edit` | `{file_path, old_string, new_string, replace_all?}` — atomic find-replace. Fails on 0 matches or ambiguous match |
| `write` | `{file_path, content}` — overwrite/create, auto-mkdir parents |
| `create_directory` | `mkdir -p`, idempotent |

Every response is a native JSON object in `structuredContent` — no stringified nesting.

## Portal root detection

```
FS_MCP_ROOT env var  >  CLI arg  >  headless heuristic  >  $HOME  >  /
```

**Headless** = `$SSH_CONNECTION` set, `$XDG_SESSION_TYPE=tty`, or no `$DISPLAY`/`$WAYLAND_DISPLAY`. The server logs which rule fired on startup.

## Build

```bash
go build -o bin/fs-mcp ./cmd/fs-mcp
```

Go 1.25+ required. No other build deps.

## Migrating from v1

v1 (the Python package on PyPI) will ship a final `1.48.0` with a deprecation banner pointing here. v2 is **not** PyPI-distributed — it's single-binary via GitHub Releases. See `releases/v2.0.0.md` for the full break list.

## Safety

- **No sandbox.** fs-mcp trusts its MCP client the way ssh trusts you. If the client is compromised, the box is compromised. Design explicit.
- **rg never DOSes itself.** The `--one-file-system` + auto-depth-cap guards the portal against NAS-mount symlink loops that crashed the v1 server.
- **Bootstrap only writes `$HOME/.local/bin`.** Shell rc files are never touched. The subprocess's `$PATH` is wired in-process only.

## License

MIT
