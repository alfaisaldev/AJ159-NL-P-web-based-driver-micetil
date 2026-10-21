#!/usr/bin/env python3
"""Watch USB enumeration for new AJAZZ devices (bootloader hunting).

Logs every AJAZZ device that appears or disappears, with its full descriptor
summary, so a DFU/bootloader mode can be spotted.

Usage: python3 tools/watch_usb.py [seconds]
"""
import re
import subprocess
import sys
import time

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0


def snapshot():
    out = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
    devices = {}
    for line in out.splitlines():
        m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-f]{4}):([0-9a-f]{4}) (.*)", line)
        if m:
            key = (m.group(1), m.group(2))
            devices[key] = (f"{m.group(3)}:{m.group(4)}", m.group(5).strip())
    return devices


def describe(vid_pid):
    """Full descriptor summary for a device."""
    out = subprocess.run(["lsusb", "-v", "-d", vid_pid], capture_output=True, text=True).stdout
    lines = []
    for line in out.splitlines():
        if re.search(r"bNumInterfaces|bInterfaceClass|bInterfaceSubClass|bInterfaceProtocol|"
                     r"bcdDevice|idVendor|idProduct|iProduct|MaxPower|bEndpointAddress|"
                     r"bInterfaceNumber|wDescriptorLength", line):
            lines.append("    " + line.strip())
    return lines


start = time.time()
prev = snapshot()
print(f"[{0.0:6.1f}] baseline:")
for (bus, dev), (vp, name) in prev.items():
    print(f"    {vp}  {name}")
    if vp.startswith("7768"):
        for l in describe(vp):
            print(l)

while time.time() - start < DURATION:
    time.sleep(1.0)
    now = snapshot()
    for key, (vp, name) in now.items():
        if key not in prev:
            print(f"[{time.time()-start:6.1f}] NEW  bus{key[0]} dev{key[1]}: {vp}  {name}")
            for l in describe(vp):
                print(l)
    for key, (vp, name) in prev.items():
        if key not in now:
            print(f"[{time.time()-start:6.1f}] GONE bus{key[0]} dev{key[1]}: {vp}  {name}")
    prev = now

print("done")
