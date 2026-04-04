import json
import re
import itertools
import os
import base64
import mimetypes
import fnmatch
from pathlib import Path
from typing import List, Optional, Literal, Dict, Annotated, Tuple
from datetime import datetime
from dataclasses import dataclass
from pydantic import BaseModel, Field
from fastmcp import FastMCP
import tempfile
import time
import sys
import urllib.request
import urllib.error
import shutil
import subprocess
import threading
import duckdb
import math

from .edit_tool import EditResult, RooStyleEditTool, propose_and_review_logic, apply_file_edits, MATCH_TEXT_MAX_LENGTH
from .utils import check_ripgrep, check_jq, check_yq, check_rtk, check_required_dependencies
from .gsd_lite_analyzer import analyze_gsd_logs
from .gemini_compat import make_gemini_compatible

# --- Token threshold for large file warnings (conservative to enforce grep->read workflow) ---
LARGE_FILE_TOKEN_THRESHOLD = 20000

# --- Dynamic Field Descriptions (using imported constants) ---
MATCH_TEXT_DESCRIPTION = f"""The EXACT text to find and replace (LITERAL, not regex).

WORKFLOW: Read file → Copy exact text → Paste here.

Whitespace matters. Multi-line: use \\n between lines.
Example: "def foo():\\n    return 1"

SPECIAL: "" = new file, "OVERWRITE_FILE" = replace all, "APPEND_TO_FILE" = append to end.

If no match, error tells you why - just re-read and retry.
Max {MATCH_TEXT_MAX_LENGTH} chars."""

EDITS_DESCRIPTION = f"""Batch multiple DIFFERENT edits in one call. More efficient than multiple tool calls.

EXAMPLE:
edits=[
  {{"match_text": "old_name", "new_string": "new_name"}},
  {{"match_text": "x = 1", "new_string": "x = 2"}}
]

RULES:
- Each match_text must appear exactly ONCE in file
- Edits apply in order (first edit runs, then second on the result, etc.)
- Do NOT use for overlapping regions - split into separate calls instead
- Max {MATCH_TEXT_MAX_LENGTH} chars per match_text

WHEN TO USE: ANY time you make 2+ changes to the same file. Saves tokens and review cycles."""

EDIT_PAIR_MATCH_TEXT_DESCRIPTION = f"""Exact text to find. Must appear exactly once. Copy character-for-character including whitespace. Max {MATCH_TEXT_MAX_LENGTH} chars."""

LARGE_FILE_PASSTHROUGH_DESCRIPTION = f"Set True to read large JSON/YAML files (>{LARGE_FILE_TOKEN_THRESHOLD} tokens). Default False suggests using query_jq/query_yq instead."

BYPASS_MATCH_TEXT_LIMIT_DESCRIPTION = f"Set True to allow match_text over {MATCH_TEXT_MAX_LENGTH} chars. Try using 'edits' to split into smaller chunks first."

READ_MODE_HEAD_DESCRIPTION = "Number of lines to read from the beginning of the file. Cannot be mixed with start_line/end_line."
READ_MODE_TAIL_DESCRIPTION = "Number of lines to read from the end of the file. Cannot be mixed with start_line/end_line."
READ_MODE_START_LINE_DESCRIPTION = "The 1-based line number to start reading from. Use with end_line for a range, or with read_to_next_pattern for section-aware reading."
READ_MODE_END_LINE_DESCRIPTION = "The 1-based line number to stop reading at (inclusive). Cannot be used with read_to_next_pattern."
READ_MODE_PATTERN_DESCRIPTION = "A regex pattern for section-aware reading. Reads from start_line until a line matching this pattern is found (exclusive). Useful for reading entire functions/classes. REQUIRES start_line. Cannot be used with end_line."

# --- Pydantic Models for Tool Arguments ---

class FileReadSpec(BaseModel):
    """A single read specification. Reading mode fields are mutually exclusive within this object."""
    head: Optional[int] = Field(default=None, description=READ_MODE_HEAD_DESCRIPTION)
    tail: Optional[int] = Field(default=None, description=READ_MODE_TAIL_DESCRIPTION)
    start_line: Optional[int] = Field(default=None, description=READ_MODE_START_LINE_DESCRIPTION)
    end_line: Optional[int] = Field(default=None, description=READ_MODE_END_LINE_DESCRIPTION)
    read_to_next_pattern: Optional[str] = Field(default=None, description=READ_MODE_PATTERN_DESCRIPTION)


class FileReadRequest(BaseModel):
    """A request to read a file. Supports one legacy mode or multiple read specs via `reads`."""
    path: str = Field(description="The path to the file to read. Prefer relative paths.")
    reads: Optional[List[FileReadSpec]] = Field(
        default=None,
        description="Optional list of read specifications for this file. Use this for multi-location surgical reads in one request. Cannot be combined with top-level head/tail/start_line/end_line/read_to_next_pattern fields."
    )
    head: Optional[int] = Field(default=None, description=READ_MODE_HEAD_DESCRIPTION)
    tail: Optional[int] = Field(default=None, description=READ_MODE_TAIL_DESCRIPTION)
    start_line: Optional[int] = Field(default=None, description=READ_MODE_START_LINE_DESCRIPTION)
    end_line: Optional[int] = Field(default=None, description=READ_MODE_END_LINE_DESCRIPTION)
    read_to_next_pattern: Optional[str] = Field(default=None, description=READ_MODE_PATTERN_DESCRIPTION)


class EditPair(BaseModel):
    """A single edit operation for batch editing. Provide the exact text to find (match_text) and its replacement (new_string)."""
    match_text: str = Field(description=EDIT_PAIR_MATCH_TEXT_DESCRIPTION)
    new_string: str = Field(description="The replacement text that will replace match_text.")


# --- edit_files models (token-efficient) ---
EDIT_MATCH_DESCRIPTION = f"""Exact text to find (literal, not regex). Whitespace matters. Max {MATCH_TEXT_MAX_LENGTH} chars.
Special: ""=new file, "OVERWRITE_FILE"=replace all, "APPEND_TO_FILE"=append."""

class Edit(BaseModel):
    """Single find-and-replace."""
    match_text: str = Field(description=EDIT_MATCH_DESCRIPTION)
    new_string: str = Field(description="Replacement text.")

class FileEdit(BaseModel):
    """Edits for one file."""
    path: str = Field(description="File path. Prefer relative paths.")
    edits: List[Edit] = Field(description="Ordered find-and-replace operations.")


# --- Global Configuration ---
USER_ACCESSIBLE_DIRS: List[Path] = []
ALLOWED_DIRS: List[Path] = []
DANGEROUS_SKIP_PERMISSIONS_FLAG = "FS_MCP_FLAG"
mcp = FastMCP("filesystem", stateless_http=True)
IS_VSCODE_CLI_AVAILABLE = False
IS_RIPGREP_AVAILABLE = False
IS_JQ_AVAILABLE = False
IS_YQ_AVAILABLE = False
IS_RTK_AVAILABLE = False
_RTK_PATH: Optional[str] = None  # Absolute path to rtk binary, resolved at initialize()
_RTK_MANAGED = False  # True if RTK is in ~/.local/bin (managed by auto-update)
LOGIN_ENV: Optional[dict] = None  # Populated at initialize() time; passed to run_command subprocess


def _get_user_shell() -> str:
    """Resolve the current user's shell reliably, regardless of parent process env.

    Resolution order:
      1. $SHELL env var  — set when launched from a terminal
      2. /etc/passwd entry (pwd.getpwuid) — works even when launched from a GUI
         app or systemd service that strips the environment
      3. /bin/bash — last-resort default
    """
    if shell := os.environ.get("SHELL"):
        return shell
    try:
        import pwd
        entry = pwd.getpwuid(os.getuid())
        if entry.pw_shell:
            return entry.pw_shell
    except Exception:
        pass
    return "/bin/bash"


import platform as _platform

# Standard system PATH dirs that should always be present as a baseline.
# These are appended (low priority) — they're fallbacks if the parent process
# launched with a stripped environment (systemd, Electron apps, etc.).
# Platform-aware: macOS gets Homebrew paths, Linux gets linuxbrew + snap.
_SYSTEM_BIN_DIRS: list[str] = [
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/bin",
    "/sbin",
    *(
        [
            "/opt/homebrew/bin",       # Homebrew, Apple Silicon
            "/opt/homebrew/sbin",
            "/usr/local/opt",          # Homebrew cellar links, Intel
        ]
        if _platform.system() == "Darwin"
        else [
            "/home/linuxbrew/.linuxbrew/bin",   # Homebrew on Linux
            "/home/linuxbrew/.linuxbrew/sbin",
            "/snap/bin",
        ]
    ),
]

# Well-known binary directories for common version managers and language runtimes.
# Checked at initialize() time; any that exist are prepended to PATH (high priority
# — version manager installs should win over system-level ones).
# Shell-agnostic: no rc file parsing, no subprocess, works for bash/zsh/fish/nushell.
_VERSION_MANAGER_BIN_DIRS = [
    # nvm
    "{home}/.nvm/versions/node/*/bin",
    # fnm
    "{home}/.local/share/fnm/node-versions/*/installation/bin",
    # pyenv
    "{home}/.pyenv/shims",
    "{home}/.pyenv/bin",
    # rbenv
    "{home}/.rbenv/shims",
    "{home}/.rbenv/bin",
    # cargo (Rust)
    "{home}/.cargo/bin",
    # go
    "{home}/go/bin",
    "{home}/.go/bin",
    # bun
    "{home}/.bun/bin",
    # pnpm (standalone install)
    "{home}/.local/share/pnpm",
    # deno
    "{home}/.deno/bin",
    # volta
    "{home}/.volta/bin",
    # asdf shims
    "{home}/.asdf/shims",
    "{home}/.asdf/bin",
    # mise (formerly rtx)
    "{home}/.local/share/mise/shims",
    # homebrew (Linux)
    "/home/linuxbrew/.linuxbrew/bin",
    "/home/linuxbrew/.linuxbrew/sbin",
    # local user bin
    "{home}/.local/bin",
]


def _capture_login_env() -> dict:
    """Build a login-equivalent environment using a two-layer hybrid PATH strategy.

    Layer 1 — version manager dirs (PREPEND, high priority):
        Glob-probes _VERSION_MANAGER_BIN_DIRS (nvm, pyenv, cargo, volta, etc.).
        Prepended so user-managed installs win over system ones.

    Layer 2 — standard system dirs (APPEND, low priority):
        Ensures _SYSTEM_BIN_DIRS (/usr/local/bin, /opt/homebrew/bin on macOS, etc.)
        are always present as a baseline, even when the parent process (Electron,
        systemd) launched with a stripped PATH.

    Shell-agnostic: no subprocess, no rc file parsing, works for bash/zsh/fish/nushell.
    Platform-aware: macOS gets Homebrew paths, Linux gets linuxbrew + snap.
    """
    import glob
    home = str(Path.home())
    current_env = dict(os.environ)
    current_path_dirs = current_env.get("PATH", "").split(":")
    current_path_set = set(current_path_dirs)

    # --- Layer 1: prepend version manager dirs (highest priority) ---
    prepend_dirs: list[str] = []
    for pattern in _VERSION_MANAGER_BIN_DIRS:
        expanded = pattern.format(home=home)
        for match in sorted(glob.glob(expanded), reverse=True):  # newest version first
            if os.path.isdir(match) and match not in current_path_set:
                prepend_dirs.append(match)
                current_path_set.add(match)

    # --- Layer 2: append standard system dirs (lowest priority / baseline) ---
    append_dirs: list[str] = []
    for d in _SYSTEM_BIN_DIRS:
        if os.path.isdir(d) and d not in current_path_set:
            append_dirs.append(d)
            current_path_set.add(d)

    if prepend_dirs or append_dirs:
        new_path = ":".join(prepend_dirs + current_path_dirs + append_dirs)
        current_env["PATH"] = new_path
        print(
            f"[fs-mcp] PATH augmented: +{len(prepend_dirs)} version manager dirs (prepend), "
            f"+{len(append_dirs)} system dirs (append).",
            file=sys.stderr,
            flush=True,
        )

    return current_env


# --- RTK (Rust Token Killer) Integration ---
RTK_TIMEOUT_SECONDS = 30
RTK_REWRITE_TIMEOUT = 5  # Fast: just string matching, no I/O
RTK_UPDATE_INTERVAL_HOURS = 24  # Auto-update check interval
RUN_COMMAND_DEFAULT_TIMEOUT = 30
_rtk_last_update_check: Optional[float] = None  # epoch timestamp of last update check


def _resolve_rtk_path() -> Optional[str]:
    """
    Resolve the absolute path to the RTK binary.
    
    Resolution order:
    1. shutil.which('rtk') — respects current PATH
    2. ~/.local/bin/rtk — default install.sh location
    3. LOGIN_ENV PATH lookup — in case login shell has different PATH
    
    Returns:
        Absolute path to rtk binary, or None if not found.
    """
    # 1. Standard PATH lookup
    path = shutil.which('rtk')
    if path:
        return str(Path(path).resolve())
    
    # 2. Default install.sh location
    local_bin = Path.home() / '.local' / 'bin' / 'rtk'
    if local_bin.exists() and local_bin.is_file():
        return str(local_bin.resolve())
    
    # 3. Check LOGIN_ENV PATH (login shell may have different PATH)
    if LOGIN_ENV and 'PATH' in LOGIN_ENV:
        for dir_path in LOGIN_ENV['PATH'].split(':'):
            candidate = Path(dir_path) / 'rtk'
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
    
    return None


