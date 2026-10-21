#!/usr/bin/env python3
"""RISC-V firmware: find the code that uses a given string.

Handles both absolute (`lui`+`addi`) and PC-relative (`auipc`+`addi`)
addressing, and reports the surrounding instructions so the calling
function can be identified.

Usage: python3 tools/rv_use.py <blob> <base_hex> <string-substring>
"""
import re
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
needle = sys.argv[3].encode()
# optional 4th arg: the load address of the string section (defaults to BASE)
STRBASE = int(sys.argv[4], 0) if len(sys.argv) > 4 else BASE

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


targets = []
for m in re.finditer(rb"[ -~]{4,90}", data):
    if needle in m.group(0):
        targets.append((m.start(), m.group(0).decode()))

if not targets:
    raise SystemExit("string not found")
for off, s in targets:
    print(f"target: file 0x{off:x} rt 0x{STRBASE + off:x}  {s[:70]!r}")

wanted = {STRBASE + off for off, _ in targets}
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
        elif nxt.mnemonic in ("lw", "ld", "c.lw", "c.ld", "lbu", "c.lbu") and len(o) >= 2:
            mm = re.match(r"(-?0x[0-9a-fA-F]+|-?\d+)\((\w+)\)", o[-1])
            if mm and mm.group(2) == reg:
                val = (base + int(mm.group(1), 0)) & 0xFFFFFFFF
        if val is None:
            continue
        if val in wanted:
            hits.append((insn.address, nxt.address, val))
        break

print(f"\nreferences found: {len(hits)}")
for a, b, v in hits:
    k = next(i for i, x in enumerate(insns) if x.address == b)
    lo = max(0, k - 18)
    hi = min(len(insns), k + 18)
    print(f"\n--- use of 0x{v:x} at 0x{b:x} ---")
    for i2 in range(lo, hi):
        x = insns[i2]
        mark = "  <<<" if x.address == b else ""
        print(f"   0x{x.address:x}: {x.mnemonic:9} {x.op_str}{mark}")
