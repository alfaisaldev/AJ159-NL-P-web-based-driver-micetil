#!/usr/bin/env python3
"""Sweep the real command space on the hidden report id 0 channel.

Frame layout (deduced from the device's echo behaviour):

    [0] 0x06      report id the device should use for its reply
    [1] class     the device echoes this byte back in the reply
    [2] len       1 + number of value bytes
    [3] 0x00
    [4] 0x00
    [5] type
    [6..] value

and it must be sent as SET_REPORT on report id 0 (or 1) - the feature
channel the descriptor hides and hidraw refuses.

Run: sudo python3 tools/sweep_commands.py [pid] [report_id]
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

RID_ECHO = 0x06


def build(cls, type_, value=b"", rid=RID_ECHO):
    body = bytearray([rid, cls, len(value) + 1, 0x00, 0x00, type_]) + bytearray(value)
    return bytes(body).ljust(64, b"\x00")


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
        for cls in range(0x100):
            for t in (0x00, 0x02, 0x04, 0x05):
                value = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02, 0x00, 0x00])
                payload = build(cls, t, value)
                try:
                    control(fd, 0x21, 0x09, (2 << 8) | rid, iface, payload, 64, 300)
                except OSError as exc:
                    print(f"  SET: {exc.strerror}")
                    return
                time.sleep(0.05)
                if in_ep:
                    for _ in range(2):
                        try:
                            data = bulk_read(fd, in_ep, 64, 70)
                        except OSError:
                            break
                        if any(data) and not is_battery(data):
                            key = (cls, t)
                            if key not in seen:
                                seen[key] = data[:12].hex(" ")
                                print(f"  class {cls:#04x} type {t:#04x} -> {data[:12].hex(' ')}", flush=True)
            if cls % 16 == 15:
                print(f"   ...{cls:#04x} done", flush=True)
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
