"""HomeHub: a Ring + Blink dashboard for an Amazon Fire tablet.

Run on a computer or Raspberry Pi on your home network:

    python -m homehub.main                      # demo devices
    HOMEHUB_PROVIDERS=ring,blink python -m homehub.main
    python -m homehub.main --setup ring         # one-time Ring sign-in
    python -m homehub.main --setup blink        # one-time Blink sign-in

Then open http://<computer-ip>:8080 in Silk or a kiosk browser on the tablet.
Uses only the standard library; Ring and Blink need their own packages.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .config import Config
from .hub import Hub
from .providers.base import Provider, ProviderError
from .providers.demo import DemoProvider

log = logging.getLogger("homehub")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PIN_ACTIONS = {"arm", "disarm"}
MAX_BODY = 4096


def build_providers(cfg: Config) -> List[Provider]:
    out: List[Provider] = []
    for name in cfg.providers:
        if name == "demo":
            out.append(DemoProvider())
        elif name == "ring":
            from .providers.ring import RingProvider
            out.append(RingProvider(cfg.ring_token_file))
        elif name == "blink":
            from .providers.blink import BlinkProvider
            out.append(BlinkProvider(cfg.blink_cred_file))
        else:
            raise SystemExit(f"Unknown provider '{name}' (use demo, ring or blink)")
    return out


def make_handler(hub: Hub, cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HomeHub/0.1"

        def log_message(self, fmt, *args):  # route through logging
            log.debug("%s - %s", self.address_string(), fmt % args)

        # -- helpers ------------------------------------------------------
        def _send(self, status: int, body: bytes, ctype: str, cache: bool = False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=300" if cache else "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _error(self, status: int, msg: str):
            self._json({"error": msg}, status)

        # -- routes -------------------------------------------------------
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path
            q = parse_qs(url.query)
            try:
                if path in ("/", "/index.html"):
                    return self._static("index.html")
                if path.startswith("/static/"):
                    return self._static(path[len("/static/"):])
                if path == "/api/status":
                    st = hub.status()
                    st["pin_required"] = bool(cfg.pin)
                    return self._json(st)
                if path == "/api/devices":
                    force = q.get("refresh", ["0"])[0] == "1"
                    return self._json({"devices": [d.to_dict() for d in hub.devices(force)],
                                       "errors": hub.errors})
                if path == "/api/events":
                    limit = max(1, min(100, int(q.get("limit", ["20"])[0])))
                    return self._json({"events": [e.to_dict() for e in hub.events(limit)]})
                if path.startswith("/api/snapshot/"):
                    img = hub.snapshot(unquote(path[len("/api/snapshot/"):]))
                    if not img:
                        return self._error(404, "No snapshot")
                    return self._send(200, img, "image/jpeg", cache=True)
                return self._error(404, "Not found")
            except ProviderError as e:
                return self._error(400, str(e))
            except ValueError:
                return self._error(400, "Bad request")
            except Exception as e:
                log.exception("GET %s failed", path)
                return self._error(502, f"Device service error: {e}")

        def do_POST(self):
            path = urlparse(self.path).path
            prefix, suffix = "/api/devices/", "/action"
            if not (path.startswith(prefix) and path.endswith(suffix)):
                return self._error(404, "Not found")
            device_id = unquote(path[len(prefix):-len(suffix)])
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._error(413, "Body too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                action = str(body.get("action", ""))
            except (ValueError, AttributeError):
                return self._error(400, "Expected JSON body with an 'action'")
            if not action:
                return self._error(400, "Missing 'action'")
            if cfg.pin and action in PIN_ACTIONS:
                if not hmac.compare_digest(str(body.get("pin", "")), cfg.pin):
                    return self._error(403, "Wrong PIN")
            try:
                hub.action(device_id, action)
            except ProviderError as e:
                return self._error(400, str(e))
            except Exception as e:
                log.exception("Action %s on %s failed", action, device_id)
                return self._error(502, f"Device service error: {e}")
            return self._json({"ok": True})

        def _static(self, rel: str):
            full = os.path.realpath(os.path.join(STATIC_DIR, rel))
            if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
                return self._error(404, "Not found")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)

    return Handler


def make_server(hub: Hub, cfg: Config) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((cfg.host, cfg.port), make_handler(hub, cfg))
    srv.daemon_threads = True
    return srv


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="HomeHub dashboard server")
    ap.add_argument("--setup", choices=["ring", "blink"], help="sign in once and save a token")
    ap.add_argument("--port", type=int)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env()
    if args.port:
        cfg.port = args.port

    if args.setup:
        cfg.providers = [args.setup]
        build_providers(cfg)[0].setup_interactive()  # type: ignore[attr-defined]
        return 0

    hub = Hub(build_providers(cfg))
    hub.connect_all()
    srv = make_server(hub, cfg)
    log.info("HomeHub on http://%s:%d (providers: %s)", cfg.host, cfg.port, ", ".join(cfg.providers))
    for name, err in hub.errors.items():
        log.warning("%s: %s", name, err)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
