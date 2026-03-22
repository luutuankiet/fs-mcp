"""Tests for _capture_login_env() and run_command's login-env integration.

Covers:
    1. _capture_login_env() returns a dict with PATH
    2. _capture_login_env() prepends discovered version manager dirs to PATH
    3. _capture_login_env() skips dirs already in PATH (no duplicates)
    4. _capture_login_env() skips non-existent dirs (no phantom entries)
    5. run_command passes LOGIN_ENV (not the bare process env) to subprocess
    6. run_command uses _get_user_shell(), not hardcoded /bin/bash
    7. A PATH entry injected into LOGIN_ENV is visible inside a run_command call
"""
import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest
from fs_mcp import server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_env(tmp_path):
    """Standard temp-dir fixture — mirrors the pattern in test_server.py."""
    server.initialize([str(tmp_path)], use_all_tools=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 0. _get_user_shell — resolution order
# ---------------------------------------------------------------------------

def test_get_user_shell_prefers_shell_env_var(monkeypatch):
    """$SHELL env var is used when present."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert server._get_user_shell() == "/bin/zsh"


def test_get_user_shell_falls_back_to_passwd_when_no_env(monkeypatch):
    """When $SHELL is absent, reads from /etc/passwd via pwd.getpwuid."""
    monkeypatch.delenv("SHELL", raising=False)
    import pwd as real_pwd
    fake_entry = MagicMock()
    fake_entry.pw_shell = "/bin/fish"
    with patch.object(real_pwd, "getpwuid", return_value=fake_entry):
        result = server._get_user_shell()
    assert isinstance(result, str)
    assert result.startswith("/")


def test_get_user_shell_falls_back_to_bash_if_all_fail(monkeypatch):
    """If $SHELL is absent and pwd raises, fall back to /bin/bash."""
    monkeypatch.delenv("SHELL", raising=False)
    import pwd as real_pwd
    with patch.object(real_pwd, "getpwuid", side_effect=KeyError("no entry")):
        result = server._get_user_shell()
    assert result == "/bin/bash"


# ---------------------------------------------------------------------------
# 1. _capture_login_env — returns dict with PATH
# ---------------------------------------------------------------------------

def test_capture_login_env_returns_dict_with_path():
    """_capture_login_env() must always return a dict containing PATH."""
    env = server._capture_login_env()
    assert isinstance(env, dict)
    assert "PATH" in env
    assert len(env["PATH"]) > 0


# ---------------------------------------------------------------------------
# 2. _capture_login_env — prepends discovered dirs
# ---------------------------------------------------------------------------

def test_capture_login_env_prepends_discovered_dirs(tmp_path, monkeypatch):
    """Existing dirs matching _VERSION_MANAGER_BIN_DIRS patterns are prepended to PATH."""
    fake_bin = tmp_path / ".cargo" / "bin"
    fake_bin.mkdir(parents=True)

    monkeypatch.setattr(server, "_VERSION_MANAGER_BIN_DIRS", ["{home}/.cargo/bin"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = server._capture_login_env()

    path_dirs = env["PATH"].split(":")
    assert str(fake_bin) in path_dirs
    assert path_dirs.index(str(fake_bin)) < path_dirs.index("/usr/bin")


# ---------------------------------------------------------------------------
# 3. _capture_login_env — no duplicate PATH entries
# ---------------------------------------------------------------------------

def test_capture_login_env_no_duplicate_path_entries(tmp_path, monkeypatch):
    """Dirs already in PATH must not be added again."""
    fake_bin = tmp_path / ".cargo" / "bin"
    fake_bin.mkdir(parents=True)

    monkeypatch.setattr(server, "_VERSION_MANAGER_BIN_DIRS", ["{home}/.cargo/bin"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{fake_bin}:/usr/bin")

    env = server._capture_login_env()

    path_dirs = env["PATH"].split(":")
    assert path_dirs.count(str(fake_bin)) == 1


# ---------------------------------------------------------------------------
# 4. _capture_login_env — skips non-existent dirs
# ---------------------------------------------------------------------------

def test_capture_login_env_skips_nonexistent_dirs(tmp_path, monkeypatch):
    """Dirs that don't exist on disk must not appear in PATH."""
    monkeypatch.setattr(server, "_VERSION_MANAGER_BIN_DIRS", ["{home}/.nonexistent/bin"])
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")

    env = server._capture_login_env()

    assert str(tmp_path / ".nonexistent" / "bin") not in env["PATH"]


# ---------------------------------------------------------------------------
# 5. run_command passes LOGIN_ENV to subprocess
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_passes_login_env_to_subprocess(temp_env, monkeypatch):
    """run_command must pass server.LOGIN_ENV as env= to subprocess.run."""
    sentinel_env = {"PATH": "/sentinel/bin", "HOME": "/home/ubuntu", "SHELL": "/bin/bash"}
    monkeypatch.setattr(server, "LOGIN_ENV", sentinel_env)

    captured_kwargs = {}
    original_run = subprocess.run

    def capturing_run(cmd, **kwargs):
        if kwargs.get("shell"):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="ok", stderr="")
        return original_run(cmd, **kwargs)

    with patch("fs_mcp.server.subprocess.run", side_effect=capturing_run):
        await server.run_command.fn(
            command="echo hello",
            working_dir=str(temp_env),
            timeout=5,
            compact=False,
        )

    assert "env" in captured_kwargs, "run_command did not pass env= to subprocess"
    assert captured_kwargs["env"] is sentinel_env


# ---------------------------------------------------------------------------
# 6. run_command uses _get_user_shell(), not hardcoded /bin/bash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_uses_shell_env_var(temp_env, monkeypatch):
    """run_command should honour $SHELL for executable=, not hardcode /bin/bash."""
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(server, "LOGIN_ENV", dict(os.environ))

    captured_kwargs = {}
    original_run = subprocess.run

    def capturing_run(cmd, **kwargs):
        if kwargs.get("shell"):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="ok", stderr="")
        return original_run(cmd, **kwargs)

    with patch("fs_mcp.server.subprocess.run", side_effect=capturing_run):
        await server.run_command.fn(
            command="echo hello",
            working_dir=str(temp_env),
            timeout=5,
            compact=False,
        )

    assert captured_kwargs.get("executable") == "/bin/zsh"


# ---------------------------------------------------------------------------
# 7. PATH injected into LOGIN_ENV is visible inside run_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_login_env_path_is_visible_in_command(temp_env, monkeypatch):
    """A binary on a PATH entry in LOGIN_ENV must be callable from run_command."""
    fake_bin = temp_env / "fake_bin"
    fake_bin.mkdir()
    fake_exe = fake_bin / "mynode"
    fake_exe.write_text("#!/bin/sh\necho mynode-ok\n")
    fake_exe.chmod(0o755)

    injected_path = f"{fake_bin}:/usr/bin:/bin"
    login_env = {**os.environ, "PATH": injected_path}
    monkeypatch.setattr(server, "LOGIN_ENV", login_env)

    result = await server.run_command.fn(
        command="mynode",
        working_dir=str(temp_env),
        timeout=5,
        compact=False,
    )

    assert "mynode-ok" in result, f"Binary on injected PATH not found:\n{result}"
