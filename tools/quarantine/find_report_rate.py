#!/usr/bin/env python3
"""Search for the frame that changes the mouse's report rate.

The polling rate is directly measurable (the mouse's interrupt-IN stream), so
this is a behavioural search: write a candidate frame, then measure.

The mouse only streams reports while it is moving, so keep the mouse moving
during the run.

Usage: python3 tools/find_report_rate.py [vendor_node] [mouse_node]
"""
import fcntl
import os
import select
import struct
import sys
import time

VENDOR = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
MOUSE = sys.argv[2] if len(sys.argv) > 2 else "/dev/hidraw4"
SIZE = 63


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

ctl = os.open(VENDOR, os.O_RDWR)
os.set_blocking(ctl, False)
rd = os.open(MOUSE, os.O_RDONLY | os.O_NONBLOCK)


def write_frame(body):
    buf = bytearray([6]) + bytearray(body).ljust(SIZE - 1, b"\x00")
    fcntl.ioctl(ctl, SOUTPUT(len(buf)), buf, True)


def rate(seconds=1.2):
    """Return (fastest_interval_us, report_count) - the fastest interval is
    the polling rate while the mouse is moving."""
    stamps, end = [], time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([rd], [], [], 0.02)
        if r:
            try:
                os.read(rd, 64)
            except OSError:
                continue
            stamps.append(time.perf_counter())
    if len(stamps) < 8:
        return None, 0
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    core = gaps[max(0, len(gaps) // 20): max(1, len(gaps) * 9 // 10)]
    if not core:
        return None, len(stamps)
    return core[0] * 1e6, len(stamps)


def show(label, body):
    write_frame(body)
    time.sleep(0.15)
    us, n = rate(1.2)
    hz = (1e6 / us) if us else 0
    print(f"  {label:34} {bytes(body)[:10].hex(' '):22} -> {hz:7.0f} Hz  ({n} reports)", flush=True)
    return hz


print("== baseline (keep the mouse moving!) ==")
base = show("baseline", bytes([0xFA, 0x01, 0x00, 0x00, 0x00]))

print("\n== one-byte values, tags 0x01..0x0f ==")
hits = []
for tag in range(0x01, 0x10):
    for value in (0x00, 0x01, 0x02, 0x03, 0x04):
        hz = show(f"tag {tag:#04x} val {value}", bytes([0xFA, 0x02, 0x00, 0x00, tag, value]))
        if base and hz and abs(hz - base) > base * 0.15:
            hits.append(("byte", tag, value, hz))

print("\n== u16 values (125/250/500/1000 Hz), tags 0x01..0x0f ==")
for tag in range(0x01, 0x10):
    for hz_target in (125, 250, 500, 1000):
        hz = show(f"tag {tag:#04x} = {hz_target} Hz",
                  bytes([0xFA, 0x03, 0x00, 0x00, tag, hz_target & 0xFF, (hz_target >> 8) & 0xFF]))
        if base and hz and abs(hz - base) > base * 0.15:
            hits.append(("u16", tag, hz_target, hz))

print("\nHITS:", hits)
os.close(ctl); os.close(rd)
