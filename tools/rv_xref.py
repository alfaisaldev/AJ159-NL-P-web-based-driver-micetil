#!/usr/bin/env python3
"""RISC-V firmware: resolve which code references which strings.

The image keeps its strings in a pointer table; code loads a table slot with
`lui reg, hi` + `lw reg, lo(reg)` (sometimes + addi).  This walker tracks
register values across the whole image (including RVC compressed forms) and
reports, for every load, the string it ends up pointing at.

Usage: python3 tools/rv_xref.py <blob> <base_hex> [string-substring]
"""
import re
import struct
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
needle = sys.argv[3] if len(sys.argv) > 3 else None

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

LOADS = {"lw", "ld", "lwu", "c.lw", "c.ld", "c.lwsp", "flw", "fld", "c.flw", "c.fld"}
ADDI = {"addi", "c.addi", "c.addiw", "addiw", "c.li", "li"}
MOVE = {"mv", "c.mv"}


def as_str(addr):
    off = addr - BASE
    if not (0 <= off < len(data)):
        return None
    end = data.find(b"\x00", off, off + 90)
    if end < 0:
        return None
    s = data[off:end]
    if len(s) < 4 or not all(32 <= c < 127 for c in s):
        return None
    return s.decode()


def resolve(addr, depth=0):
    s = as_str(addr)
    if s:
        return s
    if depth < 2:
        off = addr - BASE
        if 0 <= off < len(data) - 3:
            v = struct.unpack_from("<I", data, off)[0]
            if v != addr:
                return resolve(v, depth + 1)
    return None


def imm_of(op):
    op = op.strip().lstrip("#")
    try:
        return int(op, 0)
    except ValueError:
        return None


refs = {}
regs = {}
for insn in md.disasm(data, BASE):
    m = insn.mnemonic
    ops = [o.strip() for o in insn.op_str.split(",")]
    dst = ops[0] if ops else ""

    if m == "lui" and len(ops) == 2:
        imm = imm_of(ops[1])
        if imm is not None:
            regs[dst] = (imm << 12) & 0xFFFFFFFF
        continue
    if m == "auipc" and len(ops) == 2:
        imm = imm_of(ops[1])
        if imm is not None:
            regs[dst] = (insn.address + (imm << 12)) & 0xFFFFFFFF
        continue
    if m in ADDI:
        if m in ("c.li", "li"):
            imm = imm_of(ops[1]) if len(ops) > 1 else None
            if imm is not None:
                regs[dst] = imm & 0xFFFFFFFF
        elif len(ops) == 3 and ops[1] in regs:
            imm = imm_of(ops[2])
            if imm is not None:
                regs[dst] = (regs[ops[1]] + imm) & 0xFFFFFFFF
        continue
    if m in MOVE and len(ops) == 2:
        if ops[1] in regs:
            regs[dst] = regs[ops[1]]
        else:
            regs.pop(dst, None)
        continue
    if m in LOADS and len(ops) >= 2:
        mm = re.match(r"(-?0x[0-9a-fA-F]+|-?\d+)\((\w+)\)", ops[1])
        if mm and mm.group(2) in regs:
            disp = int(mm.group(1), 0)
            addr = (regs[mm.group(2)] + disp) & 0xFFFFFFFF
            s = resolve(addr)
            if s:
                refs.setdefault(s, []).append(insn.address)
        continue
    # any other instruction may clobber its first operand
    if dst and not m.startswith("c."):
        regs.pop(dst, None)
    elif dst and m.startswith("c.") and m not in ("c.jal", "c.j", "c.beqz", "c.bnez",
                                                   "c.jr", "c.jalr", "c.beqz", "c.bnez"):
        if m in ("c.li", "c.mv", "c.addi", "c.add", "c.addi16sp", "c.addi4spn", "c.lui"):
            pass
        else:
            regs.pop(dst, None)

if needle:
    found = False
    for s, lst in refs.items():
        if needle in s:
            found = True
            print(f"{s!r}")
            for a in lst:
                print(f"    code 0x{a:x}  (file 0x{a - BASE:x})")
    if not found:
        print(f"no reference to {needle!r}; {len(refs)} strings referenced in total")
else:
    print(f"strings referenced from code: {len(refs)}")
    pat = re.compile(r"dpi|rate|polling|charge|sleep|macro|msg_len|header|lod|angle|ripple|hid|usb|report|cmd|mode|button|key", re.I)
    for s, lst in sorted(refs.items(), key=lambda kv: kv[1][0]):
        if pat.search(s):
            print(f"  0x{lst[0]:x}  {s[:76]}")
