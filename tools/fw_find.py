#!/usr/bin/env python3
"""Locate code that references a string inside an ARM Thumb firmware blob.

Thumb-2 compilers usually materialise 32-bit constants with a movw/movt pair
rather than a literal pool, so we decode the whole blob and rebuild every
constant the code builds.

Usage:
  python3 tools/fw_find.py <blob> <base_hex>            # list all string refs
  python3 tools/fw_find.py <blob> <base_hex> <string>    # refs to one string
"""
import re
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

blob = sys.argv[1]
BASE = int(sys.argv[2], 0)
needle = sys.argv[3].encode() if len(sys.argv) > 3 else None

data = open(blob, "rb").read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.skipdata = True


def printable_at(addr):
    off = addr - BASE
    if not (0 <= off < len(data)):
        return None
    end = data.find(b"\x00", off, off + 64)
    if end < 0:
        return None
    s = data[off:end]
    if len(s) < 4 or not all(32 <= c < 127 for c in s):
        return None
    return s.decode()


# rebuild movw/movt pairs
pending = {}      # reg -> (value, code_offset)
refs = {}         # string -> [(code_offset, reg)]
reg_of = {}
for insn in md.disasm(data, BASE):
    m = insn.mnemonic
    if m in ("movw", "movt"):
        ops = insn.op_str.split(",")
        try:
            reg = ops[0].strip()
            imm = int(ops[1].strip().lstrip("#"), 0)
        except ValueError:
            continue
        if reg not in reg_of:
            reg_of[reg] = insn.address
        if m == "movw":
            pending[reg] = (imm, insn.address)
        else:
            if reg in pending:
                lo, _ = pending.pop(reg)
                val = (imm << 16) | (lo & 0xFFFF)
                s = printable_at(val)
                if s:
                    refs.setdefault(s, []).append((insn.address, reg))
    else:
        # any other write to the register invalidates the pair
        for reg in list(pending):
            ops = insn.op_str.split(",")
            if ops and ops[0].strip() == reg and not m.startswith("cmp"):
                pass  # keep, movt often follows a movw with other instructions between
        if m not in ("movw", "movt", "nop", "cmp", "str", "strb", "strh"):
            pass

if needle:
    s = printable_at(BASE + data.find(needle)) if needle in data else None
    targets = [needle.decode()] if needle in data else []
    print(f"searching for {needle!r}: string present={needle in data}")
    for t in targets:
        for off, reg in refs.get(t, []):
            print(f"  code 0x{off:x} (file 0x{off - BASE:x}) loads {t!r} via {reg}")
        if t not in refs:
            print(f"  no movw/movt reference found for {t!r}")
    # also show refs to any string containing the needle
    for s, lst in refs.items():
        if needle.decode() in s:
            print(f"  ~ {s!r} -> {[hex(o) for o, _ in lst]}")
else:
    print(f"string references rebuilt from movw/movt: {len(refs)}")
    for s, lst in sorted(refs.items(), key=lambda kv: kv[1][0][0]):
        if re.search(r"dpi|rate|polling|charge|sleep|light|macro|lod|angle|ripple|hid|usb|report|cmd|mode", s, re.I):
            print(f"  0x{lst[0][0]:x} (file 0x{lst[0][0] - BASE:x})  {s[:70]}")
