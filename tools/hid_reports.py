#!/usr/bin/env python3
"""Parse a HID report descriptor and list every report id with its type.

Usage: python3 tools/hid_reports.py /dev/hidrawN
"""
import sys

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from battery import _report_descriptor  # noqa: E402

TYPES = {0x08: "Input", 0x09: "Output", 0x0A: "Collection", 0x0B: "Feature"}
COLL = {0x00: "Physical", 0x01: "Application", 0x02: "Logical", 0x03: "Vendor",
        0x10: "Monitor", 0x80: "Vendor"}


def parse(d):
    """Return (reports, collections) where reports maps (id, type) -> bit count."""
    i = 0
    reports = {}
    colls = []
    stack = []
    while i < len(d):
        head = d[i]
        size = head & 0x03
        typ = (head >> 2) & 0x03
        tag = head >> 4
        if size == 3:
            ln = d[i + 1] | (d[i + 2] << 8) | (d[i + 3] << 16)
            data = d[i + 1:i + 4]
            i += 4
        elif size == 2:
            ln = d[i + 1] | (d[i + 2] << 8)
            data = d[i + 1:i + 3]
            i += 3
        elif size == 1:
            ln = d[i + 1]
            data = d[i + 1:i + 2]
            i += 2
        else:
            ln = 0
            data = b""
            i += 1
        if typ == 0:                       # main item
            if tag == 0x0A:                # collection
                coll = COLL.get(data[0] if data else 0, hex(data[0] if data else 0))
                colls.append(coll)
                stack.append(coll)
            elif tag == 0x0C:              # end collection
                if stack:
                    stack.pop()
            elif tag in TYPES:
                rid = data[0] if data else 0
                reports.setdefault((rid, TYPES[tag]), 0)
                reports[(rid, TYPES[tag])] += ln * 8
    return reports, colls


node = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
d = _report_descriptor(node)
print(f"{node}: descriptor {len(d)} bytes")
reports, colls = parse(d)
print("collections:", ", ".join(colls))
print()
byid = {}
for (rid, typ), bits in sorted(reports.items()):
    byid.setdefault(rid, []).append((typ, bits))
for rid in sorted(byid):
    print(f"  report id {rid}: " + ", ".join(f"{t} {b} bits ({b // 8} B)" for t, b in byid[rid]))
print()
feat = [rid for rid, v in byid.items() if any(t == "Feature" for t, _ in v)]
print("feature report ids:", feat if feat else "NONE")
