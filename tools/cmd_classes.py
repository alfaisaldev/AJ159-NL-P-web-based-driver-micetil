#!/usr/bin/env python3
"""Classify every command id by how the mouse answers it.

The mouse replies to *bad* frames with [echo, len, 0, 0, <status>, 0].
Frames it accepts are answered with silence.  So the reply pattern tells us
which command ids the device actually knows: a well-formed frame for a known
command is accepted (no reply), for an unknown one it is rejected (reply).

Usage: python3 tools/cmd_classes.py [node] [len_field] [tag]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
LEN = int(sys.argv[2], 0) if len(sys.argv) > 2 else 2
TAG = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0
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
    for f in frames:
        if len(f) > 1 and f[1] == 0xFA:
            continue  # periodic push
        if len(f) > 1:
            return f"reply type={f[5]:#04x} echo={f[1]:#04x}"
    return "silent (accepted)"


print(f"== command classes on {NODE} (len={LEN}, tag={TAG:#04x}) ==")
groups = {}
for cmd in range(0x100):
    body = [cmd, LEN, 0x00, 0x00, TAG] + [0x00] * 8
    send(bytes(body))
    sig = classify(drain(0.18))
    groups.setdefault(sig, []).append(cmd)

for sig, cmds in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    shown = " ".join(f"{c:#04x}" for c in cmds[:20])
    more = "" if len(cmds) <= 20 else f" ...(+{len(cmds) - 20})"
    print(f"  {len(cmds):3d} cmds: {sig:32} {shown}{more}")

os.close(fd)
