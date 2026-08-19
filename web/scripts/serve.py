"""Dev server for the web spike.

Plain `python -m http.server` almost works, but two details matter:
`.mjs` and `.wasm` must arrive with the right Content-Type or the module
worker refuses to load, and caching must be off or a rebuilt wheel will not
be picked up.

Binding to localhost is deliberate: `getUserMedia` requires a secure context,
and localhost is the only origin exempt from needing HTTPS.

    uv run web/scripts/serve.py

Nothing here is outside the standard library, so `python3 web/scripts/serve.py`
works too — the project environment is not needed to serve static files.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
from pathlib import Path

PORT = 8000
ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".wasm": "application/wasm",
        ".json": "application/json",
        ".whl": "application/octet-stream",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        if "200" not in (args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    # Threaded because the app fetches the 9 MB wasm, the stdlib archive and
    # the numpy wheel concurrently, and a single-threaded server serialises
    # them into a slow, misleading first load.
    daemon_threads = True

    # Without this the socket sits in TIME_WAIT after ctrl-c and the next
    # start fails with "Address already in use" for about thirty seconds —
    # which, during a restart-after-every-edit loop, is most of them.
    allow_reuse_address = True


if __name__ == "__main__":
    handler = functools.partial(Handler, directory=str(ROOT))
    with Server(("127.0.0.1", PORT), handler) as httpd:
        print(f"http://127.0.0.1:{PORT}/  (ctrl-c to stop)")
        httpd.serve_forever()
