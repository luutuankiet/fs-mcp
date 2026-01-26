import shutil
import platform
import distro

def check_ripgrep():
    """
    Checks if ripgrep is installed and returns platform-specific installation instructions if not.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating if ripgrep is installed,
                          and a message with installation instructions if it's not.
    """
    if shutil.which('rg'):
        return True, "ripgrep is installed."

    system = platform.system()
    install_cmd = ""

    if system == 'Darwin':
        install_cmd = "brew install ripgrep"
    elif system == 'Windows':
        install_cmd = "choco install ripgrep"
    elif system == 'Linux':
        dist = distro.id()
        if dist in ['ubuntu', 'debian']:
            install_cmd = "sudo apt-get install ripgrep"
        elif dist in ['fedora', 'centos', 'rhel']:
            install_cmd = "sudo dnf install ripgrep"
        else:
            install_cmd = "Please install ripgrep using your system's package manager."
    else:
        install_cmd = "Could not determine OS. Please install ripgrep manually."

    message = f"Warning: ripgrep is not installed. The 'grep_content' tool will be disabled. Please install it with: {install_cmd}"
    return False, message

