# Discovery: Ripgrep Integration

**Level:** 2 - Standard Research

## Objective

Determine the best approach to:
1.  Detect if `ripgrep` (`rg`) is installed and available in the system's `PATH`.
2.  Provide platform-specific installation instructions if it's missing.

## Findings

### 1. Detecting Ripgrep

The standard Python library `shutil` provides a function `shutil.which('rg')` which is the most reliable and straightforward way to check for the existence of an executable in the system's `PATH`. This function is available in Python 3.3+ and is the recommended approach.

### 2. Platform-Specific Installation Instructions

We can use a combination of Python's built-in `platform` module and the `distro` library (which is already a dependency) to identify the operating system and provide tailored installation instructions.

-   **macOS:** `platform.system() == 'Darwin'`. The recommended installation method is Homebrew: `brew install ripgrep`.
-   **Windows:** `platform.system() == 'Windows'`. The recommended installation method is Chocolatey: `choco install ripgrep`.
-   **Linux:** Use the `distro` library.
    -   `distro.id() == 'ubuntu'` or `'debian'`: `sudo apt-get install ripgrep`
    -   `distro.id() == 'fedora'` or `'centos'` or `'rhel'`: `sudo dnf install ripgrep`
    -   For other distributions, we can provide a generic message pointing to the official `ripgrep` repository.

## Decision

-   Use `shutil.which('rg')` to check for `ripgrep`.
-   Use `platform.system()` for macOS and Windows detection.
-   Use `distro.id()` for Linux distribution detection.
-   A helper function will be created to encapsulate this logic and return the appropriate installation command.
