#!/usr/bin/env python3
"""Dependency check script for Docker test builds."""
import platform
from fs_mcp.utils import check_rtk, check_ripgrep, check_jq, check_yq

print(f"=== fs-mcp Dep Check ({platform.machine()}) ===")
for name, fn in [("rg", check_ripgrep), ("jq", check_jq), ("yq", check_yq), ("rtk", check_rtk)]:
    ok, msg = fn()
    status = "OK" if ok else "SKIP"
    print(f"  {status}: {name} - {msg}")
print("=== Done ===")
