#!/usr/bin/env python3
"""Sweep the argument bytes of the frame.

Every frame we have sent so far had zeros in bytes 2 and 3 (the two
"argument" bytes of the vendor layout `[id][class][len][arg0][arg1][type]`).
In the sibling vendor protocol the frame addresses a *paired device* by
number, so a non-zero argument may be required before the dongle forwards
anything to the mouse.

This sweeps arg0 and arg1 over 0x00-0xFF for the classes the vendor driver
uses, and reports anything the device sends back.

Run: sudo python3 tools/usb_sweep8.py [pid]
"""
import ctypes
import fcntl
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.usb_sweep7 import (  # noqa: E402
    control, bulk_read, unbind, rebind, device, is_battery,
    USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE,
)

CLASSES = [0x05, 0x07, 0x10, 0x11, 0x31, 0x06]
TYPES = [0x00, 0x02, 0x04]


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
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
    print(f"device {path} interface {iface} ({name})")
    fd = os.open(path, os.O_RDWR)
    hits = []
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, __import__("fcntl").ioctl, arg, True) if False else None
        fcntl.ioctl(fd, 0x8004550F, arg, True)   # USBDEVFS_CLAIMINTERFACE
        print(f"claimed interface {iface}\n")
        for pos in (2, 3):                      # which argument byte
            for cls in CLASSES:
                for t in TYPES:
                    for v in range(0x100):
                        body = bytearray([cls, 0x04, 0x00, 0x00, t, 0x00, 0x00, 0x00])
                        body[pos] = v
                        payload = bytes(body).ljust(63, b"\x00")
                        try:
                            control(fd, 0x21, 0x09, (2 << 8) | 6, iface, payload, 63, 300)
                        except OSError as exc:
                            print(f"  {exc.strerror}")
                            return
                        time.sleep(0.03)
                        if in_ep:
                            try:
                                data = bulk_read(fd, in_ep, 64, 60)
                            except OSError:
                                continue
                            if any(data) and not is_battery(data):
                                print(f"  *** HIT arg{pos}={v:#04x} class {cls:#04x} type {t:#04x}:"
                                      f" raw={data[:16].hex(' ')}", flush=True)
                                hits.append((pos, v, cls, t, data[:16].hex(" ")))
                print(f"  arg{pos} class {cls:#04x} done", flush=True)
        print("\nHITS:", hits)
    finally:
        try:
            arg = (ctypes.c_uint * 1)(iface)
            fcntl.ioctl(fd, 0x80045510, arg, True)   # USBDEVFS_RELEASEINTERFACE
        except OSError:
            pass
        os.close(fd)
        rebind(name, drv)
        print(f"re-bound {drv}")


if __name__ == "__main__":
    main()
