#!/usr/bin/env python3
"""Inventory the full HID surface of an AJAZZ mouse: every report id, its
direction, length and usage page - plus a read of the device's current
state via HIDIOCGINPUT (read-only, nothing is written).

Usage: python3 tools/hid_surface.py /dev/hidraw4 /dev/hidraw5
"""
import fcntl
import os
import sys
import time

# _IOC(dir, type, nr, size) = (dir<<30)|(size<<16)|(type<<8)|nr
def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)

HIDIOCGINPUT = lambda n: ioc(3, ord("H"), 0x0A, n)   # read last input report
HIDIOCGOUTPUT = lambda n: ioc(3, ord("H"), 0x0C, n)  # read? (output is write-only)
HIDIOCGFEATURE = lambda n: ioc(3, ord("H"), 0x07, n)

MAIN = {0x08: "Input", 0x09: "Output", 0x0B: "Feature"}
GLOBAL = {0x00: "UsagePage", 0x01: "LogMin", 0x02: "LogMax", 0x07: "ReportSize",
          0x08: "ReportID", 0x09: "ReportCount"}


def descriptor(path):
    with open(f"/sys/class/hidraw/{os.path.basename(path)}/device/report_descriptor", "rb") as fh:
        return fh.read()


def parse(desc):
    out, i = {}, 0
    usage_page = report_id = count = size = 0
    while i < len(desc):
        head = desc[i]
        if head == 0xFE:
            i += 2 + desc[i + 1] if i + 1 < len(desc) else 2
            continue
        n = head & 3
        n = 4 if n == 3 else n
        tag, itype = (head >> 4) & 0x0F, (head >> 2) & 0x03
        if i + 1 + n > len(desc):
            break
        val = int.from_bytes(desc[i + 1 : i + 1 + n], "little")
        if itype == 1:
            if tag == 0x00:
                usage_page = val
            elif tag == 0x08:
                report_id = val
            elif tag == 0x09:
                count = val
            elif tag == 0x07:
                size = val
        elif itype == 0 and tag in MAIN:
            entry = out.setdefault(report_id, {"page": usage_page})
            kind = MAIN[tag]
            entry[kind] = entry.get(kind, 0) + (count * size) // 8
        i += 1 + n
    return out


def main():
    for path in sys.argv[1:]:
        print(f"\n=== {path} ===")
        desc = descriptor(path)
        reports = parse(desc)
        print(f"  {'id':>3} {'dir':<8} {'len':>4}  usage page")
        for rid, info in sorted(reports.items()):
            for kind in ("Input", "Output", "Feature"):
                if kind in info:
                    print(f"  {rid:>3} {kind:<8} {info[kind]:>4}  0x{info['page']:04x}")

        # read the device's current input state (read-only)
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError as exc:
            print("  open:", exc)
            continue
        try:
            for rid, info in sorted(reports.items()):
                n = info.get("Input")
                if not n:
                    continue
                buf = bytearray([rid]) + bytearray(n)
                try:
                    fcntl.ioctl(fd, HIDIOCGINPUT(len(buf)), buf, True)
                    print(f"  last input id {rid}: {bytes(buf).hex(' ')}")
                except OSError as exc:
                    print(f"  last input id {rid}: ERR {exc}")
        finally:
            os.close(fd)


if __name__ == "__main__":
    main()
