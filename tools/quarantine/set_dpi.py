#!/usr/bin/env python3
"""Find the action byte that writes a config block, then set the DPI.

The device exposes the paired mouse's settings in class 0x05; the six u16
values at offset 12 are the DPI stages encoded as dpi/50 - 1 (7, 15, 23, 31,
47, 63 = 400, 800, 1200, 1600, 2400, 3200 dpi).

The request's type byte is the *action*; this script tries every action
byte for the candidate classes, writes a modified block and reads it back to
see which one sticks.  The original value is restored afterwards.

Run: sudo python3 tools/set_dpi.py [pid] [dpi]
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

RID = 0x06
INFO_CLASS = 0x05           # the paired mouse's info/DPI block
DPI_OFF = 12                # offset of the six u16 DPI values


def build(cls, type_, value=b""):
    body = bytearray([RID, cls, len(value) + 1, 0x00, 0x00, type_]) + bytearray(value)
    return bytes(body).ljust(64, b"\x00")


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
    new_dpi = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
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
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")

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
                            best = data
                            break
                        best = best or data
            return best

        def read_info():
            r = request(INFO_CLASS)
            if not r:
                return None
            n = r[2]
            return r[6:6 + max(0, n - 1)]

        base = read_info()
        if not base:
            print("no reply from the info class")
            return
        print(f"info block: {base.hex(' ')}")
        stages = [base[DPI_OFF + 2 * i] | (base[DPI_OFF + 2 * i + 1] << 8) for i in range(6)]
        print("DPI stages (dpi/50-1):", stages, "->", [(s + 1) * 50 for s in stages])

        if not new_dpi:
            print("\nno --dpi given, just probing which action byte writes")
        else:
            target = new_dpi // 50 - 1
            print(f"\ntrying to set stage 0 to {new_dpi} dpi (code {target})")

        # find the action byte that writes
        for cls in (INFO_CLASS, 0x10, 0x11):
            for action in range(0x00, 0x10):
                mod = bytearray(base)
                mod[DPI_OFF] = (target if new_dpi else stages[0] ^ 0x5A) & 0xFF
                r = request(cls, action, bytes(mod))
                if not r:
                    continue
                after = read_info()
                if after and after != base:
                    print(f"  *** class {cls:#04x} action {action:#04x} CHANGED the block!")
                    print(f"      before: {base.hex(' ')}")
                    print(f"      after : {after.hex(' ')}")
                    if new_dpi:
                        # leave the new value in place
                        continue
                    # restore
                    request(cls, action, bytes(base))
                    print("      restored")
                    base = read_info() or base
                else:
                    print(f"  class {cls:#04x} action {action:#04x}: no effect")
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
