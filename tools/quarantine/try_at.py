#!/usr/bin/env python3
"""Try AT-style queries on the AJAZZ vendor output channels and report replies.

Only read-only queries are sent; nothing that changes a setting.
"""
import fcntl
import os
import select
import sys
import time


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)
GFEAT = lambda n: ioc(3, ord("H"), 0x07, n)

fd = os.open("/dev/hidraw5", os.O_RDWR)
os.set_blocking(fd, False)


def send(rid, data, size):
    buf = bytearray([rid]) + bytearray(data[:size]).ljust(size, b"\x00")
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)


def drain(seconds):
    out = []
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if not r:
            continue
        try:
            d = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if d:
            out.append(d)
    return out


CANDIDATES = [
    (6, b"+HELP\r\n"),
    (6, b"AT+HELP\r\n"),
    (6, b"help\r\n"),
    (6, b"AT+VER?\r\n"),
    (6, b"+VER\r\n"),
    (6, b"AT+VERSION\r\n"),
    (7, b"AT+VER?\r\n"),
    (7, b"AT+HELP\r\n"),
    (8, b"AT+VER?\r\n"),
    (8, b"AT+HELP\r\n"),
]

for rid, text in CANDIDATES:
    size = {6: 63, 7: 9, 8: 12}[rid]
    send(rid, text, size)
    replies = drain(1.2)
    shown = [r[:24].hex(" ") for r in replies]
    print(f"id{rid} <- {text!r:20} replies: {shown}")

# also try the feature-report channel (what the Windows driver uses)
for rid, text in ((6, b"+HELP\r\n"), (6, b"AT+HELP\r\n"), (7, b"AT+HELP\r\n"), (8, b"AT+HELP\r\n")):
    size = {6: 63, 7: 9, 8: 12}[rid]
    buf = bytearray([rid]) + bytearray(text[:size]).ljust(size, b"\x00")
    try:
        fcntl.ioctl(fd, GFEAT(len(buf)), buf, True)
    except OSError as exc:
        print(f"GET_FEATURE id{rid}: ERR {exc}")
        continue
    replies = drain(0.8)
    print(f"GET_FEATURE id{rid} {text!r:16} -> {buf[:24].hex(' ')} replies: {[r[:24].hex(' ') for r in replies]}")

os.close(fd)