# Commands blocked from run_command for safety — matched against first token
BLOCKED_COMMANDS = {
    "rm", "rmdir", "rmrf",
    "mkfs", "dd", "format",
    "shutdown", "reboot", "halt", "poweroff", "init",
    "kill", "killall", "pkill",
    "systemctl",
    "shred", "wipefs",
    ":()",  # fork bomb
}

# Patterns blocked anywhere in the command string
BLOCKED_PATTERNS = [
    "> /dev/",
    ">/dev/",
    "chmod -R 777",
    "chmod 777",
    "mkfs.",
]

def _rtk_compress_content(content: str, file_path: str = "-") -> tuple[str, Optional[str]]:
    """
    Pipe content through RTK for token-efficient compression.
    
    Uses `rtk read <file> -l minimal` when a real file path is available (language
    detection via extension), falls back to `rtk read - -l minimal` for stdin.
    
    Filter level 'minimal' strips comments (language-aware), collapses blank lines,
    and normalizes whitespace — 12-60% token savings on source code.
    
    Args:
        content: The file content to compress
        file_path: Original file path for language detection, or "-" for stdin
    
    Returns:
        Tuple of (compressed_content, warning_or_none)
        If RTK fails, returns original content with a warning.
    """
    if not IS_RTK_AVAILABLE:
        return content, None  # Silent skip — no subprocess overhead
    
    try:
        # Prefer file path for language-aware compression (RTK detects language from extension)
        # Fall back to stdin for content that doesn't map to a file (e.g., run_command output)
        if file_path != "-" and Path(file_path).exists():
            result = subprocess.run(
                [_RTK_PATH, "read", file_path, "-l", "minimal"],
                capture_output=True,
                text=True,
                timeout=RTK_TIMEOUT_SECONDS
            )
        else:
            result = subprocess.run(
                [_RTK_PATH, "read", "-", "-l", "minimal"],
                input=content,
                capture_output=True,
                text=True,
                timeout=RTK_TIMEOUT_SECONDS
            )
        
        if result.returncode == 0:
            return result.stdout, None
        else:
            # RTK failed, return original with warning
            warning = f"[RTK compression failed (exit {result.returncode}), returning verbatim]"
            return content, warning
            
    except subprocess.TimeoutExpired:
        warning = f"[RTK timeout after {RTK_TIMEOUT_SECONDS}s, returning verbatim]"
        return content, warning
    except FileNotFoundError:
        warning = "[RTK binary not found, returning verbatim]"
        return content, warning
    except Exception as e:
        warning = f"[RTK error: {e}, returning verbatim]"
        return content, warning



def _rtk_rewrite_command(command: str) -> Optional[str]:
    """
    Ask RTK to rewrite a shell command to its token-efficient equivalent.
    
    Uses `rtk rewrite` which maps commands to specialized RTK subcommands:
    - "git status" -> "rtk git status" (70% savings)
    - "cargo test" -> "rtk cargo test" (65% savings)  
    - "pip list" -> "rtk pip list" (60% savings)
    - "echo hello" -> None (no RTK equivalent)
    
    Returns:
        The rewritten command string, or None if RTK has no equivalent.
    """
    if not IS_RTK_AVAILABLE:
        return None
    
    try:
        result = subprocess.run(
            [_RTK_PATH, "rewrite", command],
            capture_output=True,
            text=True,
            timeout=RTK_REWRITE_TIMEOUT
        )
        
        if result.returncode == 0:
            rewritten = result.stdout.strip()
            return rewritten if rewritten else None
        else:
            # Exit 1 = no RTK equivalent, Exit 2 = denied, Exit 3 = ask
            return None
            
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None


