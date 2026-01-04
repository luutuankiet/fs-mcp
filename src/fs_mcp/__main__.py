import argparse
import sys
import subprocess
from pathlib import Path
from fs_mcp import server

def main():
    parser = argparse.ArgumentParser(description="fs-mcp server")
    parser.add_argument("--ui", action="store_true", help="Launch Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="UI Host")
    parser.add_argument("--port", default="8501", help="UI Port")
    parser.add_argument("dirs", nargs="*", help="Allowed directories")
    
    # Parse known args to allow Streamlit to handle its own flags if needed
    args, unknown = parser.parse_known_args()
    
    # Initialize Core Logic for Stdio mode
    dirs = args.dirs or [str(Path.cwd())]
    try:
        server.initialize(dirs)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.ui:
        # Launch Streamlit as a subprocess
        # FIX: Find the file without importing it
        current_dir = Path(__file__).parent
        ui_path = (current_dir / "web_ui.py").resolve()
        
        if not ui_path.exists():
            print(f"Error: Could not find web_ui.py at {ui_path}", file=sys.stderr)
            sys.exit(1)
            
        cmd = [
            sys.executable, "-m", "streamlit", "run", str(ui_path),
            "--server.address", args.host,
            "--server.port", args.port,
            "--",  # Separator: args after this are passed to the script
            *dirs
        ]
        print(f"🚀 Launching UI on http://{args.host}:{args.port}", file=sys.stderr)
        # Use simple run, Streamlit handles the rest
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
    else:
        # Run Standard MCP Server
        server.mcp.run()

if __name__ == "__main__":
    main()