#!/usr/bin/env python3
"""Find the xrefs to a string inside a PE32 file, and dump the code around them.

Usage: python3 tools/pxref.py <file.exe> <string> [context_insns]
"""
import re
import struct
import subprocess
import sys


def sections(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    size_opt = struct.unpack_from("<H", data, pe + 20)[0]
    image_base = struct.unpack_from("<I", data, opt + 28)[0]
    sec_off = opt + size_opt
    out = []
    for i in range(nsec):
        o = sec_off + i * 40
        name = data[o:o + 8].rstrip(b"\x00").decode(errors="replace")
        vsize, vaddr, rawsize, rawoff = struct.unpack_from("<IIII", data, o + 8)
        out.append((name, vaddr, vsize, rawoff, rawsize))
    return image_base, out


def file_to_va(image_base, secs, offset):
    for name, vaddr, vsize, rawoff, rawsize in secs:
        if rawoff <= offset < rawoff + rawsize:
            return image_base + vaddr + (offset - rawoff)
    return None


def main():
    path, needle = sys.argv[1], sys.argv[2].encode()
    ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    data = open(path, "rb").read()
    image_base, secs = sections(data)

    hits = []
    start = 0
    while True:
        i = data.find(needle, start)
        if i < 0:
            break
        va = file_to_va(image_base, secs, i)
        hits.append((i, va))
        start = i + 1
    print(f"'{needle.decode()}' found {len(hits)} time(s):")
    for off, va in hits:
        print(f"  file 0x{off:x}  ->  VA 0x{va:x}" if va else f"  file 0x{off:x} (no VA)")

    if not hits:
        return
    va = hits[0][1]
    if va is None:
        return
    # disassemble the whole .text and find references to that VA
    dis = subprocess.run(["objdump", "-d", "--no-show-raw-insn", path],
                         capture_output=True, text=True).stdout
    lines = dis.splitlines()
    target = f"0x{va:x}"
    refs = [n for n, l in enumerate(lines) if target in l and ("push" in l or "mov" in l or "lea" in l)]
    print(f"\nreferences to 0x{va:x}: {len(refs)}")
    for n in refs[:6]:
        print("\n" + "\n".join(lines[max(0, n - 6): n + 4]))


if __name__ == "__main__":
    main()
