#!/usr/bin/env python3
"""Print the dongle's state: notifications, link, mode, and the mouse info block."""
import ctypes
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.usb_sweep7 import (control, bulk_read, unbind, rebind, device, is_battery,
                             USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE)

RID = 0x06


def build(cls, type_=0x00, value=b""):
    b = bytearray([RID, cls, len(value) + 1, 0, 0, type_]) + bytearray(value)
    return bytes(b).ljust(64, b"\x00")


pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
path, ifs = device(pid)
if not path:
    print("device not found")
    raise SystemExit(1)
iface = next((n for n, _, _ in ifs if n == 1), 0)
name = next(nm for n, _, nm in ifs if n == iface)
eps = dict((n, e) for n, e, _ in ifs)[iface]
in_ep = next((e for e in eps if e & 0x80), None)
drv = unbind(name)
fd = os.open(path, os.O_RDWR)
try:
    arg = (ctypes.c_uint * 1)(iface)
    fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
    print(f"device {path} interface {iface} ({name})")

    print("\n-- notifications (6 s) --")
    seen = {}
    end = time.time() + 6
    while time.time() < end:
        try:
            data = bulk_read(fd, in_ep, 64, 250)
        except OSError:
            continue
        if any(data):
            k = data[:8].hex(" ")
            seen[k] = seen.get(k, 0) + 1
    for k, v in seen.items():
        print("   ", k, "x", v)
    if not seen:
        print("    (none)")

    for cls, label in ((0x05, "mouse info"), (0x07, "dongle info")):
        control(fd, 0x21, 0x09, (2 << 8) | 0, iface, build(cls), 64, 300)
        time.sleep(0.3)
        r = b""
        for _ in range(6):
            try:
                data = bulk_read(fd, in_ep, 64, 200)
            except OSError:
                break
            if any(data) and data[1] == cls:
                r = data
                break
        if r:
            n = r[2]
            val = r[6:6 + max(0, n - 1)]
            print(f"\n{label} (class {cls:#04x}): {val.hex(' ')}")
            if cls == 0x05 and len(val) > 7:
                print("   battery byte:", val[7], "(0x64 = 100% -> mouse is paired)")
        else:
            print(f"\n{label}: no reply")
finally:
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
    except OSError:
        pass
    os.close(fd)
    rebind(name, drv)
