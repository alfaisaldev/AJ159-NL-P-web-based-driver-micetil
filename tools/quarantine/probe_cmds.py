#!/usr/bin/env python3
"""Probe the AJAZZ NL command space on output report 6.

Request body layout (deduced from the device's own telemetry):
    [0] report id (0x06)      [1] command id
    [2] sub-command           [3] payload length
    [4..] payload             [last] checksum (optional)

Only read/query commands are probed - no set, no commit, no reset.
"""
import fcntl
import os
import select
import sys
import time


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)

fd = os.open("/dev/hidraw5", os.O_RDWR)
os.set_blocking(fd, False)


def send(body):
    buf = bytearray([6]) + bytearray(body).ljust(62, b"\x00")
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)


def drain(seconds=1.0):
    out, end = [], time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            continue
        try:
            d = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if d:
            out.append(d)
    return out


def old_envelope(cmd, sub=0, payload=b"", length=None):
    """AJ-series style: [0]=cmd [1]=sub [2]=len [3..]=payload, checksum last."""
    body = bytearray(62)
    body[0] = cmd
    body[1] = sub
    body[2] = length if length is not None else len(payload)
    body[3:3 + len(payload)] = payload
    body[61] = sum(body[0:61]) % 256
    return bytes(body)


def nl_envelope(cmd, sub=0, payload=b"", length=None):
    """NL style (as seen in telemetry): [0]=cmd [1]=len [2]=0 [3]=0 [4]=tag-ish."""
    body = bytearray(62)
    body[0] = cmd
    body[1] = length if length is not None else len(payload) + 1
    body[4:4 + len(payload)] = payload
    return bytes(body)


PROBES = [
    ("old 0x80 get firmware ver", old_envelope(0x80)),
    ("old 0x83 get battery", old_envelope(0x83)),
    ("old 0x84 get report rate", old_envelope(0x84)),
    ("old 0x85 get profile", old_envelope(0x85)),
    ("old 0x8f get info", old_envelope(0x8F)),
    ("old 0xF7 status poll", old_envelope(0xF7)),
    ("old 0x21 sub02 get dpi stages", old_envelope(0x21, 0x02)),
    ("nl  0x80", nl_envelope(0x80)),
    ("nl  0xfa status", nl_envelope(0xFA, payload=bytes([0x03, 0x64, 0x01]))),
    ("nl  0x03 battery tag", nl_envelope(0x03, payload=bytes([0x64, 0x01]))),
    ("nl  0x02 dpi tag", nl_envelope(0x02, payload=bytes([0x03, 0x40, 0x06]))),
    ("nl  0x01 link tag", nl_envelope(0x01, payload=bytes([0x01]))),
    ("nl  0x06 mode tag", nl_envelope(0x06, payload=bytes([0x00]))),
]

for label, body in PROBES:
    send(body)
    replies = drain(1.0)
    pretty = [r[:20].hex(" ") for r in replies]
    print(f"{label:32} -> {pretty}")

os.close(fd)
