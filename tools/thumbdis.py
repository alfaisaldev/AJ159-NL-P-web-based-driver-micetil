#!/usr/bin/env python3
"""Disassemble ARM Thumb code from an AJAZZ firmware blob.

Usage: python3 tools/thumbdis.py <blob> <start_hex> [end_hex] [base_hex]
"""
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

blob = sys.argv[1]
start = int(sys.argv[2], 0)
end = int(sys.argv[3], 0) if len(sys.argv) > 3 else start + 0x200
base = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x90115000

data = open(blob, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = False

for insn in md.disasm(data[start:end], base + start):
    line = f"  0x{insn.address:x}:  {insn.mnemonic:8} {insn.op_str}"
    print(line)