def _rtk_auto_update() -> Optional[str]:
    """
    Check for RTK updates and install if a newer version is available.
    
    Runs at most once per RTK_UPDATE_INTERVAL_HOURS. Only auto-updates
    managed installs (~/.local/bin). User-installed RTK (e.g., /usr/local/bin,
    brew, cargo) is left untouched.
    
    After successful install, re-resolves _RTK_PATH and IS_RTK_AVAILABLE
    so the new binary is used immediately.
    
    Returns:
        Status message or None if no update was needed/attempted.
    """
    global _rtk_last_update_check, _RTK_PATH, IS_RTK_AVAILABLE, _RTK_MANAGED
    
    now = time.time()
    if _rtk_last_update_check and (now - _rtk_last_update_check) < (RTK_UPDATE_INTERVAL_HOURS * 3600):
        return None  # Too soon to check again
    
    _rtk_last_update_check = now
    
    # Only auto-update if RTK is managed by us (installed via install.sh to ~/.local/bin)
    # or if RTK is not installed at all (first-time install attempt)
    if _RTK_PATH and not _RTK_MANAGED:
        return None  # User-installed RTK — don't touch
    
    managed_dir = str(Path.home() / '.local' / 'bin')
    
    try:
        # Get current version (if RTK exists)
        current_version = "not installed"
        if _RTK_PATH:
            current = subprocess.run(
                [_RTK_PATH, "--version"],
                capture_output=True, text=True, timeout=5
            )
            current_version = current.stdout.strip() if current.returncode == 0 else "unknown"
        
        # Run install script, targeting the managed directory
        result = subprocess.run(
            ["bash", "-c", f"RTK_INSTALL_DIR={managed_dir} curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Re-resolve path (may have just been installed for the first time)
            new_path = _resolve_rtk_path()
            if new_path:
                _RTK_PATH = new_path
                IS_RTK_AVAILABLE = True
                _RTK_MANAGED = str(Path(new_path).resolve()).startswith(managed_dir)
                
                # Check new version
                new = subprocess.run(
                    [_RTK_PATH, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                new_version = new.stdout.strip() if new.returncode == 0 else "unknown"
                
                if current_version == "not installed":
                    msg = f"RTK installed: {new_version} (at {_RTK_PATH})"
                    print(f"[fs-mcp] {msg}", file=sys.stderr, flush=True)
                    return msg
                elif new_version != current_version:
                    msg = f"RTK updated: {current_version} -> {new_version}"
                    print(f"[fs-mcp] {msg}", file=sys.stderr, flush=True)
                    return msg
                return None  # Already latest
            else:
                # Install script ran but binary not found — likely unsupported arch
                return None
        else:
            # Install failed — likely unsupported arch (ARM/Pi), not an error
            stderr_hint = result.stderr.strip()[:100] if result.stderr else ""
            return f"RTK install skipped ({stderr_hint or 'exit ' + str(result.returncode)})"
            
    except Exception as e:
        return f"RTK update check error: {e}"


def _rtk_grep(pattern: str, search_path: str) -> tuple[str, Optional[str]]:
    """
    Run RTK grep for token-efficient grouped search results.
    
    Args:
        pattern: The regex pattern to search for
        search_path: The directory or file to search in
    
    Returns:
        Tuple of (rtk_output, warning_or_none)
        If RTK fails, returns None with an error message.
    """
    try:
        result = subprocess.run(
            [_RTK_PATH, "grep", pattern, search_path],
            capture_output=True,
            text=True,
            timeout=RTK_TIMEOUT_SECONDS
        )
        
        if result.returncode == 0 or result.returncode == 1:  # 1 = no matches (not an error)
            return result.stdout, None
        else:
            return None, f"RTK grep failed (exit {result.returncode}): {result.stderr}"
            
    except subprocess.TimeoutExpired:
        return None, f"RTK grep timeout after {RTK_TIMEOUT_SECONDS}s"
    except FileNotFoundError:
        return None, "RTK binary not found"
    except Exception as e:
        return None, f"RTK grep error: {e}"


def _rtk_tree(path: str, max_depth: int, exclude_dirs: Optional[List[str]] = None) -> tuple[Optional[str], Optional[str]]:
    """Run RTK tree for compact filesystem exploration."""
    try:
        command = [_RTK_PATH, "tree"]

        if max_depth is not None:
            command.extend(["-L", str(max_depth)])

        if exclude_dirs:
            command.extend(["-I", "|".join(exclude_dirs)])

        command.append(path)

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=RTK_TIMEOUT_SECONDS,
        )

        if result.returncode == 0:
            output = result.stdout
            if not output.endswith("\n"):
                output += "\n"
            return output, None

        stderr = result.stderr.strip()
        if stderr:
            return None, f"RTK tree failed (exit {result.returncode}): {stderr}"
        return None, f"RTK tree failed (exit {result.returncode})"

    except subprocess.TimeoutExpired:
        return None, f"RTK tree timeout after {RTK_TIMEOUT_SECONDS}s"
    except FileNotFoundError:
        return None, "RTK binary not found"
    except Exception as e:
        return None, f"RTK tree error: {e}"


# --- GSD Reader Auto-Dump ---
# Opt-in via GSD_READER_REMOTE env var. Debounced to coalesce rapid-fire commits.

GSD_ARTIFACT_NAMES = {"WORK.md", "PROJECT.md", "ARCHITECTURE.md"}
GSD_DUMP_DEBOUNCE_SECONDS = 10
_gsd_dump_lock = threading.Lock()
_gsd_dump_pending: Dict[str, threading.Timer] = {}


def _is_gsd_artifact(path_obj: Path) -> bool:
    """Check if a file is a GSD-Lite artifact inside a gsd-lite/ directory."""
    return path_obj.name in GSD_ARTIFACT_NAMES and path_obj.parent.name == "gsd-lite"


def _trigger_gsd_dump(path_obj: Path):
    """
    Debounced fire-and-forget: schedules npx gsd-reader dump after a quiet period.
    Multiple rapid commits to the same gsd-lite/ dir coalesce into one dump.

    Env vars (set in .zshrc):
      GSD_READER_REMOTE  - required to enable
      GSD_READER_USER    - optional basic auth username
      GSD_READER_PASS    - inherited by subprocess, not passed as CLI arg
    """
    remote = os.environ.get("GSD_READER_REMOTE")
    if not remote:
        return

    worklog_path = path_obj.parent / "WORK.md"
    dump_key = str(worklog_path)

    def _do_dump():
        try:
            with _gsd_dump_lock:
                _gsd_dump_pending.pop(dump_key, None)

            if not worklog_path.exists():
                print(f"[gsd-dump] Skip: {worklog_path} not found", file=sys.stderr, flush=True)
                return

            # Read markdown artifacts
            gsd_dir = worklog_path.parent
            work_content = worklog_path.read_text(encoding="utf-8")

            project_path = gsd_dir / "PROJECT.md"
            project_content = project_path.read_text(encoding="utf-8") if project_path.exists() else ""

            arch_path = gsd_dir / "ARCHITECTURE.md"
            arch_content = arch_path.read_text(encoding="utf-8") if arch_path.exists() else ""

            # Derive project name from path (last 2 segments, same as CLI)
            parts = gsd_dir.parts
            project_name = "/".join(parts[-2:])

            # Build JSON payload (markdown only — server does the rendering)
            payload = json.dumps({
                "work": work_content,
                "project": project_content,
                "architecture": arch_content,
                "base_path": str(gsd_dir),
            }).encode("utf-8")

            # Build request with optional basic auth
            url = f"{remote}/upload-markdown/{project_name}"
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; gsd-lite-autodump/1.0)",
            }

            user = os.environ.get("GSD_READER_USER", "")
            password = os.environ.get("GSD_READER_PASS", "")
            if user:
                auth = base64.b64encode(f"{user}:{password}".encode()).decode()
                headers["Authorization"] = f"Basic {auth}"

            req = urllib.request.Request(url, data=payload, headers=headers)

            size_kb = len(payload) / 1024
            print(f"[gsd-dump] Uploading {size_kb:.0f}KB -> {url}", file=sys.stderr, flush=True)

            resp = urllib.request.urlopen(req, timeout=300)
            body = resp.read().decode("utf-8", errors="replace")
            print(f"[gsd-dump] Done ({resp.getcode()}): {body.strip()}", file=sys.stderr, flush=True)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[gsd-dump] HTTP {e.code}: {body.strip()}", file=sys.stderr, flush=True)
        except urllib.error.URLError as e:
            print(f"[gsd-dump] Network error: {e.reason}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[gsd-dump] Unexpected error: {e}", file=sys.stderr, flush=True)

    with _gsd_dump_lock:
        existing = _gsd_dump_pending.get(dump_key)
        if existing:
            existing.cancel()

        timer = threading.Timer(GSD_DUMP_DEBOUNCE_SECONDS, _do_dump)
        timer.daemon = True
        _gsd_dump_pending[dump_key] = timer
        timer.start()
        print(f"[gsd-dump] Scheduled in {GSD_DUMP_DEBOUNCE_SECONDS}s: {dump_key}", file=sys.stderr, flush=True)


# --- Tool Tier Configuration ---
# Core tier: GSD-Lite optimized toolset (safe edit, grep-first, structured queries)
# These are the tools exposed by default. Pass --all to expose everything.
CORE_TOOLS = {
    "read_files",
    "create_directory",
    "directory_tree",
    "edit_files",
    "grep_content",
    "query_jq",
    "query_yq",
    "query_duckdb",
    "run_command",
    "check_dependencies",
    "list_gsd_lite_dirs",
}

# Tools excluded from core tier (available with --all)
# - write_file: use edit_files for safe editing
# - propose_and_review: human-in-the-loop editing (use edit_files for direct writes)
# - commit_review: only needed for propose_and_review review flow
# - list_directory: use directory_tree or list_directory_with_sizes
# - move_file: rarely needed, potentially destructive
# - append_text: use edit_files for safe editing
# - grounding_search: external dependency, not core filesystem operation
EXCLUDED_FROM_CORE = {
    "write_file",
    "propose_and_review",
    "commit_review",
    "list_directory",
    "move_file",
    "append_text",
    "grounding_search",
    "analyze_gsd_work_log",
    "search_files",
    "read_media_file",
    "list_allowed_directories",
    "list_directory_with_sizes",
    "get_file_info",
}


@mcp.tool()
async def check_dependencies(
    fix: Annotated[
        bool,
        Field(default=False, description="If true, attempt to update managed dependencies (e.g., RTK auto-update). "
              "Only updates deps installed via their standard installer to ~/.local/bin.")
    ] = False,
    verbose: Annotated[
        bool,
        Field(default=False, description="If true, show detailed info: all binary locations, PATH entries, "
              "architecture, duplicate detection.")
    ] = False,
) -> str:
    """Check health and version status of all fs-mcp dependencies.

    Reports: installed/missing, version, path, duplicates, managed vs user-installed.
    Use `fix=true` to auto-update managed dependencies.

    **Example output (default):**
    ```
    ✅ ripgrep (rg) 14.1.1 — /usr/bin/rg
    ✅ jq 1.7.1 — /usr/bin/jq
    ✅ yq 4.44.1 — /usr/local/bin/yq
    ✅ rtk 0.31.0 — ~/.local/bin/rtk [managed]
    ⚠️  rtk: duplicate at /usr/local/bin/rtk (same version)
    ```

    **With fix=true:**
    ```
    ✅ rtk updated: 0.29.0 → 0.31.0
    ```
    """
    global IS_RTK_AVAILABLE, _RTK_PATH, _RTK_MANAGED

    import platform
    lines = []
    warnings = []
    arch = platform.machine()

    # --- Helper: get version from a binary ---
    def _get_version(binary_path: str, version_flag: str = "--version") -> str:
        try:
            result = subprocess.run(
                [binary_path, version_flag],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
            return "unknown"
        except Exception:
            return "error"

    # --- Helper: find all copies of a binary ---
    def _find_all(name: str) -> list:
        """Find all locations of a binary in PATH."""
        locations = []
        seen = set()
        # Check PATH
        path_dirs = os.environ.get('PATH', '').split(':')
        if LOGIN_ENV and 'PATH' in LOGIN_ENV:
            path_dirs += LOGIN_ENV['PATH'].split(':')
        for d in path_dirs:
            candidate = Path(d) / name
            try:
                resolved = str(candidate.resolve())
                if candidate.exists() and candidate.is_file() and resolved not in seen:
                    seen.add(resolved)
                    locations.append(resolved)
            except Exception:
                pass
        # Also check common manual-install locations
        for extra in [
            Path.home() / '.local' / 'bin' / name,
            Path.home() / '.cargo' / 'bin' / name,
            Path('/usr/local/bin') / name,
            Path('/usr/bin') / name,
        ]:
            try:
                resolved = str(extra.resolve())
                if extra.exists() and extra.is_file() and resolved not in seen:
                    seen.add(resolved)
                    locations.append(resolved)
            except Exception:
                pass
        return locations

    # --- Helper: format path for display ---
    def _display_path(p: str) -> str:
        home = str(Path.home())
        if p.startswith(home):
            return "~" + p[len(home):]
        return p

    # --- Check each dependency ---

    # 1. ripgrep
    rg_path = shutil.which('rg')
    if rg_path:
        ver = _get_version(rg_path)
        lines.append(f"✅ ripgrep (rg) {ver} — {_display_path(rg_path)}")
        if verbose:
            for loc in _find_all('rg'):
                if loc != str(Path(rg_path).resolve()):
                    warnings.append(f"   ⚠️  rg: also found at {_display_path(loc)}")
    else:
        lines.append("❌ ripgrep (rg) — NOT FOUND (grep_content will fail)")

    # 2. jq
    jq_path = shutil.which('jq')
    if jq_path:
        ver = _get_version(jq_path)
        lines.append(f"✅ jq {ver} — {_display_path(jq_path)}")
    else:
        lines.append("❌ jq — NOT FOUND (query_jq will fail)")

    # 3. yq
    yq_path = shutil.which('yq')
    if yq_path:
        ver = _get_version(yq_path)
        lines.append(f"✅ yq {ver} — {_display_path(yq_path)}")
    else:
        lines.append("❌ yq — NOT FOUND (query_yq will fail)")

    # 4. RTK (the interesting one)
    if _RTK_PATH:
        ver = _get_version(_RTK_PATH)
        managed_tag = " [managed]" if _RTK_MANAGED else " [user-installed]"
        lines.append(f"✅ rtk {ver} — {_display_path(_RTK_PATH)}{managed_tag}")

        # Check for duplicates
        all_rtk = _find_all('rtk')
        primary_resolved = str(Path(_RTK_PATH).resolve())
        dupes = [loc for loc in all_rtk if loc != primary_resolved]
        if dupes:
            for dupe in dupes:
                dupe_ver = _get_version(dupe)
                same = "(same version)" if dupe_ver == ver else f"(DIFFERENT: {dupe_ver})"
                warnings.append(f"⚠️  rtk: duplicate at {_display_path(dupe)} {same}")
                if dupe_ver != ver:
                    warnings.append(f"   💡 Consider removing the older copy to avoid confusion")
    else:
        lines.append(f"⚠️  rtk — NOT FOUND (token-efficient mode disabled, arch: {arch})")
        if fix:
            lines.append("   🔧 Attempting RTK install...")

    # 5. Optional: tree (used by rtk tree)
    if verbose:
        tree_path = shutil.which('tree')
        if tree_path:
            ver = _get_version(tree_path)
            lines.append(f"✅ tree {ver} — {_display_path(tree_path)}")
        else:
            lines.append(f"⚠️  tree — not found (directory_tree compact mode may fall back to built-in)")

    # --- Fix mode ---
    if fix:
        if _RTK_PATH and _RTK_MANAGED:
            # Update managed RTK
            update_result = _rtk_auto_update()
            if update_result and ("updated" in update_result.lower() or "installed" in update_result.lower()):
                lines.append(f"🔧 {update_result}")
            elif update_result:
                lines.append(f"ℹ️  {update_result}")
            else:
                lines.append("ℹ️  RTK already at latest version")
        elif _RTK_PATH and not _RTK_MANAGED:
            lines.append(f"ℹ️  RTK is user-installed at {_display_path(_RTK_PATH)} — skipping auto-update")
            lines.append(f"   💡 To enable auto-update, install via: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh")
        elif not _RTK_PATH:
            # Try to install RTK for the first time
            update_result = _rtk_auto_update()
            if update_result and "installed" in update_result.lower():
                lines.append(f"🔧 {update_result}")
            elif update_result:
                lines.append(f"ℹ️  {update_result}")
            else:
                lines.append(f"ℹ️  RTK install failed — may not be available for {arch}")

    # --- Verbose: system info ---
    if verbose:
        lines.append("")
        lines.append(f"[system] arch: {arch}, platform: {platform.system()}")
        lines.append(f"[system] IS_RTK_AVAILABLE: {IS_RTK_AVAILABLE}")
        lines.append(f"[system] _RTK_PATH: {_RTK_PATH}")
        lines.append(f"[system] _RTK_MANAGED: {_RTK_MANAGED}")
        if LOGIN_ENV and 'PATH' in LOGIN_ENV:
            path_entries = LOGIN_ENV['PATH'].split(':')[:10]
            lines.append(f"[system] LOGIN_ENV PATH (first 10):")
            for pe in path_entries:
                lines.append(f"   {pe}")

    # Combine
    result = "\n".join(lines)
    if warnings:
        result += "\n\n" + "\n".join(warnings)

    return result


def initialize(directories: List[str], use_all_tools: bool = False):
    """Initialize the allowed directories, check for dependencies, and configure tool tier.
    
    Args:
        directories: List of allowed directory paths
        use_all_tools: If False (default), expose only CORE_TOOLS. If True, expose all tools.
    """
    global ALLOWED_DIRS, USER_ACCESSIBLE_DIRS, IS_VSCODE_CLI_AVAILABLE, IS_RIPGREP_AVAILABLE, IS_JQ_AVAILABLE, IS_YQ_AVAILABLE, IS_RTK_AVAILABLE, _RTK_PATH, _RTK_MANAGED, LOGIN_ENV
    ALLOWED_DIRS.clear()
    USER_ACCESSIBLE_DIRS.clear()

    # Capture the user's login shell environment once so run_command inherits
    # nvm, pyenv, pnpm, cargo, etc. (fixes bare-PATH bug when server starts via systemd/supervisor)
    LOGIN_ENV = _capture_login_env()

    # Check required dependencies (exits with instructions if missing)
    rtk_ok = check_required_dependencies()
    
    IS_VSCODE_CLI_AVAILABLE = shutil.which('code') is not None
    IS_RIPGREP_AVAILABLE = True  # Guaranteed by check_required_dependencies
    IS_JQ_AVAILABLE = True       # Guaranteed by check_required_dependencies
    IS_YQ_AVAILABLE = True       # Guaranteed by check_required_dependencies
    
    # RTK: optional, resolve absolute path
    _rtk_path = _resolve_rtk_path()
    if _rtk_path:
        IS_RTK_AVAILABLE = True
        _RTK_PATH = _rtk_path
        managed_dir = str(Path.home() / '.local' / 'bin')
        _RTK_MANAGED = str(Path(_rtk_path).resolve()).startswith(managed_dir)
    else:
        IS_RTK_AVAILABLE = False
        _RTK_PATH = None
        _RTK_MANAGED = False
    
    # Auto-update RTK in background (non-blocking)
    # Will attempt install if missing, or update if managed
    threading.Thread(target=_rtk_auto_update, daemon=True, name="rtk-auto-update").start()

    raw_dirs = directories or [str(Path.cwd())]
    
    # Process user-specified directories
    for d in raw_dirs:
        try:
            p = Path(d).expanduser().resolve()
            if not p.exists() or not p.is_dir():
                print(f"Warning: Skipping invalid directory: {p}")
                continue
            USER_ACCESSIBLE_DIRS.append(p)
        except Exception as e:
            print(f"Warning: Could not resolve {d}: {e}")

    # The full list of allowed directories includes the user-accessible ones
    # and the system's temporary directory for internal review sessions.
    ALLOWED_DIRS.extend(USER_ACCESSIBLE_DIRS)
    ALLOWED_DIRS.append(Path(tempfile.gettempdir()).resolve())

    if not USER_ACCESSIBLE_DIRS:
        print("Warning: No valid user directories. Defaulting to CWD.")
        cwd = Path.cwd()
        USER_ACCESSIBLE_DIRS.append(cwd)
        if cwd not in ALLOWED_DIRS:
            ALLOWED_DIRS.append(cwd)
    
    # Filter tools based on tier (before applying schema transforms)
    _apply_tool_tier_filter(use_all_tools)
    
    # Apply Gemini-compatible schema transforms to all registered tools
    # This ensures schemas work with Gemini, Claude, and GPT without modification
    # Reference: LOG-001 (root cause), LOG-003 (implementation plan)
    _apply_gemini_schema_transforms()
            
    return USER_ACCESSIBLE_DIRS


def _apply_tool_tier_filter(use_all_tools: bool):
    """
    Filter registered tools based on the selected tier.
    
    By default (use_all_tools=False), only CORE_TOOLS are exposed.
    Pass --all to expose everything.
    """
    if use_all_tools:
        print("Tool tier: ALL (exposing all tools)")
        return  # Keep all tools
    
    tool_manager = mcp._tool_manager
    tools_to_remove = []
    
    for tool_name in tool_manager._tools:
        if tool_name not in CORE_TOOLS:
            tools_to_remove.append(tool_name)
    
    for tool_name in tools_to_remove:
        del tool_manager._tools[tool_name]
    
    if tools_to_remove:
        print(f"Tool tier: CORE (excluded: {', '.join(sorted(tools_to_remove))})")


def _apply_gemini_schema_transforms():
    """
    Transform all tool schemas to be Gemini-compatible.
    
    Called at the end of initialize() to post-process all registered tools.
    This is the "lowest common denominator" approach — if a schema works
    with Gemini, it works with Claude and GPT too.
    
    Why here? Tools are registered via decorators at module load time.
    By the time initialize() runs, all tools exist in the registry.
    """
    tool_manager = mcp._tool_manager
    for tool_name, tool in tool_manager._tools.items():
        if tool.parameters:
            tool.parameters = make_gemini_compatible(tool.parameters)

def _dangerous_skip_permissions_enabled() -> bool:
    """
    Return True when the workspace root contains the FS_MCP_FLAG sentinel file.

    Checked on every validation call so creating or deleting the flag takes
    effect immediately without restarting fs-mcp.
    """
    if not USER_ACCESSIBLE_DIRS:
        return False

    flag_path = USER_ACCESSIBLE_DIRS[0] / DANGEROUS_SKIP_PERMISSIONS_FLAG
    return flag_path.is_file()


def validate_path(requested_path: str) -> Path:
    """
    Security barrier: Ensures path is within ALLOWED_DIRS.
    Handles both absolute and relative paths. Relative paths are resolved 
    against the first directory in ALLOWED_DIRS.
    """
    
    # an 'empty' path should always resolve to the primary allowed directory
    if not requested_path or requested_path == ".":
        return ALLOWED_DIRS[0]

    
    p = Path(requested_path).expanduser()
    
    # If the path is relative, resolve it against the primary allowed directory.
    if not p.is_absolute():
        # Ensure the base directory for relative paths is always the first one.
        base_dir = ALLOWED_DIRS[0]
        p = base_dir / p

    # --- Security Check: Resolve the final path and verify it's within bounds ---
    try:
        # .resolve() is crucial for security as it canonicalizes the path,
        # removing any ".." components and resolving symlinks.
        path_obj = p.resolve()
    except Exception:
        # Fallback for paths that might not exist yet but are being created.
        path_obj = p.absolute()

    if _dangerous_skip_permissions_enabled():
        return path_obj

    is_allowed = any(
        str(path_obj).startswith(str(allowed)) 
        for allowed in ALLOWED_DIRS
    )

    # If the path is in the temp directory, apply extra security checks.
    temp_dir = Path(tempfile.gettempdir()).resolve()
    if is_allowed and str(path_obj).startswith(str(temp_dir)):
        # Allow access to the temp directory itself, but apply stricter checks for its contents.
        if path_obj != temp_dir:
            path_str = str(path_obj)
            is_review_dir = "mcp_review_" in path_str
            is_pytest_dir = "pytest-" in path_str

            if not (is_review_dir or is_pytest_dir):
                is_allowed = False
            # For review directories, apply stricter checks.
            elif is_review_dir and not (path_obj.name.startswith("current_") or path_obj.name.startswith("future_")):
                is_allowed = False
            
    if not is_allowed:
        raise ValueError(f"Access denied: {requested_path} is outside allowed directories: {ALLOWED_DIRS}")
        
    return path_obj

def format_size(size_bytes: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

# --- Tools ---

@mcp.tool()
def list_allowed_directories() -> str:
    """List the directories this server is allowed to access."""
    return "\n".join(str(d) for d in USER_ACCESSIBLE_DIRS)

@mcp.tool()
def read_files(
    files: Annotated[
        List[FileReadRequest],
        Field(description="A list of file read requests. WORKFLOW: Use grep_content FIRST to find line numbers and section boundaries, then use read_files for targeted reading of only the relevant sections. This preserves context. Each entry accepts either one legacy mode (path-only, head/tail, line range, section-aware) or a `reads` array with multiple mode specs for the same file.")
    ],
    large_file_passthrough: Annotated[
        bool,
        Field(default=False, description=LARGE_FILE_PASSTHROUGH_DESCRIPTION)
    ] = False,
    compact: Annotated[
        bool,
        Field(default=True, description="Token-efficient mode via RTK compression. DEFAULT=True returns compressed content (comments stripped, whitespace normalized, 60-90%% token savings). Set compact=False for VERBATIM content when preparing propose_and_review edits (exact match_text required).")
    ] = True
) -> str:
    """
    Read the contents of multiple files simultaneously.
    Returns path and content separated by dashes.
    Prefer relative paths.

    **DEFAULT BEHAVIOR (compact=True):**
    Returns TOKEN-OPTIMIZED content via RTK:
    - Comments stripped
    - Whitespace normalized  
    - Structure preserved, verbosity reduced
    - 60-90%% token savings

    **FOR EDITING (compact=False):**
    When preparing `propose_and_review`, set compact=False to get 
    EXACT VERBATIM content required for match_text.

    **Reading Modes:**
    1.  **Full File:** Provide just the `path`.
    2.  **Head/Tail:** Use `head` or `tail` to read the beginning or end of the file.
    3.  **Line Range:** Use `start_line` and `end_line` to read a specific slice.
    4.  **Section-Aware:** Use `start_line` and `read_to_next_pattern` to read until the next pattern match.
    5.  **Multi-Read Per File:** Use `reads` to request multiple slices from the same file in one request.

    **Multi-Read Example:**
    ```
    read_files([{
        "path": "src/fs_mcp/server.py",
        "reads": [
            {"head": 40},
            {"start_line": 331, "end_line": 380}
        ]
    }])
    ```

    **Section-Aware Reading Example:**
    ```
    read_files([{
        "path": "src/fs_mcp/server.py",
        "start_line": 90,
        "read_to_next_pattern": "^def "
    }])
    ```
    This reads from line 90 until the *next* line that starts with "def ", effectively capturing the whole function. The pattern search starts on the line *after* `start_line`. If the pattern is not found, it reads to the end of the file.

    **Parameter mutual exclusivity:**
    - Within one read spec, `head` and `tail` are mutually exclusive.
    - Within one read spec, `head` or `tail` cannot be mixed with `start_line` or `end_line`.
    - `end_line` cannot be used with `read_to_next_pattern`.
    - `read_to_next_pattern` requires `start_line`.
    - `reads` cannot be combined with top-level `head`/`tail`/`start_line`/`end_line`/`read_to_next_pattern`.

    **Workflow Synergy with `grep_content`:**
    This tool is the second step in the efficient "grep -> read" workflow. After using `grep_content`
    to find relevant files and line numbers, use this tool to perform a targeted read of only
    those specific sections.
    """
    def _uses_top_level_mode_fields(request: FileReadRequest) -> bool:
        return any(
            value is not None
            for value in (
                request.head,
                request.tail,
                request.start_line,
                request.end_line,
                request.read_to_next_pattern,
            )
        )

    def _normalize_read_specs(request: FileReadRequest) -> Tuple[List[FileReadSpec], Optional[str]]:
        if request.reads is not None:
            if _uses_top_level_mode_fields(request):
                return [], (
                    "Error: Invalid request shape.\n\n"
                    "You provided both `reads` and top-level read mode fields.\n"
                    "Problem: `reads` cannot be combined with top-level `head`/`tail`/`start_line`/`end_line`/`read_to_next_pattern`.\n"
                    "Fix: Move all read mode fields into `reads`, or remove `reads` and use legacy single-mode fields."
                )

            if len(request.reads) == 0:
                return [], (
                    "Error: Invalid request shape.\n\n"
                    "You provided: `reads=[]`.\n"
                    "Problem: `reads` must contain at least one read specification.\n"
                    "Fix: Add one or more read specs, e.g. `reads=[{\"head\": 50}]`."
                )

            return request.reads, None

        return [
            FileReadSpec(
                head=request.head,
                tail=request.tail,
                start_line=request.start_line,
                end_line=request.end_line,
                read_to_next_pattern=request.read_to_next_pattern,
            )
        ], None

    def _describe_read_spec(read_spec: FileReadSpec) -> str:
        if read_spec.head is not None:
            return f"head={read_spec.head}"
        if read_spec.tail is not None:
            return f"tail={read_spec.tail}"
        if read_spec.read_to_next_pattern is not None:
            start_line = read_spec.start_line if read_spec.start_line is not None else 1
            return f"start_line={start_line}, read_to_next_pattern={read_spec.read_to_next_pattern!r}"
        if read_spec.start_line is not None or read_spec.end_line is not None:
            start_line = read_spec.start_line if read_spec.start_line is not None else 1
            end_line = read_spec.end_line if read_spec.end_line is not None else "EOF"
            return f"range={start_line}:{end_line}"
        return "full_file"

    def _validate_read_spec(read_spec: FileReadSpec) -> Optional[str]:
        if read_spec.head is not None and read_spec.tail is not None:
            return (
                "Error: Mutually exclusive parameters provided.\n\n"
                f"You provided: head={read_spec.head}, tail={read_spec.tail}\n"
                "Problem: `head` and `tail` cannot be used together in the same read spec.\n"
                "Fix: Choose either `head` or `tail`."
            )

        if (read_spec.head is not None or read_spec.tail is not None) and (
            read_spec.start_line is not None or read_spec.end_line is not None
        ):
            return (
                "Error: Mutually exclusive parameters provided.\n\n"
                f"You provided: head={read_spec.head}, tail={read_spec.tail}, "
                f"start_line={read_spec.start_line}, end_line={read_spec.end_line}\n"
                "Problem: `head`/`tail` cannot be mixed with `start_line`/`end_line`.\n"
                "Fix: Use one mode per read spec."
            )

        if read_spec.end_line is not None and read_spec.read_to_next_pattern is not None:
            return (
                "Error: Mutually exclusive parameters provided.\n\n"
                f"You provided: end_line={read_spec.end_line}, read_to_next_pattern={read_spec.read_to_next_pattern!r}\n"
                "Problem: `end_line` and `read_to_next_pattern` cannot be used together.\n"
                "Fix: Choose one method for defining the read boundary."
            )

        if read_spec.read_to_next_pattern and read_spec.start_line is None:
            return (
                "Error: Missing required parameter.\n\n"
                f"You provided: read_to_next_pattern={read_spec.read_to_next_pattern!r} without `start_line`.\n"
                "Problem: `read_to_next_pattern` requires a `start_line` to know where to begin scanning.\n"
                "Fix: Provide a `start_line`."
            )

        return None

    def _read_content_for_spec(path_obj: Path, file_path: str, read_spec: FileReadSpec) -> str:
        with open(path_obj, 'r', encoding='utf-8') as f:
            if read_spec.read_to_next_pattern:
                start_line = read_spec.start_line
                if start_line is None:
                    return "Error: start_line is required for read_to_next_pattern."

                pattern = read_spec.read_to_next_pattern
                lines_to_read = []
                pattern_found = False

                # islice uses 0-based indexing, so subtract 1
                line_iterator = itertools.islice(f, start_line - 1, None)

                try:
                    first_line = next(line_iterator)
                    lines_to_read.append(first_line)
                except StopIteration:
                    # To get total lines, we need to read the file again unfortunately
                    with open(path_obj, 'r', encoding='utf-8') as count_f:
                        total_lines = sum(1 for _ in count_f)

                    return (
                        "Error: Invalid start_line.\n\n"
                        f"You provided: start_line={start_line}\n"
                        f"Problem: The file '{file_path}' only has {total_lines} lines.\n"
                        f"Fix: Choose a start_line between 1 and {total_lines}.\n"
                        "Tip: Use grep_content to find valid line numbers first."
                    )

                # Scan subsequent lines for the pattern
                for line in line_iterator:
                    if re.search(pattern, line):
                        pattern_found = True
                        break
                    lines_to_read.append(line)

                content = "".join(lines_to_read)
                if not pattern_found:
                    note = f"Note: Pattern '{pattern}' not found after line {start_line}. Read to end of file."
                    content = f"{content.rstrip()}\n{note}\n"
                return content

            if read_spec.start_line is not None or read_spec.end_line is not None:
                lines = f.readlines()
                start = (read_spec.start_line or 1) - 1
                end = read_spec.end_line or len(lines)
                return "".join(lines[start:end])

            if read_spec.head is not None:
                return "".join(itertools.islice(f, read_spec.head))

            if read_spec.tail is not None:
                return "".join(f.readlines()[-read_spec.tail:])

            return f.read()

    results = []
    for file_request_data in files:
        if isinstance(file_request_data, dict):
            file_request = FileReadRequest(**file_request_data)
        else:
            file_request = file_request_data

        try:
            path_obj = validate_path(file_request.path)
            read_specs, normalization_error = _normalize_read_specs(file_request)
            if normalization_error:
                results.append(f"File: {file_request.path}\n{normalization_error}")
                continue

            # Large file check for JSON/YAML - conservative threshold to enforce grep->read workflow
            if not large_file_passthrough and path_obj.exists() and not path_obj.is_dir():
                file_ext = path_obj.suffix.lower()
                if file_ext in ['.json', '.yaml', '.yml']:
                    file_size = os.path.getsize(path_obj)
                    tokens = file_size / 4  # Approximate token count (4 chars per token)
                    if tokens > LARGE_FILE_TOKEN_THRESHOLD:
                        query_tool = "n/a ignore this line"
                        file_type = "n/a ignore this line"
                        if file_ext in ['.json', '.yaml', '.yml']:
                            file_type = "JSON" if file_ext == '.json' else "YAML"
                            query_tool = "query_jq" if file_type == "JSON" else "query_yq"
                        error_message = (
                            f"Error: {file_request.path} is a large {file_type} file (~{tokens:,.0f} tokens).\n\n"
                            "Reading the entire file may overflow your context window. Consider using these if the file is json / yaml:\n"
                            f"- {query_tool}(\"{file_request.path}\", \"keys\") to explore structure\n"
                            f"- {query_tool}(\"{file_request.path}\", \".items[0:10]\") to preview data\n"
                            f"- {query_tool}(\"{file_request.path}\", \".items[] | select(.field == 'value')\") to filter\n\n"
                            "- Or use grep_content to explore the file structure"
                            "- As a last resort, set large_file_passthrough=True to read anyway."
                        )
                        results.append(f"File: {file_request.path}\n{error_message}")
                        continue

            for index, read_spec in enumerate(read_specs, start=1):
                header = f"File: {file_request.path}"
                if file_request.reads is not None:
                    header += f" [read {index}/{len(read_specs)}: {_describe_read_spec(read_spec)}]"

                validation_error = _validate_read_spec(read_spec)
                if validation_error:
                    results.append(f"{header}\n{validation_error}")
                    continue

                if path_obj.is_dir():
                    content = "Error: Is a directory"
                else:
                    try:
                        content = _read_content_for_spec(path_obj, file_request.path, read_spec)
                        
                        # Apply RTK compression if compact=True (default)
                        if compact and not content.startswith("Error:"):
                            content, rtk_warning = _rtk_compress_content(content, file_request.path)
                            if rtk_warning:
                                header += f" {rtk_warning}"
                    except UnicodeDecodeError:
                        content = "Error: Binary file. Use read_media_file."

                results.append(f"{header}\n{content}")

        except Exception as e:
            results.append(f"File: {file_request.path}\nError: {e}")

    return "\n\n---\n\n".join(results)
@mcp.tool()
def read_media_file(path: str) -> dict:
    """Read an image or audio file as base64. Prefer relative paths."""
    path_obj = validate_path(path)
    mime_type, _ = mimetypes.guess_type(path_obj)
    if not mime_type: mime_type = "application/octet-stream"
        
    try:
        with open(path_obj, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        
        type_category = "image" if mime_type.startswith("image/") else "audio" if mime_type.startswith("audio/") else "blob"
        return {"type": type_category, "data": data, "mimeType": mime_type}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create a new file or completely overwrite an existing file. Prefer relative paths."""
    path_obj = validate_path(path)
    with open(path_obj, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Successfully wrote to {path}"

@mcp.tool()
def create_directory(path: str) -> str:
    """Create a new directory or ensure it exists. Prefer relative paths."""
    path_obj = validate_path(path)
    os.makedirs(path_obj, exist_ok=True)
    return f"Successfully created directory {path}"

@mcp.tool()
def list_directory(path: str) -> str:
    """Get a detailed listing of all files and directories. Prefer relative paths."""
    path_obj = validate_path(path)
    if not path_obj.is_dir(): return f"Error: {path} is not a directory"
    
    entries = []
    for entry in path_obj.iterdir():
        prefix = "[DIR]" if entry.is_dir() else "[FILE]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(sorted(entries))

@mcp.tool()
def list_directory_with_sizes(path: str) -> str:
    """Get listing with file sizes. Prefer relative paths."""
    path_obj = validate_path(path)
    if not path_obj.is_dir(): return f"Error: Not a directory"
    
    output = []
    for entry in path_obj.iterdir():
        try:
            s = entry.stat().st_size if not entry.is_dir() else 0
            prefix = "[DIR]" if entry.is_dir() else "[FILE]"
            size_str = "" if entry.is_dir() else format_size(s)
            output.append(f"{prefix} {entry.name.ljust(30)} {size_str}")
        except: continue
    return "\n".join(sorted(output))

@mcp.tool()
def move_file(source: str, destination: str) -> str:
    """Move or rename files. Prefer relative paths."""
    src = validate_path(source)
    dst = validate_path(destination)
    if dst.exists(): raise ValueError(f"Destination {destination} already exists")
    src.rename(dst)
    return f"Moved {source} to {destination}"

@mcp.tool()
def search_files(path: str, pattern: str) -> str:
    """Recursively search for files matching a glob pattern. Prefer relative paths."""
    root = validate_path(path)
    try:
        results = [str(p.relative_to(root)) for p in root.rglob(pattern) if p.is_file()]
        return "\n".join(results) or "No matches found."
    except Exception as e:
        return f"Error during search: {e}"


def _calculate_adaptive_chunk_size(estimated_tokens: int, line_count: int, p: Path) -> str:
    """
    Calculate recommended chunk size based on file size and token limits.
    Strategy: Start small for sampling, then scale up adaptively.
    """
    # Target: Keep each chunk under 30k tokens to leave room for context
    TARGET_TOKENS_PER_CHUNK = 5000
    SAFE_FIRST_SAMPLE = 50  # lines
    
    if estimated_tokens <= TARGET_TOKENS_PER_CHUNK:
        return "✅ File is small enough to read in one call (no chunking needed)"
    
    # Calculate tokens per line average
    tokens_per_line = estimated_tokens / line_count if line_count > 0 else 1
    
    # Calculate safe chunk size in lines
    recommended_lines = int(TARGET_TOKENS_PER_CHUNK / tokens_per_line) if tokens_per_line > 0 else 1000
    
    # Ensure minimum chunk size
    recommended_lines = max(100, recommended_lines)
    
    num_chunks = (line_count + recommended_lines - 1) // recommended_lines  # Ceiling division
    
    strategy = [
        f"⚠️  LARGE FILE WARNING: This file requires chunked reading",
        f"",
        f"Recommended Strategy:",
        f"  1. First sample: read_files([{{'path': '{p.name}', 'head': {SAFE_FIRST_SAMPLE}}}])",
        f"     (Start with {SAFE_FIRST_SAMPLE} lines to understand structure)",
        f"",
        f"  2. Then read in chunks of ~{recommended_lines:,} lines",
        f"     (Estimated {num_chunks} chunks total)",
        f"",
        f"  3. Example progression:",
        f"     - Chunk 1: head={recommended_lines}",
        f"     - Chunk 2: Use line numbers {recommended_lines}-{recommended_lines*2}",
        f"       (Note: read_files doesn't support offset+limit yet, so you may need",
        f"        to read overlapping chunks or work with the maintainer to add this)",
        f"",
        f"Estimated tokens per chunk: ~{int(recommended_lines * tokens_per_line):,}"
    ]
    
    return "\n".join(strategy)


def _analyze_json_structure(content: str) -> Optional[str]:
    """Analyze JSON structure and return a preview of keys and array lengths."""
    try:
        data = json.loads(content)
        lines = []
        
        if isinstance(data, dict):
            lines.append(f"Type: JSON Object")
            lines.append(f"Top-level keys ({len(data)}): {', '.join(list(data.keys())[:10])}")
            
            # Show array lengths for top-level arrays
            for key, value in list(data.items())[:5]:
                if isinstance(value, list):
                    lines.append(f"  - '{key}': Array with {len(value)} items")
                elif isinstance(value, dict):
                    lines.append(f"  - '{key}': Object with {len(value)} keys")
                else:
                    lines.append(f"  - '{key}': {type(value).__name__}")
        
        elif isinstance(data, list):
            lines.append(f"Type: JSON Array")
            lines.append(f"Total items: {len(data)}")
            if len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, dict):
                    lines.append(f"First item keys: {', '.join(list(first_item.keys())[:10])}")
        
        return "\n".join(lines)
    except json.JSONDecodeError:
        return "⚠️  Invalid JSON (parse error)"
    except Exception as e:
        return f"⚠️  Could not analyze JSON: {e}"


def _analyze_csv_structure(content: str) -> Optional[str]:
    """Analyze CSV structure and return column information."""
    try:
        lines = content.split('\n')
        if len(lines) < 1:
            return None
        
        # Assume first line is header
        header = lines[0]
        columns = header.split(',')
        
        result_lines = [
            f"Detected columns ({len(columns)}): {', '.join(col.strip() for col in columns[:10])}",
            f"Estimated rows: {len(lines) - 1:,}"
        ]
        
        if len(columns) > 10:
            result_lines.append(f"  ... and {len(columns) - 10} more columns")
        
        return "\n".join(result_lines)
    except Exception:
        return None

@mcp.tool()
def get_file_info(path: str) -> str:
    """
    Retrieve detailed metadata about a file, including size, structure analysis, and 
    recommended chunking strategy for large files. This tool is CRITICAL before reading 
    large files to avoid context overflow errors.
    
    Returns:
    - Basic metadata (path, type, size, modified time)
    - Line count (for text files)
    - Estimated token count
    - File type-specific analysis (JSON structure, CSV columns, etc.)
    - Recommended chunk size for iterative reading with read_files
    
    Prefer relative paths.
    """
    p = validate_path(path)
    
    if not p.exists():
        return f"Error: File not found at {path}"
    
    s = p.stat()
    is_dir = p.is_dir()
    
    # Basic info
    info_lines = [
        f"Path: {p}",
        f"Type: {'Directory' if is_dir else 'File'}",
        f"Size: {format_size(s.st_size)} ({s.st_size:,} bytes)",
        f"Modified: {datetime.fromtimestamp(s.st_mtime)}"
    ]
    
    if is_dir:
        return "\n".join(info_lines)
    
    # For files, add detailed analysis
    try:
        # Detect file type
        suffix = p.suffix.lower()
        mime_type, _ = mimetypes.guess_type(p)
        
        # Try to read as text
        try:
            content = p.read_text(encoding='utf-8')
            char_count = len(content)
            line_count = content.count('\n') + 1
            estimated_tokens = char_count // 4  # Rough approximation
            
            info_lines.append(f"\n--- Text File Analysis ---")
            info_lines.append(f"Total Lines: {line_count:,}")
            info_lines.append(f"Total Characters: {char_count:,}")
            info_lines.append(f"Estimated Tokens: {estimated_tokens:,} (rough estimate: chars ÷ 4)")
            
            # Adaptive chunk size recommendation
            chunk_recommendation = _calculate_adaptive_chunk_size(estimated_tokens, line_count, p)
            info_lines.append(f"\n--- Chunking Strategy ---")
            info_lines.append(chunk_recommendation)
            
            # File type-specific analysis
            if suffix == '.json' and char_count < 10_000_000:  # Don't parse huge files
                type_specific = _analyze_json_structure(content)
                if type_specific:
                    info_lines.append(f"\n--- JSON Structure Preview ---")
                    info_lines.append(type_specific)
            
            elif suffix == '.csv' and line_count > 1:
                type_specific = _analyze_csv_structure(content)
                if type_specific:
                    info_lines.append(f"\n--- CSV Structure ---")
                    info_lines.append(type_specific)
            
            elif suffix in ['.txt', '.md', '.log']:
                lines = content.split('\n')
                preview_lines = []
                if len(lines) > 0:
                    preview_lines.append(f"First line: {lines[0][:100]}")
                if len(lines) > 1:
                    preview_lines.append(f"Last line: {lines[-1][:100]}")
                if preview_lines:
                    info_lines.append(f"\n--- Content Preview ---")
                    info_lines.extend(preview_lines)
                    
        except UnicodeDecodeError:
            info_lines.append(f"\n--- Binary File ---")
            info_lines.append(f"MIME Type: {mime_type or 'application/octet-stream'}")
            info_lines.append(f"Note: Use read_media_file() for binary content")
    
    except Exception as e:
        info_lines.append(f"\nWarning: Could not analyze file content: {e}")
    
    return "\n".join(info_lines)





def _build_directory_tree_node(current: Path, depth: int, max_depth: int, excluded: List[str]) -> Optional[Dict[str, object]]:
    if depth > max_depth or current.name in excluded:
        return None

    node: Dict[str, object] = {
        "name": current.name,
        "type": "directory" if current.is_dir() else "file",
    }

    if current.is_dir():
        children: List[Dict[str, object]] = []
        try:
            for entry in sorted(current.iterdir(), key=lambda x: x.name):
                child = _build_directory_tree_node(entry, depth + 1, max_depth, excluded)
                if child:
                    children.append(child)
            if children:
                node["children"] = children
        except PermissionError:
            node["error"] = "Permission Denied"
    return node


def _render_compact_tree(node: Optional[Dict[str, object]]) -> str:
    if node is None:
        return "(empty)\n"

    def walk(current: Dict[str, object], prefix: str, is_last: bool, is_root: bool) -> List[str]:
        name = str(current.get("name", ""))
        if current.get("type") == "directory":
            name += "/"

        if is_root:
            lines = [name]
        else:
            connector = "\\-- " if is_last else "|-- "
            lines = [f"{prefix}{connector}{name}"]

        raw_children = current.get("children", [])
        children = raw_children if isinstance(raw_children, list) else []

        child_prefix = "" if is_root else prefix + ("    " if is_last else "|   ")
        for index, child in enumerate(children):
            if isinstance(child, dict):
                lines.extend(walk(child, child_prefix, index == len(children) - 1, False))

        if "error" in current:
            lines.append(f"{child_prefix}[error: {current['error']}]")

        return lines

    return "\n".join(walk(node, "", True, True)) + "\n"


def _path_context_header(root: Path) -> str:
    """Build a path context header showing the absolute root and allowed directories."""
    lines = [f"[path_context: {root}]"]
    if len(USER_ACCESSIBLE_DIRS) > 1:
        dirs_str = ", ".join(str(d) for d in USER_ACCESSIBLE_DIRS)
        lines.append(f"[allowed_dirs: {dirs_str}]")
    return "\n".join(lines)


@mcp.tool()
def directory_tree(
    path: str,
    max_depth: int = 4,
    exclude_dirs: Optional[List[str]] = None,
    compact: bool = True,
) -> str:
    """Get a recursive directory tree with path context for multi-server disambiguation.

    Output always includes `path_context` — the absolute resolved path of the listed
    directory. Use this to anchor relative path construction, especially when working
    with multiple fs-mcp server instances mounted on different directories or machines.

    When multiple allowed directories are configured, `allowed_dirs` is also included
    to show the full scope of directories this server can access.

    compact=True (default): token-efficient text tree with header lines:
        [path_context: /absolute/path/to/dir]
        dir/
        |-- src/
        |-- README.md

    compact=False: JSON object with top-level keys:
        {"path_context": "/absolute/path/to/dir", "allowed_dirs": [...], "tree": {...}}
    """
    root = validate_path(path)
    header = _path_context_header(root)

    default_excludes = [".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"]
    excluded = exclude_dirs if exclude_dirs is not None else default_excludes
    max_depth = 3 if isinstance(max_depth, str) else max_depth
    rtk_error: Optional[str] = None

    if compact:
        rtk_output, rtk_error = _rtk_tree(str(root), max_depth, excluded)
        if rtk_output is not None:
            return f"{header}\n{rtk_output}"

    tree = _build_directory_tree_node(root, 0, max_depth, excluded)

    if compact:
        compact_output = _render_compact_tree(tree)
        if rtk_error:
            return f"{header}\n[{rtk_error}; using built-in compact tree]\n{compact_output}"
        return f"{header}\n{compact_output}"

    tree_with_context = {"path_context": str(root), "allowed_dirs": [str(d) for d in USER_ACCESSIBLE_DIRS], "tree": tree}
    return json.dumps(tree_with_context, separators=(",", ":"))


# --- Direct File Editing Tool (Core) ---

@mcp.tool()
async def edit_files(
    files: Annotated[
        List[FileEdit],
        Field(description="Files to edit. Each has a path and ordered list of edits.")
    ],
) -> str:
    """Edit one or more files with find-and-replace. Writes directly.

    USAGE:
      edit_files(files=[{
        "path": "src/main.py",
        "edits": [{"match_text": "old", "new_string": "new"}]
      }])

    MULTI-FILE:
      edit_files(files=[
        {"path": "a.py", "edits": [{"match_text": "x", "new_string": "y"}]},
        {"path": "b.py", "edits": [{"match_text": "a", "new_string": "b"}]}
      ])

    SPECIAL match_text VALUES:
      ""               = Create new file (must not exist)
      "OVERWRITE_FILE" = Replace entire file
      "APPEND_TO_FILE" = Append to end

    RULES:
    - match_text is EXACT literal (not regex). Whitespace matters.
    - Each match_text must appear exactly once.
    - Edits apply in order per file. Files are independent.
    - Errors include fuzzy match hints with line numbers.
    - WORKFLOW: read_files -> copy exact text -> paste as match_text.
    """
    results = []
    all_success = True

    for file_edit in files:
        edits_dicts = [e.model_dump() for e in file_edit.edits]
        result = apply_file_edits(validate_path, file_edit.path, edits_dicts)
        result["path"] = file_edit.path
        if result["status"] == "error":
            all_success = False
        results.append(result)

        # Auto-dump GSD artifacts on successful write
        if result["status"] in ("ok", "created"):
            try:
                committed_path = validate_path(file_edit.path)
                if _is_gsd_artifact(committed_path):
                    _trigger_gsd_dump(committed_path)
            except Exception:
                pass

    response = {"success": all_success, "files": results}
    return json.dumps(response, indent=2)


# --- Interactive Human-in-the-Loop Tools ---




@mcp.tool()
async def propose_and_review(
    path: Annotated[
        str,
        Field(description="Path to the file to edit. Relative paths (e.g., 'src/main.py') or absolute paths both work.")
    ],
    new_string: Annotated[
        str,
        Field(default="", description="The replacement text.")
    ] = "",
    match_text: Annotated[
        str,
        Field(default="", description=MATCH_TEXT_DESCRIPTION)
    ] = "",
    expected_replacements: Annotated[
        int,
        Field(default=1, description="How many times match_text should appear. Default 1 = must be unique (ERRORS if found 0 or 2+ times). Set to N to replace all N occurrences.")
    ] = 1,
    session_path: Annotated[
        Optional[str],
        Field(default=None, description="ONLY for continuing after 'REVIEW' response. When user modifies your proposal, pass session_path here and set match_text to the USER's edited text (from user_feedback_diff), then new_string to your next proposal. Or call commit_review to accept user's version as-is.")
    ] = None,
    edits: Annotated[
        Optional[List[EditPair]],
        Field(default=None, description=EDITS_DESCRIPTION)
    ] = None,
    bypass_match_text_limit: Annotated[
        bool,
        Field(default=False, description=BYPASS_MATCH_TEXT_LIMIT_DESCRIPTION)
    ] = False
) -> str:
    """
    Edit a file with human review. Returns COMMITTED or REVIEW response.

    ##
    QUICK REFERENCE (copy these patterns)
    

    EDIT FILE:    propose_and_review(path="file.py", match_text="old", new_string="new")
    NEW FILE:     propose_and_review(path="new.py", match_text="", new_string="content")
    APPEND FILE:  propose_and_review(path="file.py", match_text="APPEND_TO_FILE", new_string="content")
    BATCH EDIT:   propose_and_review(path="file.py", edits=[{"match_text":"a","new_string":"b"}])

    ##
    MODES (Mutually Exclusive)

    1. SINGLE EDIT:  path + match_text + new_string
    2. BATCH EDIT:   path + edits (array of {match_text, new_string})
    3. NEW FILE:     path + match_text="" + new_string
    4. OVERWRITE:    path + match_text="OVERWRITE_FILE" + new_string
    5. APPEND:       path + match_text="APPEND_TO_FILE" + new_string

    ##
    WORKFLOW: READ FILE → COPY EXACT TEXT → PASTE AS match_text
    

    match_text must be LITERAL and EXACT (not regex). Whitespace matters.

    ERRORS ARE HELPFUL: "No match found" or "found N matches, expected 1"
    tells you exactly what went wrong. Just re-read file and fix match_text.

    Multi-line example (file has "def foo():" on one line, "    return 1" on next):
      match_text="def foo():\\n    return 1"

    ##
    RESPONSE HANDLING
    

    IF "COMMITTED": File has been written. No further action needed.

    IF "REVIEW": User edited your proposal. Response contains:
      - session_path: Pass in your next call
      - user_feedback_diff: Shows what user changed
      Next call: match_text = user's edited version (not yours)

    ##
    SPECIAL VALUES FOR match_text
    
    ""              = Create new file (file must not exist)
    "OVERWRITE_FILE" = Replace entire file content
    "APPEND_TO_FILE" = Append new_string to end (file must exist)

    ##
    NOTES
    
    - Paths: relative ("src/main.py") or absolute both work
    - expected_replacements=1 means match must be unique (errors if 0 or 2+ found)
    - user_feedback_diff is a unified diff showing exactly what user changed
    - If workspace root contains `FS_MCP_FLAG`, this tool skips interactive review and commits directly
    """
    result = await propose_and_review_logic(
        validate_path,
        IS_VSCODE_CLI_AVAILABLE,
        path,
        new_string,
        match_text,
        expected_replacements,
        session_path,
        edits,
        bypass_match_text_limit,
        dangerous_skip_permissions=_dangerous_skip_permissions_enabled(),
    )

    # Auto-dump GSD artifacts on commit (non-blocking, debounced)
    if "COMMITTED" in result:
        try:
            committed_path = validate_path(path)
            if _is_gsd_artifact(committed_path):
                _trigger_gsd_dump(committed_path)
        except Exception:
            pass  # Never let dump logic break the main flow

    return result

@mcp.tool()
def commit_review(session_path: str, original_path: str) -> str:
    """Finalizes an interactive review session by committing the approved changes."""
    session_dir = Path(session_path)
    original_file = validate_path(original_path)
    if not session_dir.is_dir():
        raise ValueError(f"Invalid session path: {session_path}")
    future_file = session_dir / f"future_{original_file.name}"
    if not future_file.exists():
        raise FileNotFoundError(f"Approved file not found in session: {future_file}")
    approved_content = future_file.read_text(encoding='utf-8')
    final_content = approved_content.rstrip('\n')
    try:
        original_file.write_text(final_content, encoding='utf-8')
    except Exception as e:
        raise IOError(f"Failed to write final content to {original_path}: {e}")

    # Auto-dump GSD artifacts on commit (non-blocking, debounced)
    if _is_gsd_artifact(original_file):
        _trigger_gsd_dump(original_file)

    try:
        shutil.rmtree(session_dir)
    except Exception as e:
        return f"Successfully committed changes to {original_path}, but failed to clean up session dir {session_path}: {e}"
    return f"Successfully committed changes to '{original_path}' and cleaned up the review session."
@mcp.tool()
def grounding_search(query: str) -> str:
    """[NEW] A custom search tool. Accepts a natural language query and returns a grounded response."""
    # This is a placeholder for a future RAG or other search implementation.
    print(f"Received grounding search query: {query}")
    return "DEVELOPER PLEASE UPDATE THIS WITH ACTUAL CONTENT"


@mcp.tool()
def grep_content(
    pattern: Annotated[
        str,
        Field(description="The regex pattern to search for in file contents. WORKFLOW: Use grep_content FIRST to locate files and line numbers, then read_files for targeted reading. This preserves context by avoiding full file reads. Output includes 'section end hint' to show where functions/classes end.")
    ],
    search_path: Annotated[
        str,
        Field(default='.', description="The directory or file to search in. Defaults to current directory. Prefer relative paths.")
    ] = '.',
    case_insensitive: Annotated[
        bool,
        Field(default=False, description="If True, perform case-insensitive matching (rg -i flag).")
    ] = False,
    context_lines: Annotated[
        int,
        Field(default=2, description="Number of lines of context to show before and after each match (rg --context flag).")
    ] = 2,
    section_patterns: Annotated[
        Optional[List[str]],
        Field(default=None, description="Regex patterns for section boundary detection to generate 'section end hint' metadata. Default: Python patterns ['^def ', '^class ']. Custom: provide your own patterns. Disable: pass empty list []. Use the hint to know exactly which lines to read with read_files.")
    ] = None,
    compact: Annotated[
        bool,
        Field(default=True, description="Token-efficient mode via RTK grep. DEFAULT=True returns grouped results (70-80%% token savings). Set compact=False for full ripgrep output with section end hints (needed for precise line targeting).")
    ] = True
) -> str:
    """
    Search for a pattern in file contents using ripgrep.

    **DEFAULT BEHAVIOR (compact=True):**
    Returns TOKEN-OPTIMIZED grouped results via RTK:
    - Matches grouped by file with counts
    - Content truncated to relevant context
    - 70-80%% token savings
    - NOTE: Section end hints not available in compact mode

    **FOR TARGETED READING (compact=False):**
    Returns full ripgrep output with section end hints.
    Use when you need exact line boundaries for read_files targeting.

    **Workflow:**
    1. compact=True: "Find all usages of calculate_total" → explore
    2. compact=False: "I found it, now I need exact lines to read" → target
    3. read_files: surgical read with start_line/end_line

    **Mandatory File Interaction Protocol (compact=False mode):**
    1.  **`grep_content`**: Use this tool with a specific pattern to find *which files* are relevant and *where* in those files the relevant code is (line numbers). Its primary purpose is to **locate file paths and line numbers**, not to read full file contents.
    2.  Hint: Critically inspect the grep output for the (section end hint: ...) metadata. This hint defines the full boundary of the relevant content.
    3.  **`read_files`**: Use the file path and line numbers from the output of this tool to perform a targeted read of only the relevant file sections.
    4.  NEVER assume a single grep match represents the full context. The purpose of this protocol is to replace assumption with evidence.


    **Example:**
    ```
    # Step 1: Find where 'FastMCP' is defined.
    grep_content(pattern="class FastMCP")

    # Output might be: File: src/fs_mcp/server.py, Line: 20 (section end hint: L42)

    # Step 2: Read the relevant section of that file.
    read_files([{"path": "src/fs_mcp/server.py", "start_line": 20, "end_line": 42}])
    ```

    **Section End Hinting:**
    - The tool can optionally provide a `section_end_hint` to suggest where a logical block (like a function or class) ends.
    - This is enabled by default with patterns for Python (`def`, `class`).
    - To use custom patterns, provide `section_patterns=["^\\s*custom_pattern"]`.
    - To disable, pass `section_patterns=[]`.
    """
    if not IS_RIPGREP_AVAILABLE:
        _, msg = check_ripgrep()
        return f"Error: ripgrep is not available. {msg}"

    validated_path = validate_path(search_path)
    
    # Use RTK grep for compact mode (default)
    if compact:
        rtk_output, rtk_error = _rtk_grep(pattern, str(validated_path))
        if rtk_error:
            # Fallback to regular ripgrep if RTK fails
            # Note: Must use .fn since grep_content is decorated with @mcp.tool()
            return f"[RTK grep failed: {rtk_error}, falling back to ripgrep]\n\n" + grep_content.fn(
                pattern=pattern,
                search_path=search_path,
                case_insensitive=case_insensitive,
                context_lines=context_lines,
                section_patterns=section_patterns,
                compact=False  # Prevent infinite recursion
            )
        return rtk_output if rtk_output.strip() else "No matches found."
    
    # Non-compact mode: use ripgrep with section hints
    command = [
        'rg',
        '--json',
        '--max-count=100',
        f'--context={context_lines}',
    ]
    if case_insensitive:
        command.append('--ignore-case')
    
    command.extend([pattern, str(validated_path)])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False  # Don't raise exception for non-zero exit codes
        )
    except FileNotFoundError:
        return "Error: 'rg' command not found. Please ensure ripgrep is installed and in your PATH."
    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 10 seconds. Please try a more specific pattern."

    if result.returncode != 0 and result.returncode != 1:
        # ripgrep exits with 1 for no matches, which is not an error for us.
        # Other non-zero exit codes indicate a real error.
        return f"Error executing ripgrep: {result.stderr}"

    output_lines = []
    matches_found = False
    
    # --- Section End Hinting Configuration ---
    active_patterns = []
    if section_patterns is None:
        # Default Python patterns
        active_patterns = [r'^\\s*def ', r'^\\s*class ']
    elif section_patterns: # Not an empty list
        active_patterns = section_patterns

    for line in result.stdout.strip().split('\n'):
        try:
            message = json.loads(line)
            if message['type'] == 'match':
                matches_found = True
                data = message['data']
                path_str = data['path']['text']
                line_number = data['line_number']
                text = data['lines']['text']
                
                hint = ""
                # --- Generate Hint if Enabled ---
                if active_patterns:
                    try:
                        result_file_path = validate_path(path_str)
                        with open(result_file_path, 'r', encoding='utf-8') as f:
                            # Use islice to efficiently seek to the line after the match
                            line_iterator = itertools.islice(f, line_number, None)
                            
                            end_line_num = -1
                            # Scan subsequent lines for a pattern match
                            for i, subsequent_line in enumerate(line_iterator, start=line_number + 1):
                                if any(re.search(p, subsequent_line) for p in active_patterns):
                                    end_line_num = i
                                    break
                            
                            if end_line_num != -1:
                                hint = f" (section end hint: L{end_line_num})"
                            else:
                                hint = " (section end hint: EOF)"

                    except Exception:
                        # If hint generation fails for any reason, just don't add it.
                        pass

                output_lines.append(f"File: {path_str}, Line: {line_number}{hint}\n---\n{text.strip()}\n---")
        except (json.JSONDecodeError, KeyError):
            # Ignore non-match lines or lines with unexpected structure
            continue

    if not matches_found:
        return "No matches found."

    return "\n\n".join(output_lines)




@mcp.tool()
def query_jq(
    file_path: Annotated[
        str,
        Field(description="Path to the JSON file to query. Supports relative or absolute paths.")
    ],
    jq_expression: Annotated[
        str,
        Field(description="The jq query expression. Examples: '.field_name' (get field), '.items[]' (iterate array), '.items[] | select(.active == true)' (filter), '.items | length' (count). See https://jqlang.github.io/jq/manual/")
    ],
    timeout: Annotated[
        int,
        Field(default=30, description="Query timeout in seconds. Default is 30. Increase for complex queries on large files.")
    ] = 30
) -> str:
    """
    Query a JSON file using jq expressions. Use this to efficiently explore large JSON files
    without reading the entire content into memory.

    **Common Query Patterns:**
    - Get specific field: '.field_name'
    - Array iteration: '.items[]'
    - Filter array: '.items[] | select(.active == true)'
    - Select fields: '.items[] | {name, id}'
    - Array slice: '.items[0:100]' (first 100 items)
    - Count items: '.items | length'

    **Multiline Queries (with comments):**
    query_jq("data.json", '''
    # Filter active items
    .items[] | select(.active == true)
    ''')

    **Workflow Example:**
    1. Get structure overview: query_jq("data.json", "keys")
    2. Count array items: query_jq("data.json", ".items | length")
    3. Explore first few: query_jq("data.json", ".items[0:5]")
    4. Filter specific: query_jq("data.json", ".items[] | select(.status == 'active')")

    **Result Limit:** Returns first 100 results. For more, use slicing: .items[100:200]
    """
    if not IS_JQ_AVAILABLE:
        _, msg = check_jq()
        return f"Error: jq is not available. {msg}"

    validated_path = validate_path(file_path)

    # Create temp file for query expression to avoid command-line escaping issues
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jq', delete=False)
        temp_file.write(jq_expression)
        temp_file.close()

        command = ['jq', '-c', '-f', temp_file.name, str(validated_path)]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
        except FileNotFoundError:
            return "Error: 'jq' command not found. Please ensure jq is installed and in your PATH."
        except subprocess.TimeoutExpired:
            return f"Error: Query timed out after {timeout} seconds. Please simplify your query."

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            return f"jq syntax error: {error_msg}. Check your query for common issues (unclosed brackets, missing semicolons, undefined functions)."

        output = result.stdout.strip()
        if not output or output == 'null':
            return "No results found."

        lines = output.split('\n')

        if len(lines) > 100:
            truncated_output = "\n".join(lines[:100])
            return f"{truncated_output}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use jq slicing: .items[100:200]"

        return output
    finally:
        # Clean up temp file
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass



@mcp.tool()
def query_yq(
    file_path: Annotated[
        str,
        Field(description="Path to the file to query. Supports relative or absolute paths.")
    ],
    yq_expression: Annotated[
        str,
        Field(description="The yq query expression (jq-like syntax). Examples: '.field_name' (get field), '.items[]' (iterate array), '.items[] | select(.active == true)' (filter), '.items | length' (count). See mikefarah.gitbook.io/yq")
    ],
    input_format: Annotated[
        Literal["yaml", "json", "xml", "csv", "tsv", "toml", "props", "ini", "hcl"],
        Field(default="yaml", description="Input file format. Use 'xml' for .twb/.pom/.rss, 'toml' for pyproject.toml/Cargo.toml, 'props' for .properties, 'csv'/'tsv' for tabular data, 'ini' for .ini/.cfg, 'hcl' for Terraform .tf files.")
    ] = "yaml",
    timeout: Annotated[
        int,
        Field(default=30, description="Query timeout in seconds. Default is 30. Increase for complex queries on large files.")
    ] = 30
) -> str:
    """
    Query structured data files using yq (mikefarah/yq). Supports YAML, JSON, XML, CSV, TSV, TOML, Properties, INI, and HCL formats.

    **Multi-Format Examples:**
    - XML (Tableau .twb): `query_yq("file.twb", ". | keys", input_format="xml")`
    - TOML: `query_yq("pyproject.toml", ".project.name", input_format="toml")`
    - CSV: `query_yq("data.csv", ".[0]", input_format="csv")` (first row as object)

    **Common Query Patterns:**
    - Get field: '.field_name' | Iterate: '.items[]' | Filter: '.items[] | select(.active)'
    - Count: '.items | length' | Slice: '.items[0:100]'

    **Result Limit:** First 100 results. Use slicing for more: `.items[100:200]`
    """
    if not IS_YQ_AVAILABLE:
        _, msg = check_yq()
        return f"Error: yq is not available. {msg}"

    validated_path = validate_path(file_path)

    # Create temp file for query expression to avoid command-line escaping issues
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yq', delete=False)
        temp_file.write(yq_expression)
        temp_file.close()

        command = ['yq', '-o', 'json', '-I', '0']
        if input_format != "yaml":
            command.extend(['-p', input_format])
        command.extend(['--from-file', temp_file.name, str(validated_path)])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
        except FileNotFoundError:
            return "Error: 'yq' command not found. Please ensure yq is installed and in your PATH."
        except subprocess.TimeoutExpired:
            return f"Error: Query timed out after {timeout} seconds. Please simplify your query."

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            return f"yq syntax error: {error_msg}. Check your query for common issues (unclosed brackets, missing semicolons, undefined functions)."

        output = result.stdout.strip()
        if not output or output == 'null':
            return "No results found."

        lines = output.split('\n')

        if len(lines) > 100:
            truncated_output = "\n".join(lines[:100])
            return f"{truncated_output}\n\n--- Truncated. Showing 100 of {len(lines)} results. ---\nRefine your query or use yq slicing: .items[100:200]"

        return output
    finally:
        # Clean up temp file
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


@mcp.tool()
def append_text(path: str, content: str) -> str:
    """
    Append text to the end of a file. If the file does not exist, it will be created.
    Use this as a fallback if edit_file fails to find a match.
    Prefer relative paths.
    """
    p = validate_path(path)
    
    # Ensure there is a newline at the start of the append if the file doesn't have one
    # to avoid clashing with the existing last line.
    with open(p, 'a', encoding='utf-8') as f:
        # Check if we need a leading newline
        if p.exists() and p.stat().st_size > 0:
            f.write("\n")
        f.write(content)
        
    return f"Successfully appended content to '{path}'."


@mcp.tool()
def analyze_gsd_work_log(
    file_path: Annotated[
        str,
        Field(
            default="gsd-lite/WORK.md",
            description="Path to the GSD-Lite WORK.md file. Defaults to 'gsd-lite/WORK.md'."
        )
    ] = "gsd-lite/WORK.md",
    output_format: Annotated[
        Literal["json", "table"],
        Field(
            default="json",
            description="Output format: 'json' for machine-readable structured data, 'table' for human-readable summary."
        )
    ] = "json"
) -> str:
    """
    Analyze a GSD-Lite WORK.md file to detect semantic signals for housekeeping.

    This tool implements context-aware signal detection that avoids false positives
    when documentation contains examples of the patterns being detected (the "Quine Paradox").

    **What it detects:**

    **Tier 1 Signals (High Confidence - Auto-Flag):**
    - `~~strikethrough titles~~` in log headers
    - `SUPERSEDED BY: LOG-XXX` tags
    - `[DEPRECATED]`, `[OBSOLETE]`, `[ARCHIVED]` markers
    - Status fields indicating obsolete/abandoned

    **Tier 2 Signals (Medium Confidence - Review Needed):**
    - `Depends On:` references
    - Words like "supersedes", "replaces", "pivot"
    - Phrases like "hit a wall", "decided not to"

    **False Positive Prevention:**
    - Code blocks (```...```) are masked before scanning
    - Inline code (`...`) is masked before scanning
    - Header-only signals (strikethrough) only match in `### [LOG-XXX]` lines

    **Output (JSON format):**
    ```json
    {
      "summary": {
        "total_tokens": 65420,
        "total_logs": 24,
        "tier_1_flags": 3,
        "tier_2_flags": 12
      },
      "logs": [
        {
          "log_id": "LOG-018",
          "type": "DECISION",
          "task": "PHASE-002",
          "tokens": 1200,
          "lines": [3213, 3287],
          "signals": {
            "tier_1": ["strikethrough: ~~Pivot to Public Data~~ (L3213)"],
            "tier_2": ["depends_on: LOG-017 (L3220)"]
          }
        }
      ]
    }
    ```

    **Workflow Example:**
    1. Run analysis: `analyze_gsd_work_log("gsd-lite/WORK.md")`
    2. Review Tier 1 flags (likely superseded)
    3. Investigate Tier 2 flags with user
    4. Use results to guide archival decisions
    """
    validated_path = validate_path(file_path)
    
    try:
        result = analyze_gsd_logs(str(validated_path), format=output_format)
        
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        else:
            return result
            
    except FileNotFoundError:
        return f"Error: File not found at '{file_path}'. Ensure the path is correct and the file exists."
    except Exception as e:
        return f"Error analyzing file: {str(e)}"
    

@mcp.tool()
def list_gsd_lite_dirs(
    max_depth: Annotated[
        int,
        Field(
            default=15,
            description="Maximum directory depth to search. Default 15."
        )
    ] = 15,
    include_meta: Annotated[
        bool,
        Field(
            default=True,
            description="Include PROJECT.md content (~5 lines) to help agents match natural-language project descriptions to paths."
        )
    ] = True
) -> str:
    """
    List all gsd-lite/ directories found in the server's allowed directories.

    Returns paths and optional metadata to help agents route natural-language
    project references (e.g. "the tableau migration project") to exact paths.

    **Strategy:** Uses ripgrep (fast, respects .gitignore) to find gsd-lite/PROJECT.md
    files, then derives directory paths. Falls back to Python os.walk if ripgrep
    is unavailable or fails.

    **Noise filtering:** Automatically skips:
    - node_modules, .venv, __pycache__, .git, .cache, .npm
    - test/eval fixture directories (tests/evals/)
    - template directories (template/gsd-lite)
    - .opencode/command/ copies

    **Output (include_meta=True):**
    ```
    fs-mcp/gsd-lite
      A universal, provider-agnostic filesystem MCP server designed for AI agents.
      It acts as a "smart driver" for remote codebases, providing efficient access
      patterns (grep -> read), structured data querying, and safe editing workflows.

    ticktick_dbt/gsd-lite
      A personal data platform for GTD-driven life decisions. Extracts task data
      from TickTick and Todoist into a dbt warehouse for analysis.
    ```

    **Output (include_meta=False):**
    ```
    fs-mcp/gsd-lite
    ticktick_dbt/gsd-lite
    ```
    """
    import time as _time
    start = _time.monotonic()
    TIMEOUT_SECONDS = 30

    MAX_SUMMARY_LINES = 5
    SKIP_PATTERNS = {
        "node_modules", ".venv", "__pycache__", ".git", ".cache", ".npm",
        "venv", "site-packages", ".tox", "dist", "build",
    }
    NOISE_PATH_FRAGMENTS = {
        "tests/evals/", "template/gsd-lite", ".opencode/command/",
        "wt-npm/", "/persistent/home/",  # docker mirrors
        "wheels-v5",  # uv/pip cache
    }

    found_dirs: list[dict] = []

    def _is_noise(path_str: str) -> bool:
        return any(frag in path_str for frag in NOISE_PATH_FRAGMENTS)

    def _get_project_summary(gsd_dir: Path) -> list[str]:
        """Read first ~5 content lines of PROJECT.md for natural-language matching."""
        project_md = gsd_dir / "PROJECT.md"
        if not project_md.exists():
            return ["(no PROJECT.md)"]
        try:
            content_lines: list[str] = []
            with open(project_md, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    # Skip markdown headers, blank lines, metadata
                    if not stripped or stripped.startswith("#") or stripped.startswith("*Initialized"):
                        continue
                    # Skip section markers like ## What This Is
                    if stripped.startswith("## "):
                        continue
                    content_lines.append(stripped)
                    if len(content_lines) >= MAX_SUMMARY_LINES:
                        break
            if not content_lines:
                # Fallback: use the first header
                with open(project_md, "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith("# "):
                            return [stripped[2:].strip()]
            return content_lines if content_lines else ["(empty)"]
        except Exception:
            return ["(unreadable)"]

    def _try_ripgrep() -> bool:
        """Try to find gsd-lite dirs via ripgrep. Returns True if successful."""
        rg_binary = shutil.which('rg')
        if not rg_binary:
            return False

        # Verify it's real ripgrep, not a grep wrapper
        try:
            ver_result = subprocess.run(
                [rg_binary, '--version'],
                capture_output=True, text=True, timeout=5
            )
            if 'ripgrep' not in ver_result.stdout.lower():
                return False
        except Exception:
            return False

        for base_dir in ALLOWED_DIRS:
            if _time.monotonic() - start > TIMEOUT_SECONDS:
                break
            try:
                result = subprocess.run(
                    [
                        rg_binary, '--files',
                        '--glob', '**/gsd-lite/PROJECT.md',
                        f'--max-depth={max_depth}',
                        '--no-ignore',  # don't skip gitignored dirs
                        str(base_dir)
                    ],
                    capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                    check=False
                )
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    p = Path(line)
                    gsd_dir = p.parent  # strip PROJECT.md to get gsd-lite/
                    try:
                        rel = str(gsd_dir.relative_to(base_dir))
                    except ValueError:
                        rel = str(gsd_dir)
                    if not _is_noise(rel):
                        found_dirs.append({"path": rel, "abs": gsd_dir})
            except (subprocess.TimeoutExpired, Exception):
                continue
        return len(found_dirs) > 0

    def _try_python_walk() -> None:
        """Fallback: os.walk with skip-list."""
        for base_dir in ALLOWED_DIRS:
            for root, dirs, files in os.walk(base_dir):
                if _time.monotonic() - start > TIMEOUT_SECONDS:
                    return
                # Depth check
                depth = str(root).replace(str(base_dir), '').count(os.sep)
                if depth > max_depth:
                    dirs.clear()
                    continue
                # Prune junk
                dirs[:] = [d for d in dirs if d not in SKIP_PATTERNS]

                current = Path(root)
                if current.name == "gsd-lite" and (current / "PROJECT.md").exists():
                    try:
                        rel = str(current.relative_to(base_dir))
                    except ValueError:
                        rel = str(current)
                    if not _is_noise(rel):
                        found_dirs.append({"path": rel, "abs": current})
                    dirs.clear()  # don't recurse into gsd-lite/

    # --- Execution ---
    rg_used = _try_ripgrep()
    if not rg_used:
        _try_python_walk()

    if not found_dirs:
        return "No gsd-lite directories found."

    # Deduplicate by path
    seen = set()
    unique = []
    for d in found_dirs:
        if d["path"] not in seen:
            seen.add(d["path"])
            unique.append(d)
    found_dirs = sorted(unique, key=lambda x: x["path"])

    elapsed = _time.monotonic() - start
    method = "ripgrep" if rg_used else "os.walk"
    header = f"Found {len(found_dirs)} gsd-lite project(s) [{method}, {elapsed:.1f}s]"

    lines = [header, ""]
    for d in found_dirs:
        lines.append(d["path"])
        if include_meta:
            summary_lines = _get_project_summary(d["abs"])
            for sl in summary_lines:
                lines.append(f"  {sl}")
            lines.append("")

    return "\n".join(lines)


@mcp.tool()
def query_duckdb(
    sql: Annotated[
        str,
        Field(description="SQL query to execute via DuckDB. Use file-reading functions to query data files directly:\n"
              "- CSV: `SELECT * FROM read_csv_auto('data.csv') LIMIT 10`\n"
              "- Parquet: `SELECT * FROM read_parquet('data.parquet')`\n"
              "- JSON: `SELECT * FROM read_json_auto('data.json')`\n"
              "- Glob: `SELECT * FROM read_csv_auto('data/*.csv')`\n\n"
              "Supports full SQL: JOIN, GROUP BY, HAVING, window functions, CTEs, UNION, PIVOT.\n\n"
              "**Write-back:** `COPY (SELECT ...) TO 'output.csv' (HEADER, DELIMITER ',')`\n"
              "**Format conversion:** `COPY (SELECT * FROM read_csv_auto('big.csv')) TO 'big.parquet' (FORMAT PARQUET)`\n"
              "**Schema inspect:** `DESCRIBE SELECT * FROM read_csv_auto('data.csv')`")
    ],
    timeout: Annotated[
        int,
        Field(default=30, description="Query timeout in seconds. Default is 30. Increase for complex queries on large files.")
    ] = 30
) -> str:
    """
    Query tabular data files using DuckDB SQL. Reads CSV, Parquet, and JSON files directly — no import step needed.

    **Why use this over grep/yq for tabular data:**
    - Full SQL: GROUP BY, JOIN, window functions, CTEs, PIVOT
    - No false positives from pattern matching on CSV content
    - Accurate aggregations and field-level filtering

    **Common Patterns:**
    - Explore: `SELECT * FROM read_csv_auto('data.csv') LIMIT 10`
    - Aggregate: `SELECT col, COUNT(*) FROM read_csv_auto('data.csv') GROUP BY 1 ORDER BY 2 DESC`
    - Join files: `SELECT a.*, b.label FROM read_csv_auto('a.csv') a JOIN read_csv_auto('b.csv') b ON a.id = b.id`
    - Filter + export: `COPY (SELECT * FROM read_csv_auto('data.csv') WHERE status = 'active') TO 'filtered.csv' (HEADER)`
    - Schema: `DESCRIBE SELECT * FROM read_csv_auto('data.csv')`
    - Convert: `COPY (SELECT * FROM read_csv_auto('big.csv')) TO 'big.parquet' (FORMAT PARQUET)`

    **Result Format:** JSON array of objects (proxy-safe for pagination via read_cache).
    Control result size with LIMIT in your SQL query.
    """
    # For COPY TO / EXPORT statements, validate the output path is within allowed directories
    write_match = re.search(r"\bTO\s+'([^']+)'", sql, re.IGNORECASE)
    if write_match:
        output_path = write_match.group(1)
        try:
            validate_path(output_path)
        except ValueError as e:
            return f"Error: Output path validation failed — {e}"

    # Block multi-statement SQL (security: prevent DDL injection via semicolons)
    stripped_sql = sql.strip().rstrip(';')
    if ';' in stripped_sql:
        return "Error: Multi-statement SQL is not allowed. Submit one statement at a time."

    conn = duckdb.connect(":memory:")
    try:
        # Execute with timeout using threading + conn.interrupt()
        result_holder = [None]
        error_holder = [None]

        def _execute():
            try:
                result_holder[0] = conn.execute(sql)
            except Exception as e:
                error_holder[0] = e

        thread = threading.Thread(target=_execute)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            conn.interrupt()
            thread.join(timeout=5)
            return f"Error: Query timed out after {timeout} seconds. Simplify your query or increase timeout."

        if error_holder[0] is not None:
            return f"DuckDB error: {error_holder[0]}"

        result = result_holder[0]

        # Non-SELECT statements (COPY TO, CREATE, etc.) — no result set
        if result.description is None:
            if write_match:
                return f"Query executed successfully. Output written to `{write_match.group(1)}`."
            return "Query executed successfully."

        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        if not rows:
            return "No results found."

        # Return JSON array — proxy-safe for read_cache pagination (LOG-006 design rule).
        # Agent controls result size via LIMIT in SQL query.
        # Sanitize non-JSON-safe float values (Infinity, NaN → null)
        result_dicts = [
            {col: (None if isinstance(val, float) and (math.isinf(val) or math.isnan(val)) else val)
             for col, val in zip(columns, row)}
            for row in rows
        ]
        return json.dumps(result_dicts, default=str)

    except Exception as e:
        return f"DuckDB error: {e}"
    finally:
        conn.close()


# --- Shell Command Execution Tool (Core) ---

def _validate_command_safety(command: str) -> Optional[str]:
    """Check command against blocked commands/patterns. Returns error message or None if safe."""
    stripped = command.strip()
    if not stripped:
        return "Error: Empty command."

    # Extract first token (the actual binary being called)
    # Handle: sudo X, env X, bash -c 'X', sh -c 'X'
    tokens = stripped.split()
    first_token = tokens[0].lower()

    # Unwrap common wrappers to get the real command
    idx = 0
    while idx < len(tokens):
        t = tokens[idx].lower()
        if t == "sudo":
            idx += 1
            continue
        if t == "env" and idx + 1 < len(tokens) and "=" in tokens[idx + 1]:
            idx += 2
            continue
        break
    real_cmd = tokens[idx].lower() if idx < len(tokens) else first_token
    # Strip path prefix (e.g., /bin/rm -> rm)
    real_cmd = real_cmd.rsplit("/", 1)[-1]

    if real_cmd in BLOCKED_COMMANDS:
        return f"Error: Command '{real_cmd}' is blocked for safety. Blocked commands: {', '.join(sorted(BLOCKED_COMMANDS))}"

    # Check patterns anywhere in command
    for pattern in BLOCKED_PATTERNS:
        if pattern in command:
            return f"Error: Command contains blocked pattern '{pattern}'."

    return None


@mcp.tool()
async def run_command(
    command: Annotated[
        str,
        Field(description="Shell command to execute. Supports pipes, redirects, &&, ||, etc. "
              "Runs in /bin/bash. Destructive commands (rm, kill, shutdown, etc.) are blocked.")
    ],
    working_dir: Annotated[
        str,
        Field(default=".", description="Working directory for the command. Must be within allowed directories. "
              "Defaults to server root.")
    ] = ".",
    timeout: Annotated[
        int,
        Field(default=30, description="Timeout in seconds. Default 30. Increase for builds/tests.")
    ] = 30,
    compact: Annotated[
        bool,
        Field(default=True, description="When true, pipe stdout through RTK for token-efficient compression. "
              "Set false for exact output (e.g., diffs, error debugging).")
    ] = True,
) -> str:
    """Run a shell command on the remote host.

    **Use cases:** build, test, lint, git, package managers, dev servers, curl, etc.
    **Blocked:** rm, kill, shutdown, reboot, dd, mkfs, and other destructive commands.

    **Examples:**
    - Build: `run_command(command="make build")`
    - Test: `run_command(command="pytest -x tests/", timeout=120)`
    - Git: `run_command(command="git status && git log --oneline -5")`
    - Install: `run_command(command="pip install -e '.[dev]'")`
    - Chain: `run_command(command="cd src && grep -r 'TODO' . | wc -l")`

    **Output format:**
    ```
    [exit_code: 0]
    [stdout]
    ... (RTK-compressed if compact=true)
    [stderr]
    ...
    ```
    """
    # Safety check
    safety_error = _validate_command_safety(command)
    if safety_error:
        return safety_error

    # Validate working directory
    try:
        cwd = validate_path(working_dir)
        if not cwd.is_dir():
            return f"Error: Working directory '{working_dir}' is not a directory."
    except ValueError as e:
        return f"Error: {e}"

    # Cap timeout
    timeout = min(max(timeout, 1), 600)  # 1s to 10min

    try:
        _shell = _get_user_shell()  # env-independent: reads $SHELL then /etc/passwd
        
        # Smart RTK integration: try to rewrite the command to its RTK equivalent
        # e.g., "git status" -> "rtk git status" (70% savings)
        # RTK subcommands run the real command internally and compress the output.
        actual_command = command
        rtk_rewritten = False
        if compact:
            rewritten = _rtk_rewrite_command(command)
            if rewritten:
                actual_command = rewritten
                rtk_rewritten = True
        
        result = subprocess.run(
            actual_command,
            shell=True,
            executable=_shell,
            env=LOGIN_ENV,  # full login env: nvm, pyenv, pnpm, cargo, etc.
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # If RTK already handled compression via rewrite, skip post-processing.
        # Otherwise, fall back to rtk read for generic compression.
        rtk_warning = None
        if compact and stdout and not rtk_rewritten:
            stdout, rtk_warning = _rtk_compress_content(stdout)

        # Build output
        parts = [f"[exit_code: {result.returncode}]"]
        if rtk_warning:
            parts.append(f"[rtk: {rtk_warning}]")
        if stdout:
            parts.append(f"[stdout]\n{stdout}")
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        if not stdout and not stderr:
            parts.append("[no output]")

        return "\n".join(parts)

    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial = f"\n[partial stdout]\n{e.stdout[:2000]}"
        return f"Error: Command timed out after {timeout}s.{partial}"
    except Exception as e:
        return f"Error running command: {e}"