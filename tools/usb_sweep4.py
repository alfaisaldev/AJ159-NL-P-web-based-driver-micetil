#!/usr/bin/env python3
"""Raw-USB sweep using the vendor's own command scheme.

The vendor's (reversed) driver for the sibling keyboards uses:

    request : [0] 0xAA magic  [1] cmd  [2] len  [3..4] addr  [5..7] hdr  [8..] payload
    response: [0] 0x55 magic  [1] cmd echo  [2] lenOrType  [3..4] addr  [8..] data

and its command enum contains 0xFA = GET_DEVICE_NOTIFY - which is exactly the
header of the mouse's telemetry frames (06 fa 03 00 00 03 64 02).  The mouse
firmware's own parser shows the received frame is

    [0] report id   [1] cmd   [2] len   [3..] payload

so a host request is [id][cmd][len][payload...].  This sweep tries every
command id in that shape (and with the keyboard's magic bytes) and reports
ANY frame the device sends back that is not the periodic battery notification.

Run: sudo python3 tools/usb_sweep4.py [pid]
"""
import ctypes
import errno
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


def bulk_read(fd, ep, length, timeout=100):
    buf = (ctypes.c_ubyte * length)()
    bt = BulkTransfer(ep, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_BULK, bt, True)
    return bytes(buf[:length])


def unbind(name):
    """Unbind usbhid from an interface.  Tolerates an already-unbound one."""
    for drv in ("usbhid", "usbhid-generic"):
        p = f"/sys/bus/usb/drivers/{drv}/unbind"
        if os.path.exists(p):
            try:
                with open(p, "w") as fh:
                    fh.write(name)
                return drv
            except OSError as exc:
                if exc.errno in (errno.ENODEV, errno.EINVAL, errno.ENXIO):
                    # not bound to that driver any more - fine
                    if not any(os.path.basename(d) == name
                               for d in glob.glob(f"/sys/bus/usb/drivers/{drv}/*")):
                        return drv
                else:
                    print(f"    unbind via {drv}: {exc.strerror}")
    return None


def rebind(name, drv="usbhid"):
    try:
        with open(f"/sys/bus/usb/drivers/{drv}/bind", "w") as fh:
            fh.write(name)
    except OSError as exc:
        print(f"  rebind failed: {exc.strerror}")


def is_battery(f):
    return len(f) > 5 and f[1] == 0xFA and f[5] == 0x03 and f[6] in (0x64,)


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
        print("could not unbind usbhid")
        return
    print(f"device {path} interface {iface} ({name}) in-endpoint {hex(in_ep) if in_ep else None}")
    fd = os.open(path, os.O_RDWR)
    hits = []
    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}")

        def probe(label, payload, rtype=3, rid=6):
            try:
                control(fd, 0x21, SET_REPORT, (rtype << 8) | rid, iface, payload, len(payload), 300)
            except OSError as exc:
                print(f"  SET id {rid} {label}: {exc.strerror}")
                return
            time.sleep(0.04)
            if in_ep:
                for _ in range(3):
                    try:
                        data = bulk_read(fd, in_ep, 64, 80)
                    except OSError:
                        return
                    if any(data) and not is_battery(data):
                        print(f"  *** HIT id {rid} {label}: raw={data[:16].hex(' ')}", flush=True)
                        hits.append((label, data[:16].hex(" ")))

        shapes = {
            "cmd only":        lambda c: bytes([c]),
            "cmd+len":         lambda c: bytes([c, 0x00]),
            "cmd+len+addr":    lambda c: bytes([c, 0x00, 0x00, 0x00]),
            "cmd+len+addr+3":  lambda c: bytes([c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
            "AA+cmd+len":      lambda c: bytes([0xAA, c, 0x00, 0x00, 0x00]),
            "55+cmd+len":      lambda c: bytes([0x55, c, 0x00, 0x00, 0x00]),
            "F5+cmd+len":      lambda c: bytes([0xF5, c, 0x00, 0x00, 0x00]),
            "FA+cmd+len":      lambda c: bytes([0xFA, c, 0x00, 0x00, 0x00]),
        }
        for sname, mk in shapes.items():
            print(f"\n-- shape: {sname} --", flush=True)
            for c in range(0x01, 0x100):
                probe(f"{sname} cmd {c:#04x}", mk(c))
            print(f"   {sname} done", flush=True)
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
