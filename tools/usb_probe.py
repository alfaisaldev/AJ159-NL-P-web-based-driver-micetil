#!/usr/bin/env python3
"""Talk to the mouse over raw USB (usbfs) instead of hidraw.

hidraw refuses SET_FEATURE for a device whose descriptor declares no feature
reports, and the Windows driver uses exactly HidD_Get/SetFeature.  Raw USB
lets us send SET_REPORT with *any* report type, so we can find out which
request the mouse actually listens on.

Needs write access to the usbfs node -> run with pkexec.

Usage: sudo python3 tools/usb_probe.py [vid] [pid]
"""
import ctypes
import fcntl
import glob
import os
import select
import struct
import sys
import time

VID = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x7768
PID = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x6D25

SET_REPORT = 0x09
GET_REPORT = 0x01
TYPE_INPUT, TYPE_OUTPUT, TYPE_FEATURE = 1, 2, 3


class CtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("requestType", ctypes.c_uint32),
        ("request", ctypes.c_uint32),
        ("value", ctypes.c_uint32),
        ("index", ctypes.c_uint32),
        ("length", ctypes.c_uint32),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


def _ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


USBDEVFS_CONTROL = _ioc(2, ord("U"), 0, ctypes.sizeof(CtrlTransfer))
USBDEVFS_CLAIMINTERFACE = _ioc(3, ord("U"), 15, 4)
USBDEVFS_RELEASEINTERFACE = _ioc(3, ord("U"), 16, 4)
USBDEVFS_GET_DESCRIPTOR = _ioc(2, ord("U"), 2, ctypes.sizeof(CtrlTransfer))


def usb_nodes():
    out = []
    for path in glob.glob("/dev/bus/usb/*/*"):
        try:
            vid, pid = path.split("/")[-2:]
            with open(f"/sys/bus/usb/devices/{vid}:{pid}/idVendor") as fh:
                v = int(fh.read().strip(), 16)
            with open(f"/sys/bus/usb/devices/{vid}:{pid}/idProduct") as fh:
                p = int(fh.read().strip(), 16)
        except OSError:
            continue
        if v == VID and p == PID:
            out.append((path, f"{vid}:{pid}"))
    return out


def interfaces(path):
    """Return the interface numbers of the device."""
    bus, dev = path.split("/")[-2:]
    base = f"/sys/bus/usb/devices/{bus}:{dev}"
    ifs = []
    for d in sorted(glob.glob(base + ":*")):
        if os.path.exists(os.path.join(d, "bInterfaceNumber")):
            with open(os.path.join(d, "bInterfaceNumber")) as fh:
                ifs.append(int(fh.read().strip()))
    return ifs


def control(fd, req_type, request, value, index, data, length=None, timeout=300):
    buf = (ctypes.c_ubyte * max(len(data), length or 0))()
    ctypes.memmove(buf, data, len(data))
    ct = CtrlTransfer(req_type, request, value, index, length if length is not None else len(data),
                      timeout, ctypes.cast(buf, ctypes.c_void_p))
    fcntl.ioctl(fd, USBDEVFS_CONTROL, ct, True)
    return bytes(buf[:length if length is not None else len(data)])


def main():
    nodes = usb_nodes()
    if not nodes:
        print(f"no USB device {VID:04x}:{PID:04x} found")
        return
    path, desc = nodes[0]
    print(f"device: {path} ({desc})")
    ifs = interfaces(path)
    print(f"interfaces: {ifs}")
    fd = os.open(path, os.O_RDWR)
    try:
        for iface in ifs:
            try:
                fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, iface, True)
                print(f"claimed interface {iface}")
            except OSError as exc:
                print(f"claim interface {iface} failed: {exc}")
        for iface in ifs:
            for rtype, rname in ((TYPE_FEATURE, "Feature"), (TYPE_OUTPUT, "Output"), (TYPE_INPUT, "Input")):
                for rid in (6, 7, 8, 0):
                    length = {6: 63, 7: 9, 8: 2, 0: 63}[rid]
                    # GET_REPORT first (harmless read)
                    try:
                        resp = control(fd, 0xA1, GET_REPORT, (rtype << 8) | rid, iface, b"", length, 300)
                        interesting = any(resp)
                        print(f"  iface{iface} GET {rname:7} id {rid}: {'data' if interesting else 'empty'} {resp[:16].hex(' ')}")
                    except OSError as exc:
                        print(f"  iface{iface} GET {rname:7} id {rid}: error {exc.strerror}")
    finally:
        for iface in ifs:
            try:
                fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, iface, True)
            except OSError:
                pass
        os.close(fd)


if __name__ == "__main__":
    main()
