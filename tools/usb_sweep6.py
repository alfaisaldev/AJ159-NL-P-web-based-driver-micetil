#!/usr/bin/env python3
"""Test the 'report id inside the data' hypothesis.

The firmware's frame builder writes the report id into byte 0 of the frame it
*sends* (see `sb s1,0x10(sp)` in the builder).  If the receive path is
symmetric, the host's data must therefore *contain* the report id as its
first byte, i.e.

    [0x06][class][len][0][0][type][data]

whereas if the USB stack prepends the id for us, the correct frame is

    [class][len][0][0][type][data]

We have only ever tried the second form.  This script sends both forms for
the driver's classes and reports every reply.

Run: sudo python3 tools/usb_sweep6.py [pid]
"""
import ctypes
import fcntl
import glob
import os
import sys
import time

VID = 0x7768


class CtrlTransfer(ctypes.Structure):
    _fields_ = [("bRequestType", ctypes.c_ubyte), ("bRequest", ctypes.c_ubyte),
                ("wValue", ctypes.c_ushort), ("wIndex", ctypes.c_ushort),
                ("wLength", ctypes.c_ushort), ("timeout", ctypes.c_uint32),
                ("data", ctypes.c_void_p)]


class BulkTransfer(ctypes.Structure):
    _fields_ = [("ep", ctypes.c_uint), ("len", ctypes.c_uint),
                ("timeout", ctypes.c_uint), ("data", ctypes.c_void_p)]


def _ioc(d, t, n, s):
    return (d << 30) | ((s & 0xFFFF) << 16) | ((t & 0xFF) << 8) | (n & 0xFF)


USBDEVFS_CONTROL = _ioc(3, ord("U"), 0, ctypes.sizeof(CtrlTransfer))
USBDEVFS_BULK = _ioc(3, ord("U"), 2, ctypes.sizeof(BulkTransfer))
USBDEVFS_CLAIMINTERFACE = _ioc(2, ord("U"), 15, 4)
USBDEVFS_RELEASEINTERFACE = _ioc(2, ord("U"), 16, 4)
SET_REPORT = 0x09
REPORT_LEN = {6: 63, 7: 9, 8: 12}


def device(pid):
    for base in sorted(glob.glob("/sys/bus/usb/devices/*")):
        try:
            with open(os.path.join(base, "idVendor")) as fh:
                vid = int(fh.read().strip(), 16)
            with open(os.path.join(base, "idProduct")) as fh:
                p = int(fh.read().strip(), 16)
        except OSError:
            continue
        if vid != VID or p != pid:
            continue
        with open(os.path.join(base, "busnum")) as fh:
            bus = int(fh.read().strip())
        with open(os.path.join(base, "devnum")) as fh:
            dev = int(fh.read().strip())
        ifs = []
        for d in sorted(glob.glob(base + ":*")):
            f = os.path.join(d, "bInterfaceNumber")
            if os.path.exists(f):
                with open(f) as fh:
                    num = int(fh.read().strip())
                eps = []
                for e in sorted(glob.glob(os.path.join(d, "ep_*"))):
                    try:
                        with open(os.path.join(e, "bEndpointAddress")) as fh:
                            eps.append(int(fh.read().strip(), 16))
                    except OSError:
                        pass
                ifs.append((num, eps, os.path.basename(d)))
        return f"/dev/bus/usb/{bus:03d}/{dev:03d}", ifs
    return None, []


def control(fd, rt, req, value, index, data=b"", length=0, timeout=300):
    buf = (ctypes.c_ubyte * max(length, len(data), 1))()
    if data:
        ctypes.memmove(buf, data, len(data))
    ct = CtrlTransfer(rt, req, value, index, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_CONTROL, ct, True)
    return bytes(buf[:length])


def bulk_read(fd, ep, length, timeout=100):
    buf = (ctypes.c_ubyte * length)()
    bt = BulkTransfer(ep, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_BULK, bt, True)
    return bytes(buf[:length])


def unbind(name):
    for drv in ("usbhid", "usbhid-generic"):
        p = f"/sys/bus/usb/drivers/{drv}/unbind"
        if os.path.exists(p):
            try:
                with open(p, "w") as fh:
                    fh.write(name)
                return drv
            except OSError:
                pass
    return None


def rebind(name, drv="usbhid"):
    try:
        with open(f"/sys/bus/usb/drivers/{drv}/bind", "w") as fh:
            fh.write(name)
    except OSError as exc:
        print(f"  rebind failed: {exc.strerror}")


def is_battery(f):
    return len(f) > 5 and f[1] == 0xFA and f[5] == 0x03 and f[6] == 0x64


CLASSES = [0x05, 0x07, 0x10, 0x11, 0x31, 0x06, 0x13, 0x12, 0x30, 0x00, 0x01, 0x02,
           0x03, 0x04, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]
TYPES = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]


def payload_for(t):
    if t == 0x02:
        return bytes([0x05, 0x80, 0x0C])
    if t in (0x04, 0x05):
        return bytes([0x02])
    return bytes([0x00, 0x00, 0x00])


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6D25
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
        print("could not unbind usbhid (another probe running?)")
        return
    print(f"device {path} interface {iface} ({name}) in-endpoint {hex(in_ep) if in_ep else None}")
    fd = os.open(path, os.O_RDWR)
    hits = []
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}\n")
        for rid in (6, 7, 8):
            ln = REPORT_LEN[rid]
            for prefixed in (True, False):
                for cls in CLASSES:
                    for t in TYPES:
                        pl = payload_for(t)
                        core = bytes([cls, len(pl) + 1, 0x00, 0x00, t]) + pl
                        body = (bytes([rid]) + core) if prefixed else core
                        payload = body.ljust(ln, b"\x00")[:ln]
                        try:
                            control(fd, 0x21, SET_REPORT, (2 << 8) | rid, iface,
                                    payload, ln, 300)
                        except OSError as exc:
                            print(f"  SET id {rid}: {exc.strerror}")
                            break
                        time.sleep(0.04)
                        if in_ep:
                            for _ in range(2):
                                try:
                                    data = bulk_read(fd, in_ep, 64, 80)
                                except OSError:
                                    break
                                if any(data) and not is_battery(data):
                                    print(f"  *** HIT id {rid} "
                                          f"{'prefixed' if prefixed else 'plain'} "
                                          f"class {cls:#04x} type {t:#04x}: "
                                          f"raw={data[:16].hex(' ')}", flush=True)
                                    hits.append((rid, prefixed, cls, t, data[:16].hex(" ")))
                print(f"  report {rid} {'prefixed' if prefixed else 'plain'} done", flush=True)
        print("\nHITS:", hits)
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
