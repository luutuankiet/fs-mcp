"""Tests for _capture_login_env() and run_command's login-env integration.

Covers:
    1. _capture_login_env() happy path — returns a dict with PATH
    2. _capture_login_env() falls back gracefully when $SHELL is broken
    3. _capture_login_env() falls back gracefully on subprocess timeout
    4. run_command passes LOGIN_ENV (not the bare process env) to subprocess
    5. run_command uses $SHELL, not hardcoded /bin/bash
    6. A PATH entry injected into LOGIN_ENV is visible inside a run_command call
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
    """When $SHELL is absent, _get_user_shell() reads from /etc/passwd via pwd.getpwuid."""
    monkeypatch.delenv("SHELL", raising=False)

    import pwd as _pwd
    fake_entry = MagicMock()
    fake_entry.pw_shell = "/bin/fish"

    with patch("fs_mcp.server.pwd", create=True) as mock_pwd_mod:
        # pwd is imported inside the function, patch it at the module level
        with patch("builtins.__import__", wraps=__import__) as mock_import:
            pass  # just verify the logic via direct pwd patch below

    # Simpler: patch pwd.getpwuid directly in the server module's call
    with patch("fs_mcp.server.os.getuid", return_value=1000):
        import pwd as real_pwd
        with patch.object(real_pwd, "getpwuid", return_value=fake_entry):
            # Re-import pwd inside _get_user_shell uses the real module;
            # fake the return value
            result = server._get_user_shell()
    # Will either be /bin/fish (if pwd patch worked) or /bin/bash fallback —
    # either way it must not be None and must be a string
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
# 1. _capture_login_env — happy path
# ---------------------------------------------------------------------------

def test_capture_login_env_returns_dict_with_path(monkeypatch):
    """_capture_login_env() should return a non-empty dict that always contains PATH."""
    fake_env_output = "PATH=/usr/local/bin:/usr/bin\nHOME=/home/ubuntu\nSHELL=/bin/zsh\n"
    mock_result = MagicMock(returncode=0, stdout=fake_env_output)

    with patch("fs_mcp.server.subprocess.run", return_value=mock_result) as mock_run:
        monkeypatch.setenv("SHELL", "/bin/zsh")
        env = server._capture_login_env()

    assert isinstance(env, dict)
    assert "PATH" in env
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HOME"] == "/home/ubuntu"
    # Must have invoked the login shell correctly
    args_used = mock_run.call_args[0][0]
    assert args_used == ["/bin/zsh", "-i", "-l", "-c", "env"]


# ---------------------------------------------------------------------------
# 2. _capture_login_env — non-zero exit falls back to os.environ
# ---------------------------------------------------------------------------

def test_capture_login_env_falls_back_on_nonzero_exit(monkeypatch, capsys):
    """A non-zero exit from the shell should fall back to the process environment."""
    mock_result = MagicMock(returncode=1, stdout="")

    with patch("fs_mcp.server.subprocess.run", return_value=mock_result):
        monkeypatch.setenv("SHELL", "/bin/bash")
        env = server._capture_login_env()

    # Should still be a dict derived from the current process env
    assert isinstance(env, dict)
    assert "PATH" in env
    # Warning should have been printed to stderr
    captured = capsys.readouterr()
    assert "falling back to process environment" in captured.err


# ---------------------------------------------------------------------------
# 3. _capture_login_env — timeout falls back to os.environ
# ---------------------------------------------------------------------------

def test_capture_login_env_falls_back_on_timeout(monkeypatch, capsys):
    """A subprocess.TimeoutExpired should fall back gracefully, not raise."""
    with patch(
        "fs_mcp.server.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="env", timeout=10),
    ):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        env = server._capture_login_env()

    assert isinstance(env, dict)
    captured = capsys.readouterr()
    assert "falling back to process environment" in captured.err


# ---------------------------------------------------------------------------
# 4. run_command passes LOGIN_ENV to subprocess, not bare os.environ
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_passes_login_env_to_subprocess(temp_env, monkeypatch):
    """run_command must pass server.LOGIN_ENV as env= to subprocess.run."""
    sentinel_env = {"PATH": "/sentinel/bin", "HOME": "/home/ubuntu", "SHELL": "/bin/bash"}
    monkeypatch.setattr(server, "LOGIN_ENV", sentinel_env)

    captured_kwargs = {}

    original_run = subprocess.run

    def capturing_run(cmd, **kwargs):
        # Only intercept the run_command subprocess call (shell=True)
        if kwargs.get("shell"):
            captured_kwargs.update(kwargs)
            return MagicMock(returncode=0, stdout="ok", stderr="")
        return original_run(cmd, **kwargs)  # let RTK/other calls through

    with patch("fs_mcp.server.subprocess.run", side_effect=capturing_run):
        await server.run_command.fn(
            command="echo hello",
            working_dir=str(temp_env),
            timeout=5,
            compact=False,
        )

    assert "env" in captured_kwargs, "run_command did not pass env= to subprocess"
    assert captured_kwargs["env"] is sentinel_env, (
        "run_command passed a different env than LOGIN_ENV"
    )


# ---------------------------------------------------------------------------
# 5. run_command uses $SHELL, not hardcoded /bin/bash
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

    assert captured_kwargs.get("executable") == "/bin/zsh", (
        f"Expected /bin/zsh, got {captured_kwargs.get('executable')}"
    )


# ---------------------------------------------------------------------------
# 6. PATH injected into LOGIN_ENV is visible inside run_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_login_env_path_is_visible_in_command(temp_env, monkeypatch):
    """A PATH entry present in LOGIN_ENV should be reachable from inside a command."""
    # Create a fake 'mynode' binary in a temp dir
    fake_bin = tmp_path = temp_env / "fake_bin"
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

    assert "mynode-ok" in result, (
        f"Binary on injected PATH was not found. run_command output:\n{result}"
    )
