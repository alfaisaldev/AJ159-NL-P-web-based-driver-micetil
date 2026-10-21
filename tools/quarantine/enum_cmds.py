#!/usr/bin/env python3
"""Enumerate the supported (class, action) command space of the mouse.

Every class we know replies with a generic "not supported" frame
(type 0x02, one byte) for most actions.  A supported action replies
differently (a different type and/or a longer payload), so this probe
reveals which commands actually exist - including the vendor app's
"Restore Factory Settings" and the key/button map.

Only *empty* payloads are sent, and the DPI table is verified afterwards.

Run: sudo python3 tools/enum_cmds.py [pid]
"""
import ctypes
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools.usb_sweep7 import (control, bulk_read, unbind, rebind, device, is_battery,
                             USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE)

RID = 0x06
CLASSES = [0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C,
           0x0F, 0x10, 0x11, 0x12, 0x30, 0x31, 0x32, 0x40, 0x50]
ACTIONS = range(0x00, 0x20)


def build(cls, action, value=b""):
    b = bytearray([RID, cls, len(value) + 1, 0, 0, action]) + bytearray(value)
    return bytes(b).ljust(64, b"\x00")


pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6d25
path, ifs = device(pid)
if not path:
    raise SystemExit("device not found")
iface = next((n for n, _, _ in ifs if n == 1), 0)
name = next(nm for n, _, nm in ifs if n == iface)
eps = dict((n, e) for n, e, _ in ifs)[iface]
in_ep = next((e for e in eps if e & 0x80), None)
drv = unbind(name)
fd = os.open(path, os.O_RDWR)
try:
    arg = (ctypes.c_uint * 1)(iface)
    fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
    print(f"device {path} interface {iface} ({name})\n")

    def request(cls, action, value=b"", wait=0.05):
        control(fd, 0x21, 0x09, (2 << 8) | 0, iface, build(cls, action, value), 64, 300)
        time.sleep(wait)
        for _ in range(3):
            try:
                data = bulk_read(fd, in_ep, 64, 40)
            except OSError:
                break
            if any(data) and not is_battery(data) and data[1] == cls:
                return data
        return b""

    def info():
        r = request(0x05, 0x00, wait=0.15)
        if not r or r[2] < 2:
            return None
        return r[6:6 + r[2] - 1]

    base = info()
    print("dpi table before:", base.hex(" ") if base else None)

    print("\n-- non-generic replies (generic = type 0x02, len 1) --")
    for cls in CLASSES:
        for act in ACTIONS:
            r = request(cls, act)
            if not r:
                continue
            t, n = r[5], r[2]
            if t == 0x02 and n == 1:
                continue
            print(f"  class {cls:#04x} action {act:#04x} -> type {t:#04x} len {n}  "
                  f"{r[6:6 + max(0, n - 1)].hex(' ')}")

    after = info()
    print("\ndpi table after :", after.hex(" ") if after else None)
    print("UNCHANGED" if after == base else "*** CHANGED - aborting further writes ***")
finally:
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
    except OSError:
        pass
    os.close(fd)
    rebind(name, drv)
    print("re-bound")
