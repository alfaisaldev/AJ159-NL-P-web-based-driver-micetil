#!/usr/bin/env python3
"""Dump the full reply of every command class on the hidden report id 0 channel.

Frame layout (from the device's echo behaviour):

    [0] 0x06   report id for the reply
    [1] class  (echoed back by the device)
    [2] len    1 + number of value bytes
    [3] 0x00
    [4] 0x00
    [5] type
    [6..] value

Run: sudo python3 tools/dump_replies.py [pid] [report_id]
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


def build(cls, type_, value=b"", rid=0x06):
    body = bytearray([rid, cls, len(value) + 1, 0x00, 0x00, type_]) + bytearray(value)
    return bytes(body).ljust(64, b"\x00")


def ascii(b):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


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
    print(f"device {path} interface {iface} ({name})  report id {rid}\n")
    fd = os.open(path, os.O_RDWR)
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")
        for cls in range(0x00, 0x60):
            payload = build(cls, 0x00, b"")
            try:
                control(fd, 0x21, 0x09, (2 << 8) | rid, iface, payload, 64, 300)
            except OSError as exc:
                print(f"  SET: {exc.strerror}")
                return
            time.sleep(0.08)
            reply = b""
            if in_ep:
                for _ in range(3):
                    try:
                        data = bulk_read(fd, in_ep, 64, 90)
                    except OSError:
                        break
                    if any(data) and not is_battery(data):
                        reply = data
                        break
            if reply:
                n = reply[2] if len(reply) > 2 else 0
                payload_bytes = reply[6:6 + max(0, n - 1)]
                print(f"class {cls:#04x}: len={n} type={reply[5]:#04x}  {reply[:6+n].hex(' ')}")
                if payload_bytes:
                    print(f"          value: {payload_bytes.hex(' ')}  |{ascii(payload_bytes)}|")
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
