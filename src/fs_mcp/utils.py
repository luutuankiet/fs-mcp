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


def check_jq():
    """
    Checks if jq is installed and returns platform-specific installation instructions if not.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating if jq is installed,
                          and a message with installation instructions if it's not.
    """
    if shutil.which('jq'):
        return True, "jq is installed."

    system = platform.system()
    install_cmd = ""

    if system == 'Darwin':
        install_cmd = "brew install jq"
    elif system == 'Windows':
        install_cmd = "choco install jq"
    elif system == 'Linux':
        dist = distro.id()
        if dist in ['ubuntu', 'debian']:
            install_cmd = "sudo apt-get install jq"
        elif dist in ['fedora', 'centos', 'rhel']:
            install_cmd = "sudo dnf install jq"
        else:
            install_cmd = "Please install jq using your system's package manager."
    else:
        install_cmd = "Could not determine OS. Please install jq manually."

    message = f"Warning: jq is not installed. The 'query_json' tool will be disabled. Please install it with: {install_cmd}"
    return False, message


def check_yq():
    """
    Checks if yq is installed and returns platform-specific installation instructions if not.

    Returns:
        tuple[bool, str]: A tuple containing a boolean indicating if yq is installed,
                          and a message with installation instructions if it's not.
    """
    if shutil.which('yq'):
        return True, "yq is installed."

    system = platform.system()
    install_cmd = ""

    if system == 'Darwin':
        install_cmd = "brew install yq"
    elif system == 'Windows':
        install_cmd = "choco install yq"
    elif system == 'Linux':
        install_cmd = "Download from https://github.com/mikefarah/yq/releases or use 'brew install yq' if brew is available"
    else:
        install_cmd = "Could not determine OS. Please install yq manually."

    message = f"Warning: yq is not installed. The 'query_yaml' tool will be disabled. Please install it with: {install_cmd}"
    return False, message


