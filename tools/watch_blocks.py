#!/usr/bin/env python3
"""Watch the config blocks and print what changes.

The device exposes its paired-mouse descriptor (class 0x05) and two config
blocks (0x10, 0x11) on the hidden report id 0 channel.  Reading a block
repeatedly and diffing it shows exactly which bytes hold which setting -
press the mouse's DPI button while this runs and the DPI fields light up.

Run: sudo python3 tools/watch_blocks.py [pid]
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
BLOCKS = [0x05, 0x10, 0x11, 0x07, 0x0F]


def build(cls, type_=0x00, value=b""):
    body = bytearray([RID, cls, len(value) + 1, 0x00, 0x00, type_]) + bytearray(value)
    return bytes(body).ljust(64, b"\x00")


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6425
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
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
    last = {}
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")
        print("watching - press the mouse DPI button now\n")
        end = time.time() + secs
        while time.time() < end:
            for cls in BLOCKS:
                control(fd, 0x21, 0x09, (2 << 8) | 0, iface, build(cls), 64, 300)
                time.sleep(0.03)
                if in_ep:
                    for _ in range(2):
                        try:
                            data = bulk_read(fd, in_ep, 64, 60)
                        except OSError:
                            break
                        if any(data) and not is_battery(data) and data[1] == cls:
                            n = data[2]
                            val = data[6:6 + max(0, n - 1)]
                            if cls not in last:
                                last[cls] = val
                                print(f"  class {cls:#04x} initial: {val.hex(' ')}")
                            elif val != last[cls]:
                                old, new = last[cls], val
                                diff = " ".join(
                                    f"[{i}]{old[i]:02x}->{new[i]:02x}"
                                    for i in range(min(len(old), len(new)))
                                    if old[i] != new[i])
                                print(f"  class {cls:#04x} CHANGED: {diff}", flush=True)
                                print(f"        now: {new.hex(' ')}")
                                last[cls] = val
                            break
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
