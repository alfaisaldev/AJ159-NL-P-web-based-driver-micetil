#!/usr/bin/env python3
"""Read-only dump of every feature report a HID node exposes.

Only GET_FEATURE (a read) is used - nothing is written to the device.

Usage: python3 tools/dump_features.py /dev/hidraw4
"""
import fcntl
import os
import re
import sys
import time


def ioc(direction, typ, nr, size):
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


GFEAT = lambda n: ioc(3, ord("H"), 0x07, n)   # HIDIOCGFEATURE(len)
HID_SIZE = 0x80044801                        # HIDIOCGRDESCSIZE
HID_DESC = 0xC0480200                        # HIDIOCGRDESC(len)


def descriptor(path):
    with open(f"/sys/class/hidraw/{os.path.basename(path)}/device/report_descriptor", "rb") as fh:
        return fh.read()


def parse(desc):
    """Return {report_id: {feature: bytes, input: bytes, output: bytes}}.

    Short item layout: bSize = bits 0-1, bType = bits 2-3, bTag = bits 4-7.
    """
    MAIN_INPUT, MAIN_OUTPUT, MAIN_FEATURE = 0x08, 0x09, 0x0B
    G_USAGE_PAGE, G_REPORT_ID, G_REPORT_COUNT, G_REPORT_SIZE = 0x00, 0x08, 0x09, 0x07

    out, i = {}, 0
    usage_page = report_id = count = size = 0
    while i < len(desc):
        head = desc[i]
        if head == 0xFE:  # long item
            i += 2 + desc[i + 1] if i + 1 < len(desc) else 2
            continue
        n = head & 0x03
        n = 4 if n == 3 else n
        tag = (head >> 4) & 0x0F
        itype = (head >> 2) & 0x03
        if i + 1 + n > len(desc):
            break
        val = int.from_bytes(desc[i + 1 : i + 1 + n], "little")
        if itype == 1:  # global
            if tag == G_USAGE_PAGE:
                usage_page = val
            elif tag == G_REPORT_ID:
                report_id = val
            elif tag == G_REPORT_COUNT:
                count = val
            elif tag == G_REPORT_SIZE:
                size = val
        elif itype == 0:  # main
            if tag in (MAIN_INPUT, MAIN_OUTPUT, MAIN_FEATURE):
                kind = {MAIN_INPUT: "input", MAIN_OUTPUT: "output", MAIN_FEATURE: "feature"}[tag]
                entry = out.setdefault(report_id, {"page": usage_page})
                entry[kind] = entry.get(kind, 0) + (count * size) // 8
        i += 1 + n
    return out


def main():
    for path in sys.argv[1:]:
        print(f"\n=== {path} ===")
        try:
            desc = descriptor(path)
        except OSError as exc:
            print("  descriptor:", exc)
            continue
        reports = parse(desc)
        print("  report id -> lengths:", {
            k: {kk: vv for kk, vv in v.items() if kk != "page"} for k, v in sorted(reports.items())
        })
        print("  usage pages:", sorted({v.get("page") for v in reports.values()}))

        fd = os.open(path, os.O_RDWR)
        try:
            for rid, info in sorted(reports.items()):
                n = info.get("feature")
                if not n:
                    continue
                for attempt in range(2):
                    buf = bytearray([rid]) + bytearray(n)
                    try:
                        fcntl.ioctl(fd, GFEAT(len(buf)), buf, True)
                    except OSError as exc:
                        print(f"  feature id {rid} ({n}B): ERR {exc}")
                        break
                    print(f"  feature id {rid} ({n}B): {bytes(buf).hex(' ')}")
                    if attempt == 0:
                        time.sleep(0.15)
        finally:
            os.close(fd)


if __name__ == "__main__":
    main()
