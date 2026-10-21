#!/usr/bin/env python3
"""Find ARM Thumb code that references a runtime address, and show the
constants compared in the surrounding function.

Usage: python3 tools/fw_xref.py <blob> <runtime_addr_hex> [search_from] [search_to]
"""
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_OP_MEM

blob = sys.argv[1]
target = int(sys.argv[2], 0)
frm = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0
to = int(sys.argv[4], 0) if len(sys.argv) > 4 else None

data = open(blob, "rb").read()
if to is None:
    to = len(data)

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

hits = []
for insn in md.disasm(data[frm:to], frm):
    if insn.mnemonic.startswith("ldr") and len(insn.operands) == 2:
        op = insn.operands[1]
        if op.type == ARM_OP_MEM and op.mem.base == 13 and op.mem.disp is not None:
            lit = ((insn.address + 4) & ~3) + op.mem.disp
            if 0 <= lit < len(data) - 3:
                val = struct.unpack_from("<I", data, lit)[0]
                if val == target:
                    hits.append((insn.address, lit, val))

print(f"references to 0x{target:x}: {len(hits)}")
for addr, lit, val in hits:
    print(f"\n  ldr at 0x{addr:x} (literal pool 0x{lit:x})")
    # show the constants compared in the +-0x80 bytes around the load
    lo, hi = max(frm, addr - 0x100), min(to, addr + 0x120)
    for insn in md.disasm(data[lo:hi], lo):
        mark = "  <<<" if insn.address == addr else ""
        if insn.mnemonic in ("cmp", "mov", "movs", "add", "sub", "and", "orr", "ldr", "strb", "strh", "str", "ldrb", "push", "pop", "bl", "b") or mark:
            print(f"    0x{insn.address:x}:  {insn.mnemonic:8} {insn.op_str}{mark}")
