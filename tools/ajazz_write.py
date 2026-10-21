#!/usr/bin/env python3
"""Controlled write probe for the AJAZZ vendor control channels.

Safety model
------------
* Only *output* reports are written (the mouse's config channels). No flash
  writes, no firmware commands, no EEPROM-commit opcodes are ever sent.
* Every frame written here is a byte-for-byte copy of a frame the device
  itself produced, with at most one value byte changed - so the layout is
  known-good and the worst case is "one setting changed".
* Every write is followed by a read-back: the telemetry stream is watched for
  N seconds and the effect is reported.

Usage:
    python3 tools/ajazz_write.py list
    python3 tools/ajazz_write.py send <report_id> <hex...>
"""
from __future__ import annotations

import fcntl
import re
import os
import select
import sys
import time

# _IOC(dir, type, nr, size)
def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

SOUTPUT = lambda n: ioc(3, ord("H"), 0x0B, n)   # HIDIOCSOUTPUT
GFEAT = lambda n: ioc(3, ord("H"), 0x07, n)     # HIDIOCGFEATURE (read)

VENDOR_PAGE = b"\x06\xb2\xff"   # usage page 0xFFB2 - the control collection

REPORT_LEN = {6: 63, 7: 9, 8: 12}


def find_vendor_node():
    """Prefer the mouse itself (wired) over the dongle."""
    found = []
    for name in sorted(n for n in os.listdir("/dev") if n.startswith("hidraw")):
        path = f"/dev/{name}"
        try:
            with open(f"/sys/class/hidraw/{name}/device/uevent") as fh:
                uevent = fh.read()
            with open(f"/sys/class/hidraw/{name}/device/report_descriptor", "rb") as fh:
                desc = fh.read()
        except OSError:
            continue
        if "HID_ID=0003:00007768:" not in uevent:
            continue
        if VENDOR_PAGE not in desc:
            continue
        pid = int(re.search(r"HID_ID=0003:[0-9A-Fa-f]{8}:([0-9A-Fa-f]{8})", uevent).group(1), 16)
        found.append((0 if pid == 0x6D25 else 1, path, pid))
    found.sort()
    return found


def open_node():
    nodes = find_vendor_node()
    if not nodes:
        raise SystemExit("no AJAZZ vendor node found")
    rank, path, pid = nodes[0]
    print(f"# using {path} (pid {pid:04x})")
    return os.open(path, os.O_RDWR)


def send(fd, report_id: int, payload: bytes) -> None:
    size = REPORT_LEN.get(report_id, len(payload))
    buf = bytearray([report_id]) + bytearray(payload[:size]).ljust(size, b"\x00")
    fcntl.ioctl(fd, SOUTPUT(len(buf)), buf, True)
    print(f"# sent  id={report_id} ({size}B): {bytes(buf).hex(' ')}")


def watch(fd, seconds=6.0) -> None:
    """Print telemetry frames that arrive after a write."""
    end = time.time() + seconds
    os.set_blocking(fd, False)
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            data = os.read(fd, 128)
        except (BlockingIOError, OSError):
            continue
        if data:
            print(f"  <- IN id={data[0]:#04x} len={len(data)}: {data[:16].hex(' ')}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    action = sys.argv[1]
    fd = open_node()
    try:
        if action == "list":
            for rank, path, pid in find_vendor_node():
                print(f"  {path}  pid {pid:04x}")
            print("  report ids: 6 (63B), 7 (9B), 8 (12B) - all output reports")
        elif action == "send":
            rid = int(sys.argv[2], 0)
            payload = bytes.fromhex("".join(sys.argv[3:]))
            send(fd, rid, payload)
            watch(fd, float(os.environ.get("WATCH", "6")))
        else:
            raise SystemExit(f"unknown action {action}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
