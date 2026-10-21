#!/usr/bin/env python3
"""List every AJAZZ USB device, its HID interfaces and report descriptors.

Usage: python3 tools/list_ajazz.py
"""
import glob
import os
import re
import subprocess
import sys

VID = "7768"


def usb_tree():
    out = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-f]{4}):([0-9a-f]{4}) (.*)", line)
        if m and m.group(3) == VID:
            yield m.group(4), m.group(5).strip(), line


def descriptors():
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        name = os.path.basename(path)
        try:
            with open(f"{path}/device/uevent") as fh:
                uevent = fh.read()
        except OSError:
            continue
        m = re.search(r"HID_ID=0003:([0-9A-F]{8}):([0-9A-F]{8})", uevent)
        if not m or m.group(1)[4:] != VID:
            continue
        prod = re.search(r"HID_NAME=(.*)", uevent)
        iface = os.path.realpath(f"{path}/device")
        number = re.search(r"(\d{4}:\d{4}:\d{4})\.(\d{3})$", iface)
        desc = b""
        try:
            with open(f"{path}/device/report_descriptor", "rb") as fh:
                desc = fh.read()
        except OSError:
            pass
        yield {
            "node": f"/dev/{name}",
            "product": (prod.group(1).strip() if prod else "?"),
            "iface": number.group(1) if number else "?",
            "desc": desc,
        }


def usage_pages(desc: bytes) -> list:
    pages, i = [], 0
    while i < len(desc):
        head = desc[i]
        if head == 0xFE:
            i += 2 + desc[i + 1] if i + 1 < len(desc) else 2
            continue
        size = head & 3
        size = 4 if size == 3 else size
        tag, _t = (head & 0xFC) >> 2, head & 3
        if tag == 0 and size in (1, 2, 4):
            val = int.from_bytes(desc[i + 1 : i + 1 + size], "little")
            if val not in pages:
                pages.append(val)
        i += 1 + size
    return pages


def main():
    print("== USB devices (VID %s) ==" % VID)
    for pid, name, line in usb_tree():
        print(f"  {pid}  {name}")

    print("\n== HID nodes ==")
    for d in descriptors():
        pages = usage_pages(d["desc"])
        pages_s = " ".join(f"0x{p:04x}" for p in pages)
        print(f"  {d['node']}  iface={d['iface']}  {d['product']}")
        print(f"      usage pages: {pages_s}")
        print(f"      descriptor ({len(d['desc'])} bytes): {d['desc'][:120].hex(' ')}")

    if len(sys.argv) > 1:
        for d in descriptors():
            if d["node"] == sys.argv[1]:
                print(f"\n== full descriptor {d['node']} ==")
                print(d["desc"].hex(" "))


if __name__ == "__main__":
    main()
