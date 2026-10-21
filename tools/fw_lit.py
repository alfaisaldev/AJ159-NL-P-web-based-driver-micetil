#!/usr/bin/env python3
"""Find ARM Thumb code that loads a given 32-bit constant (e.g. a string
address) from a literal pool.

Handles the three PC-relative literal forms:
  T1  LDR  Rt, [PC, #imm8]          (16-bit, forward only)
  T2  LDR.W Rt, [PC, #imm8]         (32-bit, signed -> can point backwards)
  T3  LDR.W Rt, [PC, #imm12]        (32-bit, forward only)

Usage: python3 tools/fw_lit.py <blob> <const_hex> [base_hex]
"""
import struct
import sys

blob = sys.argv[1]
target = int(sys.argv[2], 0)
base = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x90115000

data = open(blob, "rb").read()


def literal_at(off):
    if 0 <= off <= len(data) - 3:
        return struct.unpack_from("<I", data, off)[0]
    return None


hits = []
i = 0
while i < len(data) - 1:
    w = struct.unpack_from("<H", data, i)[0]
    lit = None
    kind = ""
    if 0x4800 <= w <= 0x4FFF:  # T1
        lit = ((i + 4) & ~3) + (w & 0xFF)
        kind = "T1"
    elif 0xF850 <= w <= 0xF85F and i + 3 < len(data):  # T2 / T3
        w2 = struct.unpack_from("<H", data, i + 2)[0]
        if (w2 & 0xFF00) == 0x4700:  # T2: signed imm8
            imm8 = w2 & 0xFF
            off = ((i + 4) & ~3) + (imm8 << 2 if imm8 < 0x80 else (imm8 - 256) << 2)
            lit, kind = off, "T2"
        elif (w2 & 0xF800) == 0xF000 and not (w2 & 0x0800):  # T3: imm12
            lit = ((i + 4) & ~3) + ((w2 & 0x0FFF) << 2)
            kind = "T3"
    if lit is not None:
        if literal_at(lit) == target:
            hits.append((i, lit, kind, (w >> 8) & 7))
        i += 4 if kind in ("T2", "T3") else 2
        continue
    i += 2

print(f"literal loads of 0x{target:x}: {len(hits)}")
for i, lit, kind, rt in hits:
    print(f"  0x{i:x}  {kind} r{rt} (pool 0x{lit:x})  runtime 0x{base + i:x}")
