"""Local preview: build, serve, and rebuild whenever a source file or note changes.

The server answers only this Mac (loopback) and the networks in `allow`, e.g. a
WireGuard subnet, whichever address it listens on.
"""

from __future__ import annotations

import functools
import http.server
import ipaddress
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .config import ROOT

WATCHED = ["templates", "static", "content", "data", "sitegen", "site.yaml"]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # only report problems
        if len(args) > 1 and str(args[1])[:1] in "45":
            super().log_message(fmt, *args)


def allowed_server(allow: Sequence[str]) -> type[http.server.ThreadingHTTPServer]:
    networks = [ipaddress.ip_network(n, strict=False) for n in allow]

    class Server(http.server.ThreadingHTTPServer):
        def verify_request(self, request, client_address) -> bool:
            ip = ipaddress.ip_address(client_address[0])
            return ip.is_loopback or any(ip in net for net in networks)

    return Server


def snapshot(paths: list[Path]) -> dict[Path, float]:
    state = {}
    for base in paths:
        if base.is_file():
            state[base] = base.stat().st_mtime
        elif base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and ".obsidian" not in p.parts and "__pycache__" not in p.parts:
                    state[p] = p.stat().st_mtime
    return state


def watch(rebuild: Callable[[], Path], paths: list[Path]) -> None:
    before = snapshot(paths)
    while True:
        time.sleep(0.8)
        now = snapshot(paths)
        if now == before:
            continue
        changed = {p for p in now.keys() | before.keys() if now.get(p) != before.get(p)}
        before = now
        if any(p.suffix == ".py" for p in changed):
            print("Python code changed: restart the server to pick it up.")
        started = time.perf_counter()
        try:
            rebuild()
            print(f"rebuilt in {(time.perf_counter() - started) * 1000:.0f} ms")
        except SystemExit as exc:
            print(f"build stopped: {exc}")
        except Exception as exc:  # keep serving the last good build
            print(f"build failed: {exc!r}")


def serve(rebuild: Callable[[], Path], archive: Path | None, port: int,
          hosts: Sequence[str] = ("127.0.0.1",), allow: Sequence[str] = (), strict: bool = False) -> None:
    out = rebuild()
    threading.Thread(target=watch, args=(rebuild, [ROOT / w for w in WATCHED] + ([archive] if archive else [])),
                     daemon=True).start()
    handler = functools.partial(QuietHandler, directory=str(out))
    Server = allowed_server(allow)
    servers = []
    for host in hosts:
        try:
            servers.append(Server((host, port), handler))
            print(f"serving {out.name} at http://{host}:{port}")
        except OSError as exc:  # e.g. the WireGuard tunnel is down
            print(f"can't listen on {host}:{port} ({exc.strerror})")
    if not servers or (strict and len(servers) < len(hosts)):
        raise SystemExit("Couldn't listen on every address; exiting so launchd can retry.")
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
