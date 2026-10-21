#!/usr/bin/env python3
"""Sweep host->mouse command frames over raw USB, using the mouse's own
telemetry as the oracle.

The mouse pushes a telemetry frame whenever its state changes - a DPI change
arrives as a type 0x02 frame.  So: send a candidate frame, watch the
interrupt endpoint, and report anything that is not the periodic battery
push.  A hit means the frame was understood.

Needs root (usbfs + unbinding usbhid from the vendor interface).

Run: sudo python3 tools/usb_sweep.py
"""
import ctypes
import fcntl
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from battery import claim_device  # noqa: E402  (kept for the import path)

VID = 0x7768
PIDS = {0x6D25: "mouse (wired)", 0x6425: "NearLink dongle"}
SET_REPORT, GET_REPORT = 0x09, 0x01
TYPE_INPUT, TYPE_OUTPUT, TYPE_FEATURE = 1, 2, 3


class CtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_ubyte),
        ("bRequest", ctypes.c_ubyte),
        ("wValue", ctypes.c_ushort),
        ("wIndex", ctypes.c_ushort),
        ("wLength", ctypes.c_ushort),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


class BulkTransfer(ctypes.Structure):
    _fields_ = [("ep", ctypes.c_uint), ("len", ctypes.c_uint),
                ("timeout", ctypes.c_uint), ("data", ctypes.c_void_p)]


def _ioc(d, t, n, s):
    return (d << 30) | ((s & 0xFFFF) << 16) | ((t & 0xFF) << 8) | (n & 0xFF)


USBDEVFS_CONTROL = _ioc(3, ord("U"), 0, ctypes.sizeof(CtrlTransfer))
USBDEVFS_BULK = _ioc(3, ord("U"), 2, ctypes.sizeof(BulkTransfer))
USBDEVFS_CLAIMINTERFACE = _ioc(2, ord("U"), 15, 4)
USBDEVFS_RELEASEINTERFACE = _ioc(2, ord("U"), 16, 4)


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


def bulk_read(fd, ep, length, timeout=200):
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


def describe(f):
    if len(f) > 5 and f[1] == 0xFA:
        t = f[5]
        if t == 0x02 and len(f) > 8:
            return f"DPI stage={f[6]} dpi={f[7] | (f[8] << 8)}"
        if t == 0x03:
            return f"battery {f[6] if len(f) > 6 else '?'}%"
        return f"push type={t:#04x} {f[6:9].hex(' ')}"
    return "reply " + f[:12].hex(" ")


def payload_for(t):
    if t == 0x02:      # DPI: stage + u16 (3200 = a factory value, safe)
        return bytes([0x05, 0x80, 0x0C])
    if t == 0x03:      # battery
        return bytes([0x64, 0x02])
    return bytes([0x00, 0x00, 0x00])


HEADERS = [0xFA, 0x02, 0x7A, 0x10, 0x15, 0x36, 0x82, 0x90, 0x92, 0x95, 0xB6,
           0x6C, 0x56, 0x76, 0x00, 0x01, 0x03, 0x04, 0x05, 0x07, 0x0B, 0x0F,
           0x45, 0x1A, 0x12, 0x13, 0x17, 0x19, 0x1A, 0x28, 0x30]
TYPES = [0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08]     # 0x06 = mode, skipped


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
    print(f"device {path}  interface {iface} ({name})  in-endpoint {hex(in_ep) if in_ep else None}")

    drv = unbind(name)
    if not drv:
        print("could not unbind usbhid")
        return
    print(f"unbound {drv}")
    fd = os.open(path, os.O_RDWR)
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}")

        hits = []
        for rtype, rname in ((TYPE_FEATURE, "Feature"), (TYPE_OUTPUT, "Output")):
            for h in HEADERS:
                for t in TYPES:
                    pl = payload_for(t)
                    body = bytes([h, len(pl) + 1, 0x00, 0x00, t]) + pl
                    payload = body.ljust(63, b"\x00")
                    try:
                        control(fd, 0x21, SET_REPORT, (rtype << 8) | 6, iface, payload, 63, 300)
                    except OSError as exc:
                        print(f"  SET {rname} hdr {h:#04x} type {t:#04x}: {exc.strerror}")
                        break
                    time.sleep(0.05)
                    if in_ep:
                        for _ in range(2):
                            try:
                                data = bulk_read(fd, in_ep, 64, 120)
                            except OSError:
                                break
                            if any(data) and not (data[1] == 0xFA and data[5] == 0x03):
                                print(f"  *** HIT {rname} hdr {h:#04x} type {t:#04x}: "
                                      f"{describe(data)}  raw={data[:12].hex(' ')}", flush=True)
                                hits.append((rname, h, t, data[:12].hex(" ")))
            print(f"  {rname} done", flush=True)
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
