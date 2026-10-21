#!/usr/bin/env python3
"""
AJAZZ mouse panel - tiny local web server.

Serves a single-page UI and a JSON endpoint with the live battery level of
the attached AJAZZ AJ159 NL P mouse. Standard library only.

    python3 server.py [--host 127.0.0.1] [--port 8778]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from battery import AjazzBattery

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
STARTED = time.time()
RATE_FILE = os.path.join(os.path.expanduser("~/.cache"), "ajazz-panel", "rate.json")
RATE_OPTIONS = [125, 250, 500, 1000]   # measured in ajaaz.pcapng, see ajazz_protocol


class Handler(BaseHTTPRequestHandler):
    device: AjazzBattery = None  # type: ignore[assignment]
    server_version = "ajazz-panel/1.0"

    def _serve_static(self, rel: str) -> None:
        self._serve_file(STATIC_DIR, rel)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_static("index.html")
        elif path == "/api/battery":
            self._serve_json(self.device.snapshot())
        elif path == "/api/rate":
            self._serve_json(self.rate_state())
        elif path == "/api/dpi":
            self._serve_json(self.dpi_state())
        elif path == "/api/stage":
            self._serve_json(self.dpi_state())
        elif path == "/api/health":
            self._serve_json({"ok": True, "uptime": int(time.time() - STARTED)})
        elif path.startswith("/assets/"):
            self._serve_file(ASSETS_DIR, path[len("/assets/"):])
        else:
            self._serve_static(path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/dpi":
            self._handle_dpi()
        elif path == "/api/stage":
            self._handle_stage()
        elif path == "/api/rate":
            self._handle_rate()
        else:
            self.send_error(404, "not found")

    # -- report rate ----------------------------------------------------------
    def rate_state(self) -> dict:
        hz, readable = None, False
        try:
            hz = self.device.rate_hz()
            readable = hz is not None
        except (OSError, TimeoutError):
            pass
        if hz is None:
            try:
                with open(RATE_FILE, "r", encoding="utf-8") as fh:
                    hz = json.load(fh).get("hz")
            except (OSError, ValueError):
                pass
        return {"ok": True, "hz": hz, "options": RATE_OPTIONS,
                "readable": readable,
                "note": "read back from the info block, byte 24" if readable
                        else "the mouse did not answer the read; showing the last value written"}

    def _handle_rate(self) -> None:
        import ajazz_protocol as proto

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            hz = int(body["hz"])
        except (KeyError, TypeError, ValueError):
            self._serve_json({"ok": False, "error": "hz is required", "hz": None})
            return
        try:
            cls, type_, value = proto.report_rate_frame(hz)
        except proto.AjazzError as exc:
            self._serve_json({"ok": False, "error": str(exc), "hz": None})
            return
        try:
            self.device.command(cls, type_, value, timeout=1.0)
        except (OSError, TimeoutError) as exc:
            self._serve_json({"ok": False, "hz": self.rate_state()["hz"],
                              "error": f"device did not acknowledge: {exc}"})
            return
        time.sleep(0.4)
        got = None
        try:
            got = self.device.rate_hz()
        except (OSError, TimeoutError):
            pass
        if got is not None and got != hz:
            self._serve_json({"ok": False, "hz": got,
                              "error": f"device kept {got} Hz, wanted {hz}"})
            return
        try:
            os.makedirs(os.path.dirname(RATE_FILE), exist_ok=True)
            with open(RATE_FILE, "w", encoding="utf-8") as fh:
                json.dump({"hz": hz}, fh)
        except OSError:
            pass
        self._serve_json({"ok": True, "hz": hz, "options": RATE_OPTIONS,
                          "readable": got is not None})

    # -- DPI -----------------------------------------------------------------
    def dpi_state(self) -> dict:
        try:
            info = self.device.dpi_info()
        except (OSError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "dpi": []}
        table, active = info["table"], info["active"]
        return {"ok": bool(table), "dpi": table, "stages": len(table),
                "active": active,
                "activeDpi": table[active] if active is not None and active < len(table) else None}

    def _handle_stage(self) -> None:
        """Verified active-stage change: chosen stage last, read back, roll back."""
        import ajazz_protocol as proto

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            stage = int(body["stage"])
        except (KeyError, TypeError, ValueError):
            self._serve_json({"ok": False, "error": "stage is required"})
            return
        if not 0 <= stage < proto.DPI_STAGES:
            self._serve_json({"ok": False, "error": f"stage must be 0..{proto.DPI_STAGES - 1}"})
            return
        try:
            res = self.device.set_dpi_stage(stage)
        except (OSError, TimeoutError) as exc:
            failed = self.dpi_state()
            self._serve_json({"ok": False, "error": str(exc),
                              "active": failed.get("active"),
                              "dpi": failed.get("dpi", []),
                              "activeDpi": failed.get("activeDpi")})
            return
        self._serve_json({"ok": True, "active": res["stage"], "activeDpi": res["dpi"],
                          "dpi": res["table"], "stages": len(res["table"]),
                          "changed": res["changed"]})

    def _handle_dpi(self) -> None:
        """Verified DPI write: vendor frame -> read back -> roll back on miss."""
        import ajazz_protocol as proto

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            stage = int(body["stage"])
            dpi = int(body["dpi"])
        except (KeyError, TypeError, ValueError):
            self._serve_json({"ok": False, "error": "stage and dpi are required", "dpi": []})
            return
        if not 0 <= stage < proto.DPI_STAGES or not 50 <= dpi <= 26000:
            self._serve_json({"ok": False, "dpi": self.dpi_state()["dpi"],
                              "error": f"stage must be 0..{proto.DPI_STAGES - 1}, dpi 50..26000"})
            return

        try:
            before = self.device.dpi_info()
            table, active = before["table"], before["active"]
            if len(table) != proto.DPI_STAGES:
                raise OSError("cannot read the DPI table")
            target = list(table)
            target[stage] = dpi
            # keep the stage the mouse is on: the device activates whichever
            # stage frame it receives last, so that one goes last again
            keep = active if active is not None else 0
            for cls, type_, value in proto.dpi_frames_for_stage(target, keep):
                self.device.command(cls, type_, value, want_reply=False)
                time.sleep(0.06)
            good, after = self.device._confirm_dpi(target, keep)
            if not good:
                for cls, type_, value in proto.dpi_frames_for_stage(table, keep):
                    self.device.command(cls, type_, value, want_reply=False)
                    time.sleep(0.06)
                restored = self.device.dpi_info()
                self._serve_json({"ok": False, "dpi": restored["table"],
                                  "active": restored["active"],
                                  "activeDpi": (restored["table"][restored["active"]]
                                                if restored["active"] is not None else None),
                                  "error": f"device stored {after['table']} on stage "
                                           f"{after['active']}, wanted {target} on stage "
                                           f"{keep}; previous table restored"})
                return
            self._serve_json({"ok": True, "dpi": after["table"],
                              "active": after["active"],
                              "activeDpi": after["table"][after["active"]]})
        except (OSError, TimeoutError) as exc:
            self._serve_json({"ok": False, "error": str(exc), "dpi": []})

    # -- helpers -------------------------------------------------------------
    def _serve_file(self, root: str, rel: str) -> None:
        safe = os.path.normpath(rel).lstrip("/")
        full = os.path.join(root, safe)
        if not full.startswith(root) or not os.path.isfile(full):
            self.send_error(404, "not found")
            return
        ctype, _ = mimetypes.guess_type(full)
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the console quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="AJAZZ mouse battery panel")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8778)
    args = ap.parse_args()

    device = AjazzBattery()
    device.start()
    Handler.device = device

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    print(f"AJAZZ panel  ->  http://{args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        device.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
