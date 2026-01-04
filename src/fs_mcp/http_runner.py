import argparse
from fs_mcp import server

def main():
    """
    This is a dedicated entry point for running the FastMCP server in HTTP mode.
    It's designed to be called as a subprocess from the main CLI.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("dirs", nargs="*")
    args = parser.parse_args()
    
    try:
        server.initialize(args.dirs)
        server.mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port
        )
    except KeyboardInterrupt:
        pass # The main process will handle termination.
    except Exception as e:
        print(f"HTTP runner failed: {e}")

if __name__ == "__main__":
    main()