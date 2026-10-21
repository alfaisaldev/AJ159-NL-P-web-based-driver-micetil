#!/usr/bin/env python3
"""Self-test for Micetil - runs without the mouse attached.

It checks the parts of the project that are pure logic: the wire format,
the DPI/rate encodings, the read-only guard rails, and the agreement
between the JavaScript in static/index.html and the HTML it drives.

    python3 tools/selftest.py

Exit code 0 means everything passed.
"""

from __future__ import annotations

import http.client
import os
import pathlib
import re
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ajazz_protocol as proto  # noqa: E402

FAILURES = []
CHECKS = 0


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


def check_raises(label, exc, fn, *a, **kw):
    global CHECKS
    CHECKS += 1
    try:
        fn(*a, **kw)
    except exc:
        return
    except Exception as other:  # noqa: BLE001
        FAILURES.append(f"{label}\n     raised {type(other).__name__}, expected {exc.__name__}")
        return
    FAILURES.append(f"{label}\n     did not raise {exc.__name__}")


# -- the wire format ---------------------------------------------------------
def test_frames():
    check("encode(): frame layout",
          proto.encode(0x13, 0x01, b"\x06\x00\x90\x01\x00"),
          b"\x13\x06\x00\x00\x01\x06\x00\x90\x01\x00")

    push = proto.decode(bytes([0x06, 0xFA, 0x03, 0x00, 0x00, 0x03, 0x64, 0x01]))
    check("decode(): battery push class", push["class"], 0xFA)
    check("decode(): battery push type", push["type"], 0x03)
    check("decode(): battery push value", push["value"], b"\x64\x01")

    check("decode(): short frame is not a protocol frame",
          proto.decode(b"\x06\xfa"), None)


# -- the DPI table -----------------------------------------------------------
# the class-0x05 block as it reads back on the real mouse
INFO_BLOCK = bytes([
    0x00, 0x25, 0x6D, 0x12, 0x10, 0x01, 0x01, 0x64,   # 0..7  pid, battery 100 %
    0x00, 0x00, 0x01,                                 # 8..10
    0x01,                                           # 11    active stage = 1
    0x07, 0x00, 0x0F, 0x00, 0x17, 0x00, 0x1F, 0x00,  # 12..19  400..1600
    0x2F, 0x00, 0x3F, 0x00,                          # 20..23  2400, 3200
    0x03, 0x00, 0x00, 0x00,                          # 24     rate index = 1000 Hz
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
])


def test_dpi():
    check("parse_dpi_table(): the six stages",
          proto.parse_dpi_table(INFO_BLOCK), [400, 800, 1200, 1600, 2400, 3200])

    check("encode_dpi(): read-block encoding is dpi/50 - 1",
          [proto.encode_dpi(v) for v in (400, 800, 3200)], [7, 15, 63])

    check("dpi_stage_frame(): the write form is the raw dpi, u16 LE",
          proto.dpi_stage_frame(0, 400), (0x13, 0x01, b"\x06\x00\x90\x01\x00"))

    # the active stage is the last frame sent
    frames = proto.dpi_frames_for_stage([400, 800, 1200, 1600, 2400, 3200], 3)
    check("dpi_frames_for_stage(): six frames", len(frames), 6)
    check("dpi_frames_for_stage(): the chosen stage is sent last",
          frames[-1][2][1], 3)
    check("dpi_frames_for_stage(): every stage exactly once",
          sorted(f[2][1] for f in frames), [0, 1, 2, 3, 4, 5])
    check("dpi_frames_for_stage(): the values are untouched",
          [f[2][2] | (f[2][3] << 8) for f in sorted(frames)],
          [400, 800, 1200, 1600, 2400, 3200])

    check("parse_active_stage(): byte 11 is the active stage",
          proto.parse_active_stage(INFO_BLOCK), 1)
    check("parse_active_stage(): a short block gives None",
          proto.parse_active_stage(bytes(11)), None)
    check("parse_active_stage(): a stage outside 0..5 gives None",
          proto.parse_active_stage(bytes(11) + b"\x63"), None)


