#!/usr/bin/env python3
"""Read and write the device's config blocks on the hidden report id 0 channel.

Classes that return data (from the reply map):

    0x05  36 bytes  type 0x01   identity / info block
    0x07   6 bytes  type 0x01   short info block
    0x0f   2 bytes  type 0xff   ?
    0x10  36 bytes  type 0x10   config block (flags + values)
    0x11  36 bytes  type 0x05   second config block (zeros -> the DPI table)

Frame layout:  [0] reply-report-id  [1] class  [2] len  [3] 0  [4] 0  [5] type
               [6..] value

Run: sudo python3 tools/config_rw.py [pid] [report_id]
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
BLOCKS = [0x05, 0x07, 0x0F, 0x10, 0x11, 0x06, 0x12, 0x30, 0x31]


def build(cls, type_, value=b""):
    body = bytearray([RID, cls, len(value) + 1, 0x00, 0x00, type_]) + bytearray(value)
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

        def request(cls, type_=0x00, value=b"", wait=0.12):
            control(fd, 0x21, 0x09, (2 << 8) | rid, iface, build(cls, type_, value), 64, 300)
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

        print("== read ==")
        blocks = {}
        for cls in BLOCKS:
            r = request(cls)
            if r:
                n = r[2]
                val = r[6:6 + max(0, n - 1)]
                blocks[cls] = val
                print(f"  class {cls:#04x}: type={r[5]:#04x} len={n}  {val.hex(' ')}")
                if val:
                    print(f"              |{ascii(val)}|")
            else:
                print(f"  class {cls:#04x}: (no reply)")

        # --- try writing the config blocks back with one byte changed ---
        print("\n== write test (class 0x11 / 0x10, one byte toggled) ==")
        for cls in (0x11, 0x10, 0x07, 0x05):
            base = blocks.get(cls)
            if not base:
                continue
            for off in range(0, min(len(base), 12)):
                mod = bytearray(base)
                mod[off] ^= 0xFF
                r = request(cls, 0x00, bytes(mod))
                if r:
                    n = r[2]
                    val = r[6:6 + max(0, n - 1)]
                    changed = val != base
                    if changed:
                        print(f"  class {cls:#04x} byte {off}: {base.hex(' ')} -> {val.hex(' ')}  *** CHANGED ***")
                        # write the original back
                        request(cls, 0x00, bytes(base))
                        break
        print("\ndone")
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
