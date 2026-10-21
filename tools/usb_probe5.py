#!/usr/bin/env python3
"""Send the vendor driver's exact probe sequence and listen everywhere.

The driver, right after opening the device, sends

    06 05 00 00 00 00 …   (63 bytes)   x5, 20 ms apart

and then reads the reply from the HID handle.  This script does the same over
raw USB and listens on *both* interrupt endpoints of the device (interface 0
and interface 1) for several seconds, printing every frame it sees.

Run: sudo python3 tools/usb_probe5.py [pid]
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


def main():
    pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6D25
    path, ifs = device(pid)
    if not path:
        print("device not found")
        return
    vendor = next((n for n, _, _ in ifs if n == 1), 0)
    name = next(nm for n, _, nm in ifs if n == vendor)
    endpoints = []
    for n, eps, nm in ifs:
        for e in eps:
            if e & 0x80:
                endpoints.append((e, f"iface{n}"))
    print(f"device {path}")
    for n, eps, nm in ifs:
        print(f"  interface {n} ({nm}): endpoints {[hex(e) for e in eps]}")
    drv = unbind(name)
    if not drv:
        print("could not unbind usbhid")
        return
    print(f"unbound {drv} from {name}")
    fd = os.open(path, os.O_RDWR)
    try:
        arg = (ctypes.c_uint * 1)(vendor)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {vendor}\n")

        for rid, ln in ((6, 63), (7, 9), (8, 12)):
            probe = bytes([0x05] + [0x00] * (ln - 1))
            for _ in range(5):
                try:
                    control(fd, 0x21, SET_REPORT, (2 << 8) | rid, vendor, probe, ln, 300)
                except OSError as exc:
                    print(f"  probe id {rid}: {exc.strerror}")
                    break
                time.sleep(0.02)
            print(f"-- report {rid}: probe sent, listening 4 s on {endpoints}")
            end = time.time() + 4
            while time.time() < end:
                for ep, tag in endpoints:
                    try:
                        data = bulk_read(fd, ep, 64, 150)
                    except OSError:
                        continue
                    if any(data):
                        print(f"   [{tag} {hex(ep)}] {data[:16].hex(' ')}", flush=True)
    finally:
        try:
            arg = (ctypes.c_uint * 1)(vendor)
            fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
        except OSError:
            pass
        os.close(fd)
        rebind(name, drv)
        print(f"re-bound {drv}")


if __name__ == "__main__":
    main()
