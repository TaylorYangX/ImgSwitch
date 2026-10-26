"""ImgSwitch entry point.

    python main.py                              stdio MCP server (what Claude Code launches); binds no ports
    python main.py --gui [--port 8765]          configuration dashboard in a browser
    python main.py --gui --app --port N         backend for the desktop app (started by the app itself)
    python main.py --transport streamable-http  persistent MCP server over HTTP (or --transport sse)
"""

import argparse
import logging
import os
import threading
import time

from imgswitch.log import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Image generation MCP server with a configuration dashboard.")
    parser.add_argument("--gui", action="store_true", help="run the configuration dashboard instead of the MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address for --gui or HTTP transports")
    parser.add_argument("--port", type=int, help="port for --gui (default 8765) or HTTP transports (default 8000)")
    parser.add_argument("--app", action="store_true", help="with --gui: serve the desktop app (allows its origin)")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    if args.gui:
        # Imported lazily so stdio mode never loads the web stack.
        import uvicorn

        from imgswitch.gui.app import LOCAL_HOSTS, create_app

        # Host-header checking only makes sense when bound to loopback.
        app = create_app(LOCAL_HOSTS if args.host in LOCAL_HOSTS else None, app_mode=args.app)
        if args.app:
            _exit_with_parent()
        port = args.port or 8765
        logging.getLogger("imgswitch").info("Dashboard at http://%s:%d", args.host, port)
        uvicorn.run(app, host=args.host, port=port, log_level="info")
        return

    from imgswitch.server import mcp

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run(args.transport, host=args.host, port=args.port or 8000)


def _exit_with_parent() -> None:
    """The desktop app owns this process; don't outlive it if the app is killed or crashes."""
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


if __name__ == "__main__":
    main()
