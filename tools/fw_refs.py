#!/usr/bin/env python3
"""Locate a string in an ARM Thumb firmware blob and find the code that
references it, by matching the absolute address in literal pools.

Usage: python3 tools/fw_refs.py <blob> <string> [load_addr]
"""
import struct
import subprocess
import sys

blob_path, needle = sys.argv[1], sys.argv[2].encode()
load = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x90115000
data = open(blob_path, "rb").read()

off = data.find(needle)
if off < 0:
    raise SystemExit("string not found")
addr = load + off
print(f"string {needle.decode()!r} at file 0x{off:x} -> runtime 0x{addr:x}")

pat = struct.pack("<I", addr)
hits = [i for i in range(len(data) - 3) if data[i:i + 4] == pat]
print(f"literal-pool references: {len(hits)} -> {[hex(h) for h in hits]}")

if not hits:
    # try other plausible bases
    for base in (0x90100000, 0x0, 0x90115000 - 0x1000):
        a = base + off
        p = struct.pack("<I", a)
        h = [i for i in range(len(data) - 3) if data[i:i + 4] == p]
        if h:
            print(f"  ...found with base 0x{base:x} -> {[hex(x) for x in h]}")

for h in hits[:3]:
    print(f"\n--- context around literal pool at 0x{h:x} ---")
    start = max(0, h - 0x60)
    for line in subprocess.run(
            ["objdump", "-D", "-b", "binary", "-m", "arm", "-M", "force-thumb",
             "--start-address=0x%x" % start, "--stop-address=0x%x" % (h + 8),
             blob_path],
            capture_output=True, text=True).stdout.splitlines():
        if line.strip().startswith("0") or ":" in line:
            print("   " + line)
