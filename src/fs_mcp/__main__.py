# src/fs_mcp/__main__.py

import argparse
import sys
import subprocess
import time
from pathlib import Path
from importlib import metadata
import toml
from pyfiglet import Figlet

try:
    # Use importlib.metadata to find the version of the installed package
    __version__ = metadata.version("fs-mcp")
except metadata.PackageNotFoundError:
    # Fallback for when the package is not installed, e.g., in development
    try:
        pyproject_path = Path(__file__).parent.parent.parent / 'pyproject.toml'
        with open(pyproject_path, 'r') as f:
            data = toml.load(f)
            __version__ = data['project']['version']
    except (ImportError, FileNotFoundError, KeyError):
        __version__ = "unknown"

def main():
    f = Figlet(font='slant')
    banner = f.renderText('fs-mcp')
    print(banner)
    print(f"version {__version__}")
    parser = argparse.ArgumentParser(
        description="fs-mcp server. By default, runs both UI and HTTP servers.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # UI flags - now inverted to disable the default
    ui_group = parser.add_argument_group('UI Options')
    ui_group.add_argument("--no-ui", action="store_false", dest="run_ui", help="Do not launch the Streamlit Web UI.")
    ui_group.add_argument("--host", default="0.0.0.0", help="Host for the Streamlit UI.")
    ui_group.add_argument("--port", default="8123", type=int, help="Port for the Streamlit UI.")
    
    # Background HTTP server flags - now inverted
    http_group = parser.add_argument_group('HTTP Server Options')
    http_group.add_argument("--no-http", action="store_false", dest="run_http", help="Do not run a background HTTP MCP server.")
    http_group.add_argument("--http-host", default="0.0.0.0", help="Host for the background HTTP server.")
    http_group.add_argument("--http-port", type=int, default=8124, help="Port for the background HTTP server.")

    # Common args
    parser.add_argument("dirs", nargs="*", help="Allowed directories (applies to all server modes).")
    
    args, unknown = parser.parse_known_args()
    dirs = args.dirs or [str(Path.cwd())]

    http_process = None
    try:
        # --- Start Background HTTP Server if requested ---
        if args.run_http:
            # Command to run our dedicated HTTP runner script
            http_cmd = [
                sys.executable, "-m", "fs_mcp.http_runner",
                "--host", args.http_host,
                "--port", str(args.http_port),
                *dirs
            ]
            print(f"🚀 Launching background HTTP MCP server process on http://{args.http_host}:{args.http_port}", file=sys.stderr)
            
            # Use Popen to start the process without blocking.
            # We pipe stdout/stderr so they don't clutter the main console unless there's an error.
            http_process = subprocess.Popen(http_cmd, stdout=sys.stderr, stderr=sys.stderr)
            
            # Give it a moment to start up and check for instant failure.
            time.sleep(2) 
            if http_process.poll() is not None:
                print("❌ Background HTTP server failed to start. Check logs.", file=sys.stderr)
                sys.exit(1)

        # --- Start Foreground Application (UI or wait) ---
        if args.run_ui:
            current_dir = Path(__file__).parent
            ui_path = (current_dir / "web_ui.py").resolve()
            if not ui_path.exists():
                raise FileNotFoundError(f"Could not find web_ui.py at {ui_path}")
            
            ui_cmd = [
                sys.executable, "-m", "streamlit", "run", str(ui_path),
                "--server.address", args.host,
                "--server.port", str(args.port),
                "--", *[str(Path(d).resolve()) for d in dirs]
            ]
            print(f"🚀 Launching UI on http://{args.host}:{args.port}", file=sys.stderr)
            # This is a blocking call. The script waits here until Streamlit exits.
            subprocess.run(ui_cmd)

        elif args.run_http and http_process:
            # If ONLY the http server is running, we just need to wait.
            print("Background HTTP server is running. Press Ctrl+C to stop.", file=sys.stderr)
            http_process.wait()
            
        if not args.run_ui and not args.run_http:
            # Default: run the original stdio server. This should be a direct import.
            from fs_mcp import server
            print("🚀 Launching Stdio MCP server", file=sys.stderr)
            server.initialize(dirs)
            server.mcp.run()

    except KeyboardInterrupt:
        print("\nCaught interrupt, shutting down...", file=sys.stderr)
    
    finally:
        # This block is GUARANTEED to run, ensuring the background process is cleaned up.
        if http_process:
            print("Terminating background HTTP server...", file=sys.stderr)
            http_process.terminate()  # Sends SIGTERM for a graceful shutdown
            try:
                # Wait up to 5 seconds for it to shut down
                http_process.wait(timeout=5)
                print("Background server stopped gracefully.", file=sys.stderr)
            except subprocess.TimeoutExpired:
                # If it's stuck, force kill it.
                print("Server did not terminate gracefully, killing.", file=sys.stderr)
                http_process.kill()

if __name__ == "__main__":
    main()