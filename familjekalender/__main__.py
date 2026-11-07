"""Starta familjekalendern: python -m familjekalender [--port 8080]"""

from __future__ import annotations

import argparse
import logging
import socket

from .app import create_app


def _lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Familjekalender")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = nåbar från mobiler på hemnätet")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app()

    print(f"\n  Familjekalendern körs!\n  På den här datorn:  http://localhost:{args.port}")
    ip = _lan_ip()
    if ip and args.host == "0.0.0.0":
        print(f"  På mobilen (samma wifi):  http://{ip}:{args.port}")
    print("  Stoppa med Ctrl+C\n")

    try:
        from waitress import serve
    except ImportError:
        app.run(host=args.host, port=args.port, threaded=True)
    else:
        serve(app, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    main()
