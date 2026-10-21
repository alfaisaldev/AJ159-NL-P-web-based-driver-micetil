#!/usr/bin/env python3
"""RISC-V firmware: find code that touches a given runtime address (a data
table) and dump the surrounding function.

Usage: python3 tools/rv_addr.py <blob> <code_base> <addr1> [addr2 ...]
"""
import re
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
targets = {int(a, 0) for a in sys.argv[3:]}

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


hits = []
for k, insn in enumerate(insns):
    if insn.mnemonic not in ("lui", "auipc"):
        continue
    ops = [o.strip() for o in insn.op_str.split(",")]
    if len(ops) != 2:
        continue
    imm = imm_of(ops[1])
    if imm is None:
        continue
    base = ((imm << 12) if insn.mnemonic == "lui" else (insn.address + (imm << 12))) & 0xFFFFFFFF
    reg = ops[0]
    for j in range(k + 1, min(k + 5, len(insns))):
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
        elif nxt.mnemonic in ("lw", "ld", "c.lw", "c.ld", "lbu", "c.lbu", "lhu", "c.lhu", "lhu") and len(o) >= 2:
            mm = re.match(r"(-?0x[0-9a-fA-F]+|-?\d+)\((\w+)\)", o[-1])
            if mm and mm.group(2) == reg:
                val = (base + int(mm.group(1), 0)) & 0xFFFFFFFF
        if val is None:
            continue
        if any((val & ~0xFFF) == (t & ~0xFFF) for t in targets):
            hits.append((nxt.address, val))
        break

print(f"hits: {len(hits)}")
shown = set()
for a, v in hits:
    k = next((i for i, x in enumerate(insns) if x.address == a), None)
    if k is None:
        continue
    lo, hi = max(0, k - 24), min(len(insns), k + 24)
    key = (lo // 20)
    if key in shown:
        continue
    shown.add(key)
    print(f"\n=== reference to ~0x{v:x} at 0x{a:x} ===")
    for i2 in range(lo, hi):
        x = insns[i2]
        mark = "  <<<" if x.address == a else ""
        print(f"   0x{x.address:x}: {x.mnemonic:9} {x.op_str}{mark}")