# -- report rate -------------------------------------------------------------
def test_rate():
    check("report_rate_frame(): 1000 Hz", proto.report_rate_frame(1000),
          (0x13, 0x02, b"\x03\x00"))
    check("report_rate_frame(): 125 Hz", proto.report_rate_frame(125),
          (0x13, 0x02, b"\x00\x00"))
    check_raises("report_rate_frame(): an unmeasured rate is refused",
                 proto.AjazzError, proto.report_rate_frame, 2000)


# -- the guard rails ---------------------------------------------------------
def test_guards():
    device = object.__new__(proto.AjazzDevice)  # no device needed
    device.node = "test"
    device.fd = -1

    check_raises("send(): a quarantined class is refused",
                 proto.AjazzError, device.send, 0x12)
    check_raises("send(): the profile class is refused",
                 proto.AjazzError, device.send, 0x31)
    check_raises("send(): a frame with a payload is refused by default",
                 proto.AjazzError, device.send, 0x05, 0x00, b"\x01")
    check_raises("send(): a class outside the read whitelist is refused",
                 proto.AjazzError, device.send, 0x42, 0x00)


# -- the UI ------------------------------------------------------------------
def test_ui():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    wanted = set(re.findall(r"getElementById\('([^']+)'\)", html))
    missing = sorted(wanted - ids)
    check("index.html: every id the script asks for exists", missing, [])

    for asset in re.findall(r'src="(/assets/[^"]+)"', html):
        check(f"index.html: {asset} exists",
              (ROOT / asset.lstrip("/")).is_file(), True)


# -- the running panel --------------------------------------------------------
def _probe(port, method, path, headers=None, body=None):
    """One HTTP request against the test server, without touching the mouse."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def test_server_guards():
    """The panel must serve its own files and nothing else.

    A path traversal here would let any local process (or a page in a
    browser) read files the user can read, so the checks are explicit.
    """
    from http.server import ThreadingHTTPServer

    import server as panel

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        # the panel serves its own files
        status, body = _probe(port, "GET", "/index.html")
        check("server: the panel serves its own index.html", status, 200)
        check("server: the index.html is the real one",
              b"id=\"stageSeg\"" in body, True)

        # and nothing outside its directories
        for path in ("/../server.py", "/assets/../server.py",
                     "/../../../../../etc/passwd",
                     "/../../../../../home/%s/.bashrc" % os.environ.get("USER", "x")):
            status, body = _probe(port, "GET", path)
            check(f"server: {path} is refused", status, 404)
            check(f"server: {path} leaks nothing",
                  b"import" not in body[:2000] and b"root:" not in body, True)

        # only the loopback is answered (DNS rebinding)
        status, _ = _probe(port, "GET", "/api/health", {"Host": "evil.example"})
        check("server: a foreign Host is refused", status, 403)
        status, _ = _probe(port, "GET", "/api/health", {"Host": f"127.0.0.1:{port}"})
        check("server: the loopback Host is answered", status, 200)

        # a write from another site is refused
        status, _ = _probe(port, "POST", "/api/dpi",
                           {"Origin": "http://evil.example",
                            "Content-Type": "application/json"},
                           body=b'{"stage":0,"dpi":400}')
        check("server: a cross-origin write is refused", status, 403)

        # a simple (preflight-free) cross-origin form post is refused too
        status, _ = _probe(port, "POST", "/api/dpi",
                           {"Content-Type": "text/plain"}, body=b"stage=0")
        check("server: a form-encoded write is refused", status, 415)
    finally:
        httpd.shutdown()
        httpd.server_close()


def main() -> int:
    for test in (test_frames, test_dpi, test_rate, test_guards, test_ui,
                 test_server_guards):
        test()
    if FAILURES:
        print(f"FAILED  {len(FAILURES)} of {CHECKS} checks\n")
        for f in FAILURES:
            print("  x " + f)
        return 1
    print(f"ok  {CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
