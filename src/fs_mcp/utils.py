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
            'Darwin': 'brew install ripgrep  # https://github.com/BurntSushi/ripgrep#installation',
            'Windows': 'choco install ripgrep  # or: winget install BurntSushi.ripgrep  # https://github.com/BurntSushi/ripgrep#installation',
            'Linux': {
                'ubuntu': 'sudo apt-get install ripgrep',
                'debian': 'sudo apt-get install ripgrep',
                'fedora': 'sudo dnf install ripgrep',
                'centos': 'sudo dnf install ripgrep',
                'rhel': 'sudo dnf install ripgrep',
                'arch': 'sudo pacman -S ripgrep',
                'alpine': 'sudo apk add ripgrep',
                'opensuse': 'sudo zypper install ripgrep',
                'default': 'Install via package manager or: cargo install ripgrep  # https://github.com/BurntSushi/ripgrep#installation',
            },
        },
        'jq': {
            'Darwin': 'brew install jq  # https://jqlang.github.io/jq/download/',
            'Windows': 'choco install jq  # or: winget install jqlang.jq  # https://jqlang.github.io/jq/download/',
            'Linux': {
                'ubuntu': 'sudo apt-get install jq',
                'debian': 'sudo apt-get install jq',
                'fedora': 'sudo dnf install jq',
                'centos': 'sudo dnf install jq',
                'rhel': 'sudo dnf install jq',
                'arch': 'sudo pacman -S jq',
                'alpine': 'sudo apk add jq',
                'opensuse': 'sudo zypper install jq',
                'default': 'Install via package manager or download from https://jqlang.github.io/jq/download/',
            },
        },
        'yq': {
            'Darwin': 'brew install yq  # https://github.com/mikefarah/yq#install',
            'Windows': 'choco install yq  # or: winget install MikeFarah.yq  # https://github.com/mikefarah/yq#install',
            'Linux': {
                'ubuntu': 'sudo snap install yq  # or: sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq',
                'debian': 'sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq',
                'fedora': 'sudo dnf install yq  # or: sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq',
                'centos': 'sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq',
                'rhel': 'sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq',
                'arch': 'sudo pacman -S go-yq  # https://archlinux.org/packages/extra/x86_64/go-yq/',
                'alpine': 'sudo apk add yq',
                'default': 'Download binary from https://github.com/mikefarah/yq/releases/latest  # or: go install github.com/mikefarah/yq/v4@latest',
            },
        },
        'rtk': {
            'Darwin': 'brew install rtk-ai/tap/rtk  # https://github.com/rtk-ai/rtk#installation',
            'Windows': 'cargo install --git https://github.com/rtk-ai/rtk  # https://github.com/rtk-ai/rtk#installation',
            'Linux': {
                'default': 'cargo install --git https://github.com/rtk-ai/rtk  # or: brew install rtk-ai/tap/rtk  # https://github.com/rtk-ai/rtk#installation',
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
        missing.append(('jq', 'query_jq', jq_install))
    
    yq_ok, yq_install = check_yq()
    if not yq_ok:
        missing.append(('yq', 'query_yq (YAML/XML/TOML/CSV/TSV/INI/HCL)', yq_install))
    
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
    # Tools available in standard package managers vs those needing manual install
    apt_available = {'ripgrep', 'jq'}
    brew_packages = {'ripgrep': 'ripgrep', 'jq': 'jq', 'yq': 'yq', 'rtk': 'rtk-ai/tap/rtk'}

    if system == 'Darwin':
        tools = ' '.join(brew_packages.get(t[0].split()[0].lower(), t[0].split()[0].lower()) for t in missing)
        print(f"  💡 Quick fix (macOS): brew install {tools}")
    elif system == 'Linux':
        if dist in ['ubuntu', 'debian']:
            apt_tools = [t for t in missing if t[0].split()[0].lower().replace('(rg)', '').strip() in apt_available or 'ripgrep' in t[0]]
            other_tools = [t for t in missing if t not in apt_tools]
            if apt_tools:
                pkg_names = ' '.join('ripgrep' if 'ripgrep' in t[0] else t[0].split()[0].lower() for t in apt_tools)
                print(f"  💡 Quick fix (apt): sudo apt-get install {pkg_names}")
            if other_tools:
                for t in other_tools:
                    print(f"  💡 {t[0]}: see install command above (not available via apt)")
    
    print()
    print("=" * 70)
    print()