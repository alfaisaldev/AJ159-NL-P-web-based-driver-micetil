#!/usr/bin/env python3
"""Probe the class 0x06 command on the hidden report id 0 channel.

The device answers class 0x06 with `06 04 01 00 00 02 00` for every type we
tried.  This script sends class 0x06 with *distinctive* values and prints the
reply, so we can tell whether the command is

  * a reader   (the reply carries the device's state), or
  * a writer  (the reply echoes what we sent, i.e. an ack), or
  * a no-op    (the reply is constant).

Run: sudo python3 tools/probe_class06.py [pid]
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

CLASS = 0x06


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
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")

        cases = []
        for t in range(0x00, 0x10):
            cases.append((f"type {t:#04x} value 11 22 33", t, bytes([0x11, 0x22, 0x33])))
        cases.append(("type 0x02 dpi stage0 1234", 0x02, bytes([0x00, 0xD2, 0x04])))
        cases.append(("type 0x02 dpi stage5 3200", 0x02, bytes([0x05, 0x80, 0x0C])))
        cases.append(("type 0x04 rate 500", 0x04, bytes([0x02])))
        cases.append(("type 0x05 rate 500", 0x05, bytes([0x02])))
        cases.append(("empty", 0x00, b""))

        for label, t, value in cases:
            body = bytes([CLASS, len(value) + 1, 0x00, 0x00, t]) + value
            payload = body.ljust(64, b"\x00")
            try:
                control(fd, 0x21, 0x09, (2 << 8) | 0, iface, payload, 64, 300)
            except OSError as exc:
                print(f"  SET: {exc.strerror}")
                return
            time.sleep(0.15)
            replies = []
            if in_ep:
                for _ in range(4):
                    try:
                        data = bulk_read(fd, in_ep, 64, 120)
                    except OSError:
                        break
                    if any(data):
                        replies.append(data[:16].hex(" "))
            print(f"  {label:32} -> {replies}", flush=True)
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
