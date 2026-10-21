#!/usr/bin/env python3
"""Map the command channel on report id 0 (the 'feature report 0' channel).

Discovery: the device answers frames sent on report id 0/1 - the channel the
old AJ-family uses for feature reports, and the one this device's descriptor
does not advertise (so hidraw cannot reach it, but raw USB can).

This sweep sends `[class][len][0][0][type][value]` on report id 0 for a range
of classes and types and prints the device's reply for each, so the class that
carries "set DPI" / "set report rate" can be identified.

Run: sudo python3 tools/usb_sweep9.py [pid] [report_id]
"""
import ctypes
import fcntl
import os
import sys
import time

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from tools.usb_sweep7 import (  # noqa: E402
    control, bulk_read, unbind, rebind, device, is_battery,
    USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE,
)

CLASSES = list(range(0x00, 0x40))
TYPES = list(range(0x00, 0x10))


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
    rid = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    path, ifs = device(pid)
    if not path:
        print("device not found")
        return
    iface = next((n for n, _, _ in ifs if n == 1), 0)
    name = next(nm for n, _, nm in ifs if n == iface)
    eps = dict((n, e) for n, e, _ in ifs)[iface]
    in_ep = next((e for e in eps if e & 0x80), None)
    drv = unbind(name)
    if not drv:
        print("could not unbind usbhid")
        return
    print(f"device {path} interface {iface} ({name})  report id {rid}")
    fd = os.open(path, os.O_RDWR)
    seen = {}
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")
        for cls in CLASSES:
            for t in TYPES:
                value = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02, 0x00, 0x00])
                body = bytes([cls, len(value) + 1, 0x00, 0x00, t]) + value
                payload = body.ljust(64, b"\x00")
                try:
                    control(fd, 0x21, 0x09, (2 << 8) | rid, iface, payload, 64, 300)
                except OSError as exc:
                    print(f"  SET: {exc.strerror}")
                    return
                time.sleep(0.05)
                if in_ep:
                    try:
                        data = bulk_read(fd, in_ep, 64, 80)
                    except OSError:
                        continue
                    if any(data) and not is_battery(data):
                        key = (cls, t)
                        reply = data[:8].hex(" ")
                        if key not in seen:
                            seen[key] = reply
                            print(f"  class {cls:#04x} type {t:#04x} -> {reply}", flush=True)
        print(f"\ndistinct replies: {len(seen)}")
    finally:
        try:
            arg = (ctypes.c_uint * 1)(iface)
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
        except OSError:
            pass
        os.close(fd)
        rebind(name, drv)
        print(f"re-bound {drv}")


if __name__ == "__main__":
    main()
