#!/usr/bin/env python3
"""RISC-V firmware scanner: rebuild lui/addi and auipc/addi address pairs and
report which code sites reference which strings.

Usage: python3 tools/rv_find.py <blob> <base_hex> [string]
"""
import re
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
needle = sys.argv[3].encode() if len(sys.argv) > 3 else None

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

insns = []
for insn in md.disasm(data, BASE):
    if insn.mnemonic == ".byte":
        continue
    insns.append(insn)
    if len(insns) > 400000:
        break


def reg_of(op):
    return op.strip()


def parse_imm(op):
    op = op.strip()
    if op.startswith("#"):
        op = op[1:]
    try:
        return int(op, 0)
    except ValueError:
        return None


refs = {}
for i, insn in enumerate(insns):
    if insn.mnemonic not in ("lui", "auipc"):
        continue
    ops = insn.op_str.split(",")
    if len(ops) != 2:
        continue
    r = reg_of(ops[0])
    imm = parse_imm(ops[1])
    if imm is None:
        continue
    if insn.mnemonic == "lui":
        hi = (imm << 12) & 0xFFFFFFFF
    else:  # auipc: pc-relative
        hi = (insn.address + (imm << 12)) & 0xFFFFFFFF
    # look ahead for addi rd, r, lo
    for j in range(i + 1, min(i + 6, len(insns))):
        nxt = insns[j]
        if nxt.mnemonic == "addi":
            o = nxt.op_str.split(",")
            if len(o) == 3 and reg_of(o[1]) == r:
                lo = parse_imm(o[2])
                if lo is None:
                    break
                addr = (hi + (lo & 0xFFFF if lo < 0 else lo)) & 0xFFFFFFFF
                off = addr - BASE
                if 0 <= off < len(data):
                    end = data.find(b"\x00", off, off + 80)
                    s = data[off:end] if end > 0 else b""
                    if len(s) >= 4 and all(32 <= c < 127 for c in s):
                        refs.setdefault(s.decode(), []).append((insn.address, nxt.address))
                break
        elif nxt.mnemonic in ("lui", "auipc", "call", "j", "jr", "jalr"):
            break

if needle:
    hits = [(s, v) for s, v in refs.items() if needle.decode() in s]
    for s, v in hits:
        print(f"{s!r}")
        for a, b in v:
            print(f"    code 0x{a:x} (file 0x{a - BASE:x})")
    if not hits:
        print(f"no reference to {needle!r} among {len(refs)} strings")
else:
    print(f"strings referenced by lui+addi: {len(refs)}")
    pat = re.compile(r"dpi|rate|polling|charge|sleep|light|macro|lod|angle|ripple|hid|usb|report|cmd|mode|button|key|value", re.I)
    for s, v in sorted(refs.items(), key=lambda kv: kv[1][0][0]):
        if pat.search(s):
            print(f"  0x{v[0][0]:x} (file 0x{v[0][0] - BASE:x})  {s[:78]}")
