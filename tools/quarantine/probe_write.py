#!/usr/bin/env python3
"""Discover the AJAZZ NL write protocol by probing frames and watching replies.

What we know:
  * the device strips the report id, so the body it sees starts at our byte 1
  * it echoes body[0] in its reply frame
  * frames it rejects come back as  [echo, 01, 00, 00, <error>, 00]
  * frames it accepts produce no reply

Usage: python3 tools/probe_write.py [node]
"""
import fcntl
import os
import select
import sys
import time

NODE = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw3"
REPORT_ID = 6
SIZE = 63


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open(NODE, os.O_RDWR)
os.set_blocking(fd, False)


def send(body):
    buf = bytearray([REPORT_ID]) + bytearray(body).ljust(SIZE - 1, b"\x00")
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)


def drain(seconds=0.45):
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


def show(label, body):
    send(body)
    replies = drain()
    kinds = []
    for r in replies:
        # ignore the periodic battery/link pushes
        if len(r) > 1 and r[1] == 0xFA:
            kinds.append("push:" + r[:8].hex(" "))
        else:
            kinds.append("REPLY:" + r[:8].hex(" "))
    print(f"  {label:38} {bytes(body)[:9].hex(' '):24} {kinds}")


print(f"== probing {NODE} ==")

print("\n-- A: TLV style, cmd 0xfa, one byte of payload, tags 0x01..0x0f --")
for tag in range(0x01, 0x10):
    show(f"fa tag {tag:#04x} val 0", bytes([0xFA, 0x02, 0x00, 0x00, tag, 0x00]))

print("\n-- B: TLV style, cmd 0xfa, DPI-shaped payload (stage + u16) --")
for stage in range(0, 6):
    show(f"fa dpi stage {stage} = 400", bytes([0xFA, 0x04, 0x00, 0x00, 0x02, stage, 0x90, 0x01]))

print("\n-- C: single-byte command ids, zero body --")
for cmd in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0A, 0x0F,
            0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x20, 0x21, 0x22, 0x23, 0x24,
            0x30, 0x40, 0x50, 0x80, 0x83, 0x84, 0x85, 0x8F, 0xF7, 0xFA, 0xFB, 0xFF):
    show(f"cmd {cmd:#04x}", bytes([cmd]))

os.close(fd)
