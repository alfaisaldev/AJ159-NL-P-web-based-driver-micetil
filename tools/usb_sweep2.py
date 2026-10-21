#!/usr/bin/env python3
"""Second raw-USB sweep: the other candidate frame dialects.

The first sweep used the BS20 TLV shape [hdr, len, 0, 0, type, value].
This one tries the shapes documented for the neighbouring vendor families:

  IRIS-v2 NearLink : [cmd, LEN, data...]        (get = [cmd, 0, 0])
  AJ-series 0x3151 : [cmd, payload...] + checksum (sum of body[1..62]) & 0x7f
  BS20 reply-style : [hdr|0x80, len, 0, 0, type, value...]

Oracle: the mouse pushes telemetry whenever its state changes, so anything
on the interrupt endpoint other than the periodic battery frame is a hit.

Run: sudo python3 tools/usb_sweep2.py [pid]
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


def describe(f):
    if len(f) > 5 and f[1] == 0xFA:
        t = f[5]
        if t == 0x02 and len(f) > 8:
            return f"DPI stage={f[6]} dpi={f[7] | (f[8] << 8)}"
        if t == 0x03:
            return f"battery {f[6] if len(f) > 6 else '?'}%"
        return f"push type={t:#04x} {f[6:9].hex(' ')}"
    return "reply " + f[:12].hex(" ")


def cks7f(body):
    """AJ-series checksum: sum of the body bytes, 7 bits."""
    return sum(body[:61]) & 0x7F


def build_cases():
    cases = []

    # IRIS-v2 style: [cmd, 0, 0] and [cmd, LEN, data]
    for cmd in (0x12, 0x13, 0x14, 0x15, 0x17, 0x19, 0x1B, 0x1C, 0x1D, 0x28, 0x30):
        cases.append((f"IRIS get {cmd:#04x}", bytes([cmd, 0x00, 0x00])))
    # IRIS set mouse config: wireless rate, usb rate, max dpi, current dpi ...
    cfg = bytearray(30)
    cfg[0] = 0x02      # usb report rate = 1000 Hz
    cfg[1] = 0x02
    cfg[2] = 0x80      # max dpi 12800
    cfg[3] = 0x00      # current dpi index
    cases.append(("IRIS set cfg", bytes([0x18, 30]) + bytes(cfg)))
    # IRIS set dpi config: 6 levels x (u16 dpi + rgb + pad)
    dpi = bytearray()
    for v in (400, 800, 1200, 1600, 2400, 3200):
        dpi += bytes([v & 0xFF, v >> 8, 0, 0, 0, 0, 0, 0])
    cases.append(("IRIS set dpi", bytes([0x1A, 48]) + bytes(dpi)))
    # IRIS set rgb (not supported by this mouse, but cheap to try)
    cases.append(("IRIS set rgb", bytes([0x28, 0x04, 0x04, 0x10, 0x10, 0x10, 0x02])))

    # AJ-series style with the BIT7 checksum
    for code, hz in ((0x08, 125), (0x04, 250), (0x02, 500), (0x01, 1000)):
        b = bytearray([0x04, 0x00, code])
        b = bytearray(b.ljust(62, b"\x00"))
        b[61] = cks7f(b)
        cases.append((f"AJ rate {hz}Hz", bytes(b)))
    b = bytearray([0x54, 0x00, 0x00, 0x06])
    for v in (400, 800, 1200, 1600, 2400, 3200):
        b += bytes([v & 0xFF, v >> 8])
    b = bytearray(b.ljust(62, b"\x00"))
    b[61] = cks7f(b)
    cases.append(("AJ dpi table", bytes(b)))
    b2 = bytearray(b)
    b2[61] = 0
    cases.append(("AJ dpi nocks", bytes(b2)))

    # BS20 TLV with the reply-direction header (cmd | 0x80)
    for cmd in (0x02, 0x10, 0x15, 0x36, 0x00, 0x0B, 0x0F):
        h = cmd | 0x80
        cases.append((f"BS20 hdr {h:#04x} dpi", bytes([h, 0x04, 0x00, 0x00, 0x02, 0x05, 0x80, 0x0C])))
        cases.append((f"BS20 hdr {h:#04x} rate", bytes([h, 0x02, 0x00, 0x00, 0x05, 0x02])))

    # and the plain TLV, for completeness
    for h in (0xFA, 0x02, 0x10, 0x15, 0x36):
        cases.append((f"BS20 hdr {h:#04x} dpi", bytes([h, 0x04, 0x00, 0x00, 0x02, 0x05, 0x80, 0x0C])))
        cases.append((f"BS20 hdr {h:#04x} rate", bytes([h, 0x02, 0x00, 0x00, 0x05, 0x02])))
    return cases


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
        cases = build_cases()
        print(f"{len(cases)} candidate frames")
        for rtype, rname in ((3, "Feature"), (2, "Output")):
            for rid, ln in ((6, 63), (7, 9)):
                for label, body in cases:
                    payload = body.ljust(ln, b"\x00")[:ln]
                    try:
                        control(fd, 0x21, SET_REPORT, (rtype << 8) | rid, iface, payload, ln, 300)
                    except OSError as exc:
                        print(f"  SET {rname} id {rid} {label}: {exc.strerror}")
                        break
                    time.sleep(0.06)
                    if in_ep:
                        for _ in range(2):
                            try:
                                data = bulk_read(fd, in_ep, 64, 120)
                            except OSError:
                                break
                            if any(data) and not (data[1] == 0xFA and data[5] == 0x03):
                                print(f"  *** HIT {rname} id {rid} {label}: "
                                      f"{describe(data)} raw={data[:12].hex(' ')}", flush=True)
                                hits.append((rname, rid, label, data[:12].hex(" ")))
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
