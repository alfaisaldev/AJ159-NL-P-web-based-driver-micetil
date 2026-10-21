#!/usr/bin/env python3
"""RISC-V firmware: map code addresses to the string literals they use.

Looks for the `lui rd, hi` + `addi rX, rd, lo` idiom (and the `mv` variant)
and resolves the resulting absolute address against the string area.

Usage: python3 tools/rv_map.py <blob> <base_hex> [filter]
"""
import re
import struct
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
filt = sys.argv[3].lower() if len(sys.argv) > 3 else None

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

insns = [i for i in md.disasm(data, BASE) if i.mnemonic != ".byte"]


def imm_of(op):
    op = op.strip().lstrip("#")
    try:
        return int(op, 0)
    except ValueError:
        return None


def as_str(addr):
    off = addr - BASE
    if not (0 <= off < len(data)):
        return None
    end = data.find(b"\x00", off, off + 90)
    if end < 0:
        return None
    s = data[off:end]
    if len(s) < 3 or not all(32 <= c < 127 for c in s):
        return None
    return s.decode()


hits = []
for k, insn in enumerate(insns):
    if insn.mnemonic != "lui":
        continue
    ops = [o.strip() for o in insn.op_str.split(",")]
    if len(ops) != 2:
        continue
    imm = imm_of(ops[1])
    if imm is None:
        continue
    base = (imm << 12) & 0xFFFFFFFF
    reg = ops[0]
    for j in range(k + 1, min(k + 4, len(insns))):
        nxt = insns[j]
        o = [x.strip() for x in nxt.op_str.split(",")]
        val = None
        if nxt.mnemonic in ("addi", "c.addi", "addiw") and len(o) == 3 and o[1] == reg:
            i2 = imm_of(o[2])
            if i2 is None:
                break
            val = (base + i2) & 0xFFFFFFFF
        elif nxt.mnemonic in ("mv", "c.mv") and len(o) == 2 and o[1] == reg:
            val = base
        elif nxt.mnemonic in ("lw", "ld", "c.lw", "c.ld") and len(o) >= 2:
            mm = re.match(r"(-?0x[0-9a-fA-F]+|-?\d+)\((\w+)\)", o[-1])
            if mm and mm.group(2) == reg:
                val = (base + int(mm.group(1), 0)) & 0xFFFFFFFF
        if val is None:
            continue
        s = as_str(val)
        if s:
            hits.append((nxt.address, val, s))
        break

print(f"code -> string references: {len(hits)}")
seen = set()
for a, v, s in hits:
    if filt and filt not in s.lower():
        continue
    if (v, s) in seen:
        continue
    seen.add((v, s))
    print(f"  0x{a:x}  0x{v:x}  {s[:80]}")
