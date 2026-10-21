#!/usr/bin/env python3
"""Scan the AJAZZ NL command-id space.

The device parses a host frame as:  [0] command id  [1] length  [2..3] reserved
[4] tag  [5..] value.  It echoes the command id in its reply and tags the
reply with a status code, so the reply pattern tells us which command ids the
device actually knows.

Frames carry no payload (length 1 = tag only), so nothing gets set.

Usage: python3 tools/scan_cmds.py [node] [per_candidate_seconds]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
PER = float(sys.argv[2]) if len(sys.argv) > 2 else 0.22
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
        r, _, _ = select.select([fd], [], [], 0.02)
        if not r:
            continue
        try:
            d = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if d:
            out.append(d)
    return out


def classify(frames):
    """Return a signature of the replies, ignoring the periodic battery push."""
    sig = []
    for f in frames:
        if len(f) > 1 and f[1] == 0xFA and f[5] == 0x03:
            continue  # the 10 s battery push
        sig.append(f[:6].hex(" "))
    return sig


print(f"== scanning command ids on {NODE} ==")
groups = {}
for cmd in range(0x100):
    send(bytes([cmd, 0x01, 0x00, 0x00, 0x00]))
    sig = classify(drain(PER))
    key = tuple(sig)
    groups.setdefault(key, []).append(cmd)

print("\nresponse classes:")
for key, cmds in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    shown = " ".join(f"{c:#04x}" for c in cmds[:24])
    more = "" if len(cmds) <= 24 else f" ... (+{len(cmds) - 24})"
    print(f"  {len(cmds):3d} cmds  reply={list(key)}  -> {shown}{more}")

os.close(fd)
