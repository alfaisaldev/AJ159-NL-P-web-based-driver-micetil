#!/usr/bin/env python3
"""Map a firmware log string to the code that uses it.

The app addresses its log strings as

    0x90145000 + (file offset - 0x30000)

i.e. the string pool is a section that starts at file offset 0x30000 but is
linked at 0x90145000, while the code is linked at 0x90115000 + file offset.
So the runtime address of a string is

    0x90145000 + (file_off - 0x30000)

and the code references it with `lui reg, hi` + `addi reg, reg, lo`.

Usage: python3 tools/rv_str.py <blob> <string-substring> [code_base] [str_base]
"""
import re
import sys

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs

blob = sys.argv[1]
needle = sys.argv[2].encode()
CODE_BASE = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x90115000
STR_BASE = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x90145000
STR_FILE_BASE = 0x30000

data = open(blob, "rb").read()
md = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
md.skipdata = True

targets = [(m.start(), m.group(0).decode()) for m in re.finditer(rb"[ -~]{4,90}", data)
           if needle in m.group(0)]
if not targets:
    raise SystemExit(f"string not found: {needle!r}")

for foff, s in targets:
    runtime = STR_BASE + (foff - STR_FILE_BASE)
    hi, lo = (runtime >> 12) & 0xFFFFF, runtime & 0xFFF
    print(f"string  file 0x{foff:x}  runtime 0x{runtime:x}  (lui {hi:#x} / addi {lo:#x})  {s[:60]!r}")

    hits = []
    insns = [i for i in md.disasm(data, CODE_BASE) if i.mnemonic != ".byte"]
    for k, insn in enumerate(insns):
        if insn.mnemonic != "lui":
            continue
        ops = [o.strip() for o in insn.op_str.split(",")]
        if len(ops) != 2:
            continue
        try:
            imm = int(ops[1].lstrip("#"), 0)
        except ValueError:
            continue
        if imm != hi:
            continue
        reg = ops[0]
        for j in range(k + 1, min(k + 4, len(insns))):
            nxt = insns[j]
            o = [x.strip() for x in nxt.op_str.split(",")]
            if nxt.mnemonic in ("addi", "c.addi") and len(o) == 3 and o[1] == reg:
                try:
                    v = int(o[2].lstrip("#"), 0)
                except ValueError:
                    break
                if v == lo:
                    hits.append((insn.address, nxt.address))
                break
            if nxt.mnemonic in ("addi", "c.addi", "lui", "auipc", "ld", "sd", "jal", "c.jal"):
                break
    print(f"  code references: {len(hits)}")
    for a, b in hits:
        k = next((i for i, x in enumerate(insns) if x.address == b), None)
        if k is None:
            continue
        print(f"\n  --- use at 0x{a:x} / 0x{b:x} ---")
        for i2 in range(max(0, k - 14), min(len(insns), k + 16)):
            x = insns[i2]
            mark = "  <<<" if x.address == b else ""
            print(f"    0x{x.address:x}: {x.mnemonic:9} {x.op_str}{mark}")
