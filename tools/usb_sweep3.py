#!/usr/bin/env python3
"""Third raw-USB sweep: the report ids and lengths we have not tried.

Ideas tested here:
  * report id 8  - the 2-byte "page 1" output report (a compact command
                   register?).  We sweep every [a, b] pair.
  * report id 7  - the 9-byte output report.
  * report id 6 sent with the *exact* message length instead of a padded
    63 bytes - the firmware logs "msg_len", so it may reject a report whose
    length does not match the message it contains.

Oracle: any frame on the interrupt endpoint that is not the periodic
battery push.

Run: sudo python3 tools/usb_sweep3.py [pid]
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


def bulk_read(fd, ep, length, timeout=120):
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

    def probe(label, rid, payload, rtype=3):
        try:
            control(fd, 0x21, SET_REPORT, (rtype << 8) | rid, iface, payload, len(payload), 300)
        except OSError as exc:
            print(f"  SET id {rid} {label}: {exc.strerror}")
            return
        time.sleep(0.05)
        if in_ep:
            for _ in range(2):
                try:
                    data = bulk_read(fd, in_ep, 64, 100)
                except OSError:
                    return
                if any(data) and not (data[1] == 0xFA and data[5] == 0x03):
                    print(f"  *** HIT id {rid} len {len(payload)} {label}: "
                          f"{describe(data)} raw={data[:12].hex(' ')}", flush=True)
                    hits.append((rid, label, data[:12].hex(" ")))

    try:
        arg = (ctypes.c_uint * 1)(iface)
        fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
        print(f"claimed interface {iface}")

        print("\n-- report id 8: every 2-byte pair --")
        for a in range(0x00, 0x100):
            for b in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x08, 0x10, 0x20, 0x40, 0x80):
                probe(f"[{a:#04x},{b:#04x}]", 8, bytes([a, b]))
            if a % 32 == 0:
                print(f"   ...{a:#04x}", flush=True)

        print("\n-- report id 7 (9 bytes): TLV shapes --")
        for h in (0xFA, 0x02, 0x10, 0x15, 0x36, 0x00, 0x7A):
            for t in range(0x01, 0x09):
                pl = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02, 0x00, 0x00])
                probe(f"hdr {h:#04x} type {t:#04x}", 7, bytes([h, len(pl) + 1, 0, 0, t]) + pl)

        print("\n-- report id 6 with the exact message length --")
        for h in (0xFA, 0x02, 0x10, 0x15, 0x36, 0x7A, 0x00):
            for t in range(0x01, 0x09):
                pl = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02])
                body = bytes([h, len(pl) + 1, 0, 0, t]) + pl
                probe(f"hdr {h:#04x} type {t:#04x}", 6, body)
                probe(f"hdr {h:#04x} type {t:#04x} +ck", 6,
                      body + bytes([sum(body) & 0xFF]))

        print("\n-- undeclared report ids 0 and 5 --")
        for rid in (0, 5):
            for h in (0xFA, 0x02, 0xF7, 0x00):
                for t in (0x02, 0x05):
                    pl = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02])
                    body = bytes([h, len(pl) + 1, 0, 0, t]) + pl
                    probe(f"id {rid} hdr {h:#04x} type {t:#04x}", rid, body)
            for c in range(0x00, 0x100):
                probe(f"id {rid} cmd {c:#04x}", rid, bytes([c, 0x00, 0x00]))

        print("\n-- magic byte prefix --")
        for magic in (0x55, 0xAA, 0x5A, 0xA5, 0xCC, 0x0F, 0xAE, 0xFA):
            for h in (0x00, 0x02, 0x10, 0x15, 0x36):
                for t in (0x02, 0x05):
                    pl = bytes([0x05, 0x80, 0x0C]) if t == 0x02 else bytes([0x02])
                    body = bytes([magic, h, len(pl) + 1, 0, 0, t]) + pl
                    probe(f"magic {magic:#04x} hdr {h:#04x} type {t:#04x}", 6, body)

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
