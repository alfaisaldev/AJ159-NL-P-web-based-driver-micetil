#!/usr/bin/env python3
"""Discover the AJAZZ NL setting commands by writing candidate frames and
watching for *effects* rather than replies.

Effects we can see:
  * a telemetry push we did not ask for (e.g. a new DPI frame)
  * a change in the mouse's USB polling rate (report rate setting)
  * an error reply frame

Usage: python3 tools/discover_settings.py [node] [seconds_per_candidate]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw3"
PER = float(sys.argv[2]) if len(sys.argv) > 2 else 0.8
SIZE = 63


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open(NODE, os.O_RDWR)
os.set_blocking(fd, False)


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


def describe(frame):
    if len(frame) < 8:
        return frame.hex(" ")
    if frame[1] == 0xFA:
        tag = frame[5]
        names = {1: "link", 2: "DPI", 3: "battery", 6: "mode"}
        return f"push tag={tag:#04x}({names.get(tag,'?')}) val={frame[6:8].hex(' ')}"
    return "REPLY " + frame[:8].hex(" ")


print(f"== discovering settings on {NODE} ==")
print("-- baseline --")
for f in drain(2.0):
    print("   ", describe(f))

print("\n-- TLV probes: body = [cmd, len, 00, 00, tag, value] --")
for cmd in (0xFA,):
    for tag in range(0x01, 0x10):
        for value in (0x00, 0x01, 0x02, 0x03):
            body = bytes([cmd, 0x02, 0x00, 0x00, tag, value])
            send(body)
            got = drain(PER)
            interesting = [describe(f) for f in got]
            if interesting:
                print(f"   tag {tag:#04x} val {value} -> {interesting}")

print("\n-- old-AJ-style probes: body = [cmd, sub, len, payload...] --")
for cmd in (0x21, 0x22, 0x23, 0x24, 0x30, 0x40, 0x50, 0x83, 0xF7):
    for sub in (0x00, 0x01, 0x02):
        body = bytes([cmd, sub, 0x02, 0x03, 0x40, 0x06])
        send(body)
        got = drain(PER)
        interesting = [describe(f) for f in got]
        if interesting:
            print(f"   cmd {cmd:#04x} sub {sub:#04x} -> {interesting}")

os.close(fd)
print("done")
