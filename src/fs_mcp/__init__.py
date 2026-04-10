from importlib import metadata
from pathlib import Path

try:
    __version__ = metadata.version("fs-mcp")
except metadata.PackageNotFoundError:
    try:
        import toml
        pyproject_path = Path(__file__).parent.parent.parent / 'pyproject.toml'
        with open(pyproject_path, 'r') as f:
            __version__ = toml.load(f)['project']['version']
    except Exception:
        __version__ = "unknown"