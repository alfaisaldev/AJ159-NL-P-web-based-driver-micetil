#!/usr/bin/env python3
"""Find the remaining command classes and try to restore the mouse's defaults.

The mouse's button map appears to have been damaged by an earlier probe.  The
vendor's firmware has "mouse_info reset default" / "DPI reset default" strings,
so a restore command exists.  This tool

  1. reads every config block (backup),
  2. sweeps the *unknown* classes read-only, looking for a reply longer than
     one byte (a button map / key map would show up there),
  3. tries the plausible "restore defaults" frames and reports whether the
     config block changes afterwards.

Run: sudo python3 tools/restore.py [pid]
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


def build(cls, type_=0x00, value=b""):
    b = bytearray([RID, cls, len(value) + 1, 0, 0, type_]) + bytearray(value)
    return bytes(b).ljust(64, b"\x00")


pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
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
    print(f"device {path} interface {iface} ({name})")

    def request(cls, type_=0x00, value=b"", wait=0.12):
        control(fd, 0x21, 0x09, (2 << 8) | 0, iface, build(cls, type_, value), 64, 300)
        time.sleep(wait)
        best = b""
        if in_ep:
            for _ in range(4):
                try:
                    data = bulk_read(fd, in_ep, 64, 90)
                except OSError:
                    break
                if any(data) and not is_battery(data):
                    if data[1] == cls:
                        return data
                    best = best or data
        return best

    def info():
        r = request(0x05)
        if not r:
            return None
        n = r[2]
        return r[6:6 + max(0, n - 1)]

    base = info()
    print(f"current mouse info: {base.hex(' ') if base else None}")
    if base and len(base) >= 24:
        st = [base[12 + 2 * i] | (base[13 + 2 * i] << 8) for i in range(6)]
        print("  dpi stages:", [(s + 1) * 50 for s in st])

    print("\n-- read-only sweep of the remaining classes (looking for data) --")
    for cls in range(0x60, 0x100):
        r = request(cls)
        if r and r[2] > 1:
            n = r[2]
            print(f"  class {cls:#04x}: type={r[5]:#04x} len={n}  {r[6:6+n-1].hex(' ')}")

    print("\n-- try restore-defaults frames --")
    candidates = [
        (0x02, 0x00, b""),
        (0x02, 0x00, bytes([0xFF])),
        (0x02, 0xFF, b""),
        (0x0F, 0x00, b""),
        (0x0F, 0x01, b""),
        (0x30, 0x00, bytes([0xFF])),
        (0x31, 0x00, bytes([0xFF])),
        (0x12, 0x00, bytes([0xFF])),
        (0x06, 0x00, bytes([0xFF])),
    ]
    for cls, type_, value in candidates:
        r = request(cls, type_, value, wait=0.2)
        after = info()
        tag = ""
        if after and base and after != base and len(after) >= 24:
            st = [after[12 + 2 * i] | (after[13 + 2 * i] << 8) for i in range(6)]
            tag = f"  *** INFO CHANGED -> dpi stages now {[(s + 1) * 50 for s in st]}"
        print(f"  class {cls:#04x} type {type_:#04x} value {value.hex() or '-':4}"
              f" -> reply {r[:8].hex(' ') if r else 'none'}{tag}")
finally:
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
    except OSError:
        pass
    os.close(fd)
    rebind(name, drv)
    print("re-bound")
