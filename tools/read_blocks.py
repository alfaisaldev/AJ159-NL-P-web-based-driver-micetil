#!/usr/bin/env python3
"""Read-only dump of the mouse's config blocks (no writes at all)."""
import ctypes, fcntl, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.usb_sweep7 import (control, bulk_read, unbind, rebind, device, is_battery,
                             USBDEVFS_CLAIMINTERFACE, USBDEVFS_RELEASEINTERFACE)
RID = 0x06
def build(cls, action=0x00, value=b""):
    b = bytearray([RID, cls, len(value)+1, 0, 0, action]) + bytearray(value)
    return bytes(b).ljust(64, b"\x00")
pid = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x6d25
path, ifs = device(pid)
iface = next((n for n,_,_ in ifs if n==1), 0)
name = next(nm for n,_,nm in ifs if n==iface)
eps = dict((n,e) for n,e,_ in ifs)[iface]
in_ep = next((e for e in eps if e & 0x80), None)
drv = unbind(name); fd = os.open(path, os.O_RDWR)
try:
    arg=(ctypes.c_uint*1)(iface); fcntl.ioctl(fd, USBDEVFS_CLAIMINTERFACE, arg, True)
    print(f"device {path} iface {iface} ({name})")
    for cls in (0x05, 0x07, 0x10, 0x11):
        control(fd, 0x21, 0x09, (2<<8)|0, iface, build(cls), 64, 300)
        time.sleep(0.25)
        r = b""
        for _ in range(6):
            try: d = bulk_read(fd, in_ep, 64, 150)
            except OSError: break
            if any(d) and not is_battery(d) and d[1] == cls:
                r = d; break
        if r:
            n = r[2]; val = r[6:6+max(0,n-1)]
            print(f"class {cls:#04x}: type={r[5]:#04x} len={n}\n   {val.hex(' ')}")
            if cls == 0x05 and len(val) >= 24:
                st = [val[12+2*i] | (val[13+2*i] << 8) for i in range(6)]
                print(f"   dpi stages: {[(s+1)*50 for s in st]}")
        else:
            print(f"class {cls:#04x}: no reply")
finally:
    try:
        arg=(ctypes.c_uint*1)(iface); fcntl.ioctl(fd, USBDEVFS_RELEASEINTERFACE, arg, True)
    except OSError: pass
    os.close(fd); rebind(name, drv)
