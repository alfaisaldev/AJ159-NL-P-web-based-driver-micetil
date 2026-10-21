#!/usr/bin/env python3
"""Sweep candidate host->mouse commands, using a *push oracle*.

The mouse emits telemetry (header 0xfa) whenever its state changes - a DPI
stage change, a mode change, ... .  So if a command is accepted and changes
something, we will see a push.  Silence + no push = command ignored.

Usage: python3 tools/sweep_push.py [node] [header_list] [type_list]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
HEADERS = [int(x, 0) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [
    0x7A, 0x02, 0x10, 0x15, 0x36, 0x6C, 0x56, 0x76, 0x0B, 0x0F, 0x45, 0x77, 0x1A]
TYPES = [int(x, 0) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else list(range(0x01, 0x09))
SIZE = 63
WATCH = 1.4


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


def payload_for(t):
    """A plausible, harmless value for each type."""
    if t == 0x02:          # DPI: stage + u16 value (3200 = factory value)
        return bytes([0x05, 0x80, 0x0C])
    if t == 0x03:          # battery
        return bytes([0x64, 0x02])
    if t == 0x01:          # link
        return bytes([0x01])
    return bytes([0x00])


print(f"== push-oracle sweep on {NODE} ==")
print(f"headers: {[hex(h) for h in HEADERS]}")
print(f"types:   {[hex(t) for t in TYPES]}\n")

# drain the periodic battery push so it isn't mistaken for a reaction
drain(1.0)

hits = []
for h in HEADERS:
    for t in TYPES:
        if t == 0x06:
            continue                      # mode - would switch the mouse's mode
        pl = payload_for(t)
        body = bytes([h, len(pl) + 1, 0x00, 0x00, t]) + pl
        send(body)
        got = drain(WATCH)
        interesting = [g for g in got if len(g) > 1 and g[1] not in (0x03,)]
        # keep only pushes that are not the 10s battery report
        real = [g for g in got if len(g) > 1 and g[1] == 0xFA and g[5] != 0x03]
        if real or interesting:
            print(f"  HIT hdr={h:#04x} type={t:#04x} -> {[g[:10].hex(' ') for g in got]}", flush=True)
            hits.append((h, t, [g[:10].hex(' ') for g in got]))
    print(f"  ...header {h:#04x} done", flush=True)

print("\nHITS:", hits)
os.close(fd)
