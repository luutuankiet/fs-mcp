import shutil
import platform
import sys
import distro


def _get_platform_info() -> tuple[str, str]:
    """Get OS and distribution info."""
    system = platform.system()
    dist = ""
    if system == 'Linux':
        dist = distro.id()
    return system, dist


def _format_install_instructions(tool: str, system: str, dist: str) -> str:
    """Generate platform-specific install instructions for a tool."""
    
    instructions = {
        'ripgrep': {
            'Darwin': 'brew install ripgrep',
            'Windows': 'choco install ripgrep',
            'Linux': {
                'ubuntu': 'sudo apt-get install ripgrep',
                'debian': 'sudo apt-get install ripgrep',
                'fedora': 'sudo dnf install ripgrep',
                'centos': 'sudo dnf install ripgrep',
                'rhel': 'sudo dnf install ripgrep',
                'arch': 'sudo pacman -S ripgrep',
                'default': 'Install via package manager or: cargo install ripgrep',
            },
        },
        'jq': {
            'Darwin': 'brew install jq',
            'Windows': 'choco install jq',
            'Linux': {
                'ubuntu': 'sudo apt-get install jq',
                'debian': 'sudo apt-get install jq',
                'fedora': 'sudo dnf install jq',
                'centos': 'sudo dnf install jq',
                'rhel': 'sudo dnf install jq',
                'arch': 'sudo pacman -S jq',
                'default': 'Install via package manager or download from https://jqlang.github.io/jq/download/',
            },
        },
        'yq': {
            'Darwin': 'brew install yq',
            'Windows': 'choco install yq',
            'Linux': {
                'default': 'brew install yq  # or download from https://github.com/mikefarah/yq/releases',
            },
        },
        'rtk': {
            'Darwin': 'brew install rtk',
            'Windows': 'cargo install --git https://github.com/rtk-ai/rtk',
            'Linux': {
                'default': 'brew install rtk  # or: cargo install --git https://github.com/rtk-ai/rtk',
            },
        },
    }
    
    tool_instructions = instructions.get(tool, {})
    
    if system == 'Linux':
        linux_instructions = tool_instructions.get('Linux', {})
        return linux_instructions.get(dist, linux_instructions.get('default', f'Install {tool} manually'))
    
    return tool_instructions.get(system, f'Install {tool} manually')


def check_ripgrep() -> tuple[bool, str]:
    """Check if ripgrep is installed."""
    if shutil.which('rg'):
        return True, "ripgrep is installed."
    
    system, dist = _get_platform_info()
    install_cmd = _format_install_instructions('ripgrep', system, dist)
    return False, install_cmd


def check_jq() -> tuple[bool, str]:
    """Check if jq is installed."""
    if shutil.which('jq'):
        return True, "jq is installed."
    
    system, dist = _get_platform_info()
    install_cmd = _format_install_instructions('jq', system, dist)
    return False, install_cmd


def check_yq() -> tuple[bool, str]:
    """Check if yq is installed."""
    if shutil.which('yq'):
        return True, "yq is installed."
    
    system, dist = _get_platform_info()
    install_cmd = _format_install_instructions('yq', system, dist)
    return False, install_cmd


def check_rtk() -> tuple[bool, str]:
    """Check if RTK (Rust Token Killer) is installed."""
    if shutil.which('rtk'):
        return True, "rtk is installed."
    
    system, dist = _get_platform_info()
    install_cmd = _format_install_instructions('rtk', system, dist)
    return False, install_cmd


def check_required_dependencies() -> None:
    """
    Check all required dependencies and exit with clear instructions if any are missing.
    
    Required: ripgrep (rg), jq, yq
    """
    missing = []
    
    rg_ok, rg_install = check_ripgrep()
    if not rg_ok:
        missing.append(('ripgrep (rg)', 'grep_content', rg_install))
    
    jq_ok, jq_install = check_jq()
    if not jq_ok:
        missing.append(('jq', 'query_json', jq_install))
    
    yq_ok, yq_install = check_yq()
    if not yq_ok:
        missing.append(('yq', 'query_yaml (YAML/XML/TOML/CSV/TSV/INI/HCL)', yq_install))
    
    rtk_ok, rtk_install = check_rtk()
    if not rtk_ok:
        missing.append(('rtk', 'read_files/grep_content (token-efficient mode)', rtk_install))
    
    if missing:
        _print_dependency_error(missing)
        sys.exit(1)


def _print_dependency_error(missing: list[tuple[str, str, str]]) -> None:
    """Print a clear, formatted error message for missing dependencies."""
    
    # Box drawing
    print("\n" + "=" * 70)
    print("  ❌ MISSING REQUIRED DEPENDENCIES")
    print("=" * 70)
    print()
    print("  fs-mcp requires the following CLI tools to be installed:")
    print()
    
    for tool, powers, install_cmd in missing:
        print(f"  ┌─ {tool}")
        print(f"  │  Powers: {powers}")
        print(f"  │  Install: {install_cmd}")
        print(f"  └" + "─" * 50)
        print()
    
    # One-liner for common case
    system, dist = _get_platform_info()
    if system == 'Darwin':
        tools = ' '.join(t[0].split()[0].lower() for t in missing)
        print(f"  💡 Quick fix (macOS): brew install {tools}")
    elif system == 'Linux':
        if dist in ['ubuntu', 'debian']:
            # ripgrep binary is 'rg' but package is 'ripgrep'
            tools = ' '.join('ripgrep' if 'ripgrep' in t[0] else t[0].split()[0].lower() for t in missing)
            print(f"  💡 Quick fix (apt): sudo apt-get install {tools}")
    
    print()
    print("=" * 70)
    print()