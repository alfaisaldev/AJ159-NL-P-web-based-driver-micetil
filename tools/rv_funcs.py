#!/usr/bin/env python3
"""Function-aware RISC-V analysis of an AJAZZ firmware blob.

Linear sweeps desynchronise inside the SDK, so this tool finds function
prologues and decodes each function on its own.  It can then report, per
function: the immediate constants it compares against, the functions it
calls, and the string literals it references.

Usage:
  python3 tools/rv_funcs.py <blob> <base_hex> [--range START:END] [--calls]
  python3 tools/rv_funcs.py <blob> <base_hex> --calltarget 0xADDR
"""
import re
import struct
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
args = sys.argv[3:]

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

RANGE = (0, len(data))
CALLTARGET = None
for i, a in enumerate(args):
    if a == "--range":
        s, e = args[i + 1].split(":")
        RANGE = (int(s, 0), int(e, 0))
    if a == "--calltarget":
        CALLTARGET = int(args[i + 1], 0)


def prologue_offsets(lo, hi):
    """Offsets that look like a function prologue."""
    out = []
    for i in range(lo, hi, 2):
        hw = struct.unpack_from("<H", data, i)[0]
        # C.ADDI16SP: 011 0 imm[9|4|6|8:7|5] 10 010 01
        if (hw & 0x607B) == 0x6049:
            out.append(i)
        # ADDI sp, sp, -imm  (32-bit): imm | rs1=sp | 010 | rd=sp | 0010011
        if (hw & 0xFFF83F80) == 0x00201080:
            out.append(i)
    return sorted(set(out))


def decode_func(off, limit=0x400):
    insns = []
    for x in md.disasm(data[off:off + limit], BASE + off):
        if x.mnemonic == ".byte":
            break
        insns.append(x)
        if x.mnemonic in ("c.jr", "jr", "ret") and x.op_str.startswith("ra"):
            break
        if x.mnemonic in ("c.j", "j", "tail") and len(insns) > 2:
            # tail call: keep going, the next function may follow
            pass
    return insns


def as_str(addr):
    off = addr - BASE
    if not (0 <= off < len(data)):
        return None
    end = data.find(b"\x00", off, off + 90)
    if end < 0:
        return None
    s = data[off:end]
    if len(s) < 3:
        return None
    if not all(c in (9, 10, 13) or 32 <= c < 127 for c in s):
        return None
    return s.decode()


def consts(insns):
    out = []
    for x in insns:
        if x.mnemonic in ("addi", "andi", "li", "c.li", "c.addi", "c.addi16sp", "lui", "c.lui"):
            try:
                v = int(x.op_str.split(",")[-1].strip().lstrip("#"), 0)
            except ValueError:
                continue
            out.append((x.address, v))
    return out


def calls(insns):
    out = []
    for x in insns:
        if x.mnemonic in ("jal", "c.jal"):
            try:
                off = int(x.op_str.split(",")[-1].strip().lstrip("#"), 0)
            except ValueError:
                continue
            out.append((x.address, (x.address + off) & 0xFFFFFFFF))
        elif x.mnemonic in ("jalr", "c.jalr"):
            out.append((x.address, None))
    return out


def strings_in(insns):
    """Resolve lui/auipc + addi pairs to string literals."""
    res = []
    regs = {}
    for i, x in enumerate(insns):
        ops = [o.strip() for o in x.op_str.split(",")]
        if x.mnemonic == "lui" and len(ops) == 2:
            try:
                regs[ops[0]] = (int(ops[1].lstrip("#"), 0) << 12) & 0xFFFFFFFF
            except ValueError:
                pass
        elif x.mnemonic == "auipc" and len(ops) == 2:
            try:
                regs[ops[0]] = (x.address + (int(ops[1].lstrip("#"), 0) << 12)) & 0xFFFFFFFF
            except ValueError:
                pass
        elif x.mnemonic in ("addi", "c.addi") and len(ops) == 3 and ops[1] in regs:
            try:
                v = int(ops[2].lstrip("#"), 0)
            except ValueError:
                continue
            val = (regs[ops[1]] + v) & 0xFFFFFFFF
            s = as_str(val)
            if s:
                res.append((x.address, val, s))
    return res


prol = prologue_offsets(*RANGE)
print(f"candidate functions in range: {len(prol)}")
n = 0
for off in prol:
    insns = decode_func(off)
    if len(insns) < 6:
        continue
    n += 1
    cl = calls(insns)
    if CALLTARGET is not None:
        if not any(t == CALLTARGET for _, t in cl):
            continue
    cs = consts(insns)
    interesting = [(a, v) for a, v in cs if 0 <= v <= 0x100 and v not in (0,)]
    strs = strings_in(insns)
    print(f"\n== fn 0x{BASE + off:x} (file 0x{off:x}) {len(insns)} insns ==")
    if interesting:
        print("   consts:", ", ".join(f"{v:#x}@{a:#x}" for a, v in interesting[:18]))
    if strs:
        for a, v, s in strs:
            print(f"   str @0x{a:x} 0x{v:x} {s[:60]!r}")
    if "--calls" in args:
        for a, t in cl:
            print(f"   call 0x{a:x} -> {('#x' % t) if t else '?'}")
print(f"\nfunctions analysed: {n}")
