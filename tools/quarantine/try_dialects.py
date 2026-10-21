#!/usr/bin/env python3
"""Try the candidate protocol dialects against the device.

Three shapes are known to be plausible for this vendor family:

  A  IRIS-v2 NearLink   write [cmd][payload…]      read [cmd][status][data…]
                        cmds 0x13 info, 0x17 config, 0x19 dpi, 0x1A set dpi
                        rate codes 1=1000 2=500 4=250 8=125 Hz
  B  AJ-series (0x3151) write [cmd][payload…] 64-byte frame, checksum
                        (sum of body bytes) & 0x7f in the last byte
                        rate cmd 0x04, dpi cmd 0x54
  C  BS20 TLV (ours)    [0xfa][len][0][0][type][value…]

Usage: python3 tools/try_dialects.py [node]
"""
import fcntl
import os
import select
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from battery import claim_device  # noqa: E402

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw3"
BODY = 62          # bytes after the report id for a 63-byte report


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open(NODE, os.O_RDWR)
os.set_blocking(fd, False)
try:
    claim_device(fd, NODE)
except OSError as exc:
    raise SystemExit(f"{exc}\nStop the panel: systemctl --user stop ajazz-panel")


def send(body):
    buf = bytearray([6]) + bytearray(body).ljust(BODY, b"\x00")
    assert len(buf) == 1 + BODY, len(buf)
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)


def drain(seconds):
    out, end = [], time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.03)
        if not r:
            continue
        try:
            d = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if d:
            out.append(d)
    return out


def show(g):
    if len(g) > 1 and g[1] == 0xFA:
        t = g[5] if len(g) > 5 else -1
        return f"push type={t:#04x} {g[6:9].hex(' ')}"
    return "REPLY " + g[:12].hex(" ")


def cks7f(b):
    return sum(b[:BODY - 1]) & 0x7F


def cks8(b):
    return sum(b[:BODY - 1]) & 0xFF


def mk(base, ck=None):
    b = bytearray(base.ljust(BODY, b"\x00"))
    if ck:
        b[BODY - 1] = ck(b)
    return bytes(b)


cases = {}

# A: IRIS-v2 style
for cmd in (0x13, 0x14, 0x15, 0x17, 0x19, 0x12):
    cases[f"A cmd {cmd:#04x} get"] = bytes([cmd, 0x00, 0x00])
cases["A cmd 0x18 set cfg"] = bytes([0x18, 0x1E] + [0] * 29)     # LEN 30
cases["A cmd 0x1A set dpi"] = bytes([0x1A, 0x30] + [0] * 47)     # LEN 48

# B: AJ-series style (64-byte frame, BIT7 checksum in the last byte)
for rate_code, hz in ((0x08, 125), (0x04, 250), (0x02, 500), (0x01, 1000)):
    cases[f"B rate {hz}Hz"] = mk(bytes([0x04, 0x00, rate_code]), cks7f)
dpi_tbl = bytearray([0x54, 0x00, 0x00, 0x06])
for v in (400, 800, 1200, 1600, 2400, 3200):
    dpi_tbl += bytes([v & 0xFF, v >> 8])
cases["B dpi table"] = mk(bytes(dpi_tbl), cks7f)
cases["B dpi table no-ck"] = mk(bytes(dpi_tbl))

# C: our TLV with a trailing checksum
for ck in (cks7f, cks8):
    tag = "cks7f" if ck is cks7f else "cks8"
    for h in (0xFA, 0x02):
        cases[f"C hdr {h:#04x} dpi {tag}"] = mk(bytes([h, 0x04, 0x00, 0x00, 0x02, 0x05, 0x80, 0x0C]), ck)
        cases[f"C hdr {h:#04x} rate {tag}"] = mk(bytes([h, 0x02, 0x00, 0x00, 0x05, 0x02]), ck)

print(f"== dialect sweep on {NODE} ({len(cases)} cases) ==")
drain(1.0)
for name, body in cases.items():
    send(body)
    got = drain(1.3)
    interesting = [g for g in got if not (len(g) > 5 and g[1] == 0xFA and g[5] == 0x03)]
    if interesting:
        print(f"  HIT {name:28} -> {[(g[:12].hex(' '), show(g)) for g in got]}", flush=True)
print("done")
os.close(fd)
