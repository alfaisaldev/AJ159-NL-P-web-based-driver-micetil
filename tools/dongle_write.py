#!/usr/bin/env python3
"""Test host->dongle->mouse command frames.

The mouse receives its settings over the NearLink link; the dongle relays
the PC's HID output report to it.  So we write candidate command frames to
the dongle's vendor node and watch the dongle for the mouse's telemetry
(the mouse pushes a DPI frame whenever its state changes - that is our
oracle).

Usage: python3 tools/dongle_write.py [node] [header] [type] [payload_hex]
"""
import fcntl
import os
import select
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from battery import claim_device  # noqa: E402

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw3"
SIZE = 63


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open(NODE, os.O_RDWR)
os.set_blocking(fd, False)
try:
    claim_device(fd, NODE)
except OSError as exc:
    raise SystemExit(
        f"{exc}\nStop the panel first:  systemctl --user stop ajazz-panel"
    )


def send(body):
    buf = bytearray([6]) + bytearray(body).ljust(SIZE - 1, b"\x00")
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


def show(frame):
    if len(frame) > 5 and frame[1] == 0xFA:
        tag = frame[5]
        names = {1: "link", 2: "DPI", 3: "battery", 6: "mode"}
        extra = ""
        if tag == 0x02 and len(frame) > 8:
            extra = f" stage={frame[6]} dpi={frame[7] | (frame[8] << 8)}"
        if tag == 0x03 and len(frame) > 6:
            extra = f" percent={frame[6]} state={frame[7] if len(frame) > 7 else '?'}"
        return f"push {names.get(tag, hex(tag))}{extra}"
    return "REPLY " + frame[:10].hex(" ")


HEADERS = [0xFA, 0x02, 0x7A, 0x10, 0x15, 0x36, 0x82, 0x92, 0x90, 0xB6, 0x76, 0x56]
TYPES = [0x02, 0x05, 0x04, 0x07]

print(f"== writing to the dongle {NODE} ==")
print("watching for the mouse's telemetry to change...\n")
drain(1.0)
for h in HEADERS:
    for t in TYPES:
        if t == 0x02:
            pl = bytes([0x05, 0x80, 0x0C])          # stage 5 = 3200 dpi (factory value)
        elif t in (0x04, 0x05):
            pl = bytes([0x02])                        # rate index 2
        else:
            pl = bytes([0x01])
        body = bytes([h, len(pl) + 1, 0x00, 0x00, t]) + pl
        send(body)
        got = drain(1.6)
        interesting = [g for g in got if not (len(g) > 5 and g[5] == 0x03)]
        if interesting:
            print(f"  HIT hdr={h:#04x} type={t:#04x} -> {[(g[:10].hex(' '), show(g)) for g in got]}", flush=True)
    print(f"  ...header {h:#04x} done", flush=True)

print("\ndone")
os.close(fd)
