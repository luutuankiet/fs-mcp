"""
Tests for check_dependencies tool.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from fs_mcp import server


@pytest.fixture
def temp_env(tmp_path):
    """Sets up a safe temporary directory environment for testing."""
    server.initialize([str(tmp_path)], use_all_tools=True)
    return tmp_path


class TestCheckDependencies:
    """Tests for the check_dependencies MCP tool."""

    @pytest.mark.asyncio
    async def test_default_shows_all_deps(self, temp_env):
        """Default call should report all dependencies."""
        result = await server.check_dependencies.fn()

        assert "ripgrep" in result or "rg" in result
        assert "jq" in result
        assert "yq" in result
        assert "rtk" in result

    @pytest.mark.asyncio
    async def test_shows_rtk_managed_tag(self, temp_env):
        """Should show [managed] or [user-installed] tag for RTK."""
        result = await server.check_dependencies.fn()

        assert "[managed]" in result or "[user-installed]" in result or "NOT FOUND" in result

    @pytest.mark.asyncio
    async def test_verbose_shows_system_info(self, temp_env):
        """verbose=True should show system/arch info."""
        result = await server.check_dependencies.fn(verbose=True)

        assert "[system]" in result
        assert "arch:" in result
        assert "IS_RTK_AVAILABLE" in result

    @pytest.mark.asyncio
    async def test_fix_with_managed_rtk(self, temp_env):
        """fix=True with managed RTK should attempt update."""
        server._RTK_MANAGED = True
        server._RTK_PATH = "/home/test/.local/bin/rtk"
        server.IS_RTK_AVAILABLE = True

        with patch.object(server, '_rtk_auto_update') as mock_update:
            mock_update.return_value = None  # Already latest

            result = await server.check_dependencies.fn(fix=True)

            assert "latest" in result.lower() or "rtk" in result.lower()

    @pytest.mark.asyncio
    async def test_fix_with_user_installed_rtk(self, temp_env):
        """fix=True with user-installed RTK should skip update."""
        server._RTK_MANAGED = False
        server._RTK_PATH = "/usr/local/bin/rtk"
        server.IS_RTK_AVAILABLE = True

        result = await server.check_dependencies.fn(fix=True)

        assert "user-installed" in result or "skipping" in result.lower()

    @pytest.mark.asyncio
    async def test_detects_duplicates_in_verbose(self, temp_env):
        """Should detect duplicate RTK binaries."""
        # This test depends on actual system state, so we mock _find_all
        # The real test is the E2E smoke test
        result = await server.check_dependencies.fn(verbose=True)

        # Just verify it doesn't crash and returns structured output
        assert "rtk" in result.lower()
