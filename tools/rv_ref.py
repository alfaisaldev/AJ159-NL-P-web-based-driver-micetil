#!/usr/bin/env python3
"""RISC-V firmware: find the code that references a given string.

Strings live in a pointer table; the code loads a table slot with
`lui rd, hi` + `lw rx, lo(rd)`.  This tool locates the slot(s) holding a
pointer to the string and then finds the load sites.

Usage: python3 tools/rv_ref.py <blob> <base_hex> <string-substring>
"""
import re
import struct
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
needle = sys.argv[3].encode()

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

# 1) string addresses
targets = []
for m in re.finditer(rb"[ -~]{4,90}", data):
    if needle in m.group(0):
        targets.append((m.start(), m.group(0).decode()))

if not targets:
    raise SystemExit("string not found in the image")

# 2) table slots holding a pointer to them
slots = []
for off, s in targets:
    addr = BASE + off
    pat = struct.pack("<I", addr)
    i = 0
    while True:
        i = data.find(pat, i)
        if i < 0:
            break
        slots.append((i, off, s))
        i += 4

print(f"target strings: {len(targets)}")
for off, s in targets:
    print(f"  file 0x{off:x} (rt 0x{BASE + off:x})  {s[:70]!r}")
print(f"table slots pointing at them: {len(slots)}")
for slot, off, s in slots:
    print(f"  slot file 0x{slot:x} (rt 0x{BASE + slot:x}) -> {s[:40]!r}")

if not slots:
    raise SystemExit("no pointer-table slot found (strings may be inlined)")

slot_addrs = {BASE + s for s, _, _ in slots}

# 3) find the load sites
hits = []
insns = [i for i in md.disasm(data, BASE)]
for k, insn in enumerate(insns):
    if insn.mnemonic != "lui":
        continue
    ops = [o.strip() for o in insn.op_str.split(",")]
    if len(ops) != 2:
        continue
    try:
        hi = int(ops[1].lstrip("#"), 0)
    except ValueError:
        continue
    base = (hi << 12) & 0xFFFFFFFF
    for j in range(k + 1, min(k + 8, len(insns))):
        nxt = insns[j]
        if nxt.mnemonic in ("lui", "auipc", "jal", "c.jal", "j", "ret", "c.jr", "jr"):
            break
        mm = re.match(r"(-?0x[0-9a-fA-F]+|-?\d+)\((\w+)\)", nxt.op_str.split(",")[-1].strip())
        if not mm:
            continue
        disp = int(mm.group(1), 0)
        addr = (base + disp) & 0xFFFFFFFF
        if addr in slot_addrs:
            hits.append((insn.address, nxt.address, addr))
            break

print(f"\ncode sites loading those slots: {len(hits)}")
for a, b, addr in hits:
    print(f"  lui 0x{a:x}  load 0x{b:x}  -> slot 0x{addr:x}")
