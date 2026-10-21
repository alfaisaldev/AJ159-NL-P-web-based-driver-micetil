#!/usr/bin/env python3
"""Root probe: find the mouse's real command channel over raw USB.

Why root: the vendor's Windows driver talks to this device with
HidD_Get/SetFeature - *feature* reports.  The device's HID descriptor
declares no feature reports, so Linux's hidraw refuses HIDIOCSFEATURE
(EINVAL); we can only send output reports, which the firmware ignores.
Raw usbfs can send SET_REPORT with any report type.

The kernel's usbhid driver owns the interface, so the script unbinds it
(USBDEVFS_DISCONNECT), claims the interface, probes it, and re-binds it
(USBDEVFS_CONNECT) at the end.  If the mouse's hidraw node disappears, just
unplug/replug the mouse.

Everything written is a reversible setting (DPI stage value, report rate).
No flashing, no factory reset, no mode switch.

Run:  sudo python3 tools/usb_feature_test.py
"""
import ctypes
import fcntl
import glob
import os
import sys
import time

VID = 0x7768
TARGETS = {0x6D25: "mouse (wired)", 0x6425: "NearLink dongle"}

SET_REPORT, GET_REPORT = 0x09, 0x01
TYPE_INPUT, TYPE_OUTPUT, TYPE_FEATURE = 1, 2, 3
TYPE_NAME = {1: "Input", 2: "Output", 3: "Feature"}


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
    _fields_ = [
        ("ep", ctypes.c_uint),
        ("len", ctypes.c_uint),
        ("timeout", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]


class DisconnectClaim(ctypes.Structure):
    _fields_ = [
        ("interface", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("driver", ctypes.c_char * 128),
    ]


def _ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


_IOR, _IOW, _IOWR = 2, 1, 3
USBDEVFS_CONTROL = _ioc(_IOWR, ord("U"), 0, ctypes.sizeof(CtrlTransfer))
USBDEVFS_BULK = _ioc(_IOWR, ord("U"), 2, ctypes.sizeof(BulkTransfer))
USBDEVFS_CLAIMINTERFACE = _ioc(_IOR, ord("U"), 15, 4)
USBDEVFS_RELEASEINTERFACE = _ioc(_IOR, ord("U"), 16, 4)
USBDEVFS_DISCONNECT = _ioc(0, ord("U"), 22, 0)
USBDEVFS_CONNECT = _ioc(0, ord("U"), 23, 0)
USBDEVFS_DISCONNECT_CLAIM = _ioc(_IOR, ord("U"), 27, ctypes.sizeof(DisconnectClaim))


def sysfs_unbind(interface_name):
    """Unbind usbhid from an interface via sysfs (the portable way)."""
    for drv in ("usbhid", "usbhid-generic"):
        path = f"/sys/bus/usb/drivers/{drv}/unbind"
        if os.path.exists(path):
            try:
                with open(path, "w") as fh:
                    fh.write(interface_name)
                return drv
            except OSError as exc:
                print(f"    unbind via {drv}: {exc.strerror}")
    return None


def sysfs_bind(interface_name, drv="usbhid"):
    path = f"/sys/bus/usb/drivers/{drv}/bind"
    try:
        with open(path, "w") as fh:
            fh.write(interface_name)
    except OSError as exc:
        print(f"    rebind via {drv}: {exc.strerror}")


def sysfs_device(pid):
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
        return f"/dev/bus/usb/{bus:03d}/{dev:03d}", base
    return None, None


def interfaces(base):
    out = []
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
            out.append((num, eps, os.path.basename(d)))
    return out


def control(fd, req_type, request, value, index, data=b"", length=0, timeout=300):
    buf = (ctypes.c_ubyte * max(length, len(data), 1))()
    if data:
        ctypes.memmove(buf, data, len(data))
    ct = CtrlTransfer(req_type, request, value, index, length, timeout,
                      ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_CONTROL, ct, True)
    return bytes(buf[:length])


def bulk_read(fd, ep, length, timeout=200):
    buf = (ctypes.c_ubyte * length)()
    bt = BulkTransfer(ep, length, timeout, ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_BULK, bt, True)
    return bytes(buf[:length])


def frame_dump(f):
    if len(f) > 5 and f[1] == 0xFA:
        t = f[5]
        extra = ""
        if t == 0x02 and len(f) > 8:
            extra = f" stage={f[6]} dpi={f[7] | (f[8] << 8)}"
        elif t == 0x03:
            extra = f" {f[6] if len(f) > 6 else '?'}%"
        return f"push type={t:#04x}{extra}"
    return "REPLY " + f[:12].hex(" ")


def cks7f(b):
    return sum(b[:len(b) - 1]) & 0x7F


FRAMES = {
    "BS20 TLV dpi":  bytes([0xFA, 0x04, 0x00, 0x00, 0x02, 0x05, 0x80, 0x0C]),
    "BS20 TLV rate": bytes([0xFA, 0x02, 0x00, 0x00, 0x05, 0x02]),
    "IRIS get info": bytes([0x13, 0x00, 0x00]),
    "IRIS get dpi":  bytes([0x19, 0x00, 0x00]),
    "IRIS get cfg":  bytes([0x17, 0x00, 0x00]),
    "AJ rate 500":   bytes([0x04, 0x00, 0x02]),
    "AJ dpi table":  bytes([0x54, 0x00, 0x00, 0x06]) + b"".join(
        bytes([v & 0xFF, v >> 8]) for v in (400, 800, 1200, 1600, 2400, 3200)),
    "AJ dpi +ck":    bytes([0x54, 0x00, 0x00, 0x06]) + b"".join(
        bytes([v & 0xFF, v >> 8]) for v in (400, 800, 1200, 1600, 2400, 3200)) + bytes([0]),
}


def main():
    for pid, label in TARGETS.items():
        path, base = sysfs_device(pid)
        print(f"\n================ {label}  {VID:04x}:{pid:04x} ================")
        if not path:
            print("  not connected")
            continue
        ifs = interfaces(base)
        print(f"  usbfs node: {path}")
        for num, eps, name in ifs:
            print(f"    interface {num} ({name}): endpoints {[hex(e) for e in eps]}")
        fd = os.open(path, os.O_RDWR)
        vendor = [n for n, _, _ in ifs if n == 1] or [n for n, _, _ in ifs]
        iface = vendor[0]
        iface_name = dict((n, name) for n, _, name in ifs)[iface]
        eps = dict((n, e) for n, e, _ in ifs)[iface]
        in_ep = next((e for e in eps if e & 0x80), None)
        connected = False
        driver = None
        try:
            driver = sysfs_unbind(iface_name)
            if driver:
                print(f"  unbound {driver} from interface {iface} ({iface_name})")
                connected = True
            else:
                try:
                    dc = DisconnectClaim()
                    dc.interface = iface
                    fcntl.ioctl(fd, USBDEVFS_DISCONNECT_CLAIM, dc, True)
                    print(f"  disconnect-and-claimed interface {iface}")
                    connected = True
                except OSError as exc:
                    print(f"  disconnect-claim: {exc.strerror} ({exc.errno})")
            try:
                arg = (ctypes.c_uint * 1)(iface)
                fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
                print(f"  claimed interface {iface}")
            except OSError as exc:
                print(f"  claim interface: {exc.strerror} ({exc.errno})")

            print("\n  -- which report types does the device answer? --")
            for rtype in (TYPE_FEATURE, TYPE_OUTPUT, TYPE_INPUT):
                for rid, ln in ((6, 63), (7, 9), (8, 2)):
                    try:
                        resp = control(fd, 0xA1, GET_REPORT, (rtype << 8) | rid,
                                       iface, b"", ln, 300)
                    except OSError as exc:
                        print(f"    GET {TYPE_NAME[rtype]:7} id {rid}: {exc.strerror}")
                        continue
                    mark = "*** ANSWERS ***" if any(resp) else "empty"
                    print(f"    GET {TYPE_NAME[rtype]:7} id {rid}: {mark}  {resp[:20].hex(' ')}")

            print("\n  -- sending candidate commands --")
            for rtype in (TYPE_FEATURE, TYPE_OUTPUT):
                for rid, ln in ((6, 63), (7, 9)):
                    for name, body in FRAMES.items():
                        payload = body.ljust(ln, b"\x00")
                        try:
                            control(fd, 0x21, SET_REPORT, (rtype << 8) | rid, iface,
                                    payload, ln, 300)
                        except OSError as exc:
                            print(f"    SET {TYPE_NAME[rtype]:7} id {rid} {name:14}: {exc.strerror}")
                            continue
                        time.sleep(0.1)
                        if in_ep:
                            try:
                                data = bulk_read(fd, in_ep, 64, 200)
                                if any(data):
                                    print(f"    SET {TYPE_NAME[rtype]:7} id {rid} {name:14}"
                                          f" -> {frame_dump(data)}")
                            except OSError:
                                pass
            if in_ep:
                print("\n  -- passive listen (5 s) --")
                end = time.time() + 5
                while time.time() < end:
                    try:
                        data = bulk_read(fd, in_ep, 64, 300)
                    except OSError:
                        break
                    if any(data):
                        print(f"    {frame_dump(data)}")
        finally:
            try:
                arg = (ctypes.c_uint * 1)(iface)
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
            except OSError:
                pass
            if connected:
                if driver:
                    sysfs_bind(iface_name, driver)
                    print(f"  re-bound {driver} to interface {iface}")
                else:
                    try:
                        fcntl.ioctl(fd, USBDEVFS_CONNECT, iface, True)
                        print(f"  re-bound the kernel driver to interface {iface}")
                    except OSError as exc:
                        print(f"  connect failed: {exc.strerror} (unplug/replug the device)")
            os.close(fd)
    print("\nDone.")


if __name__ == "__main__":
    main()
