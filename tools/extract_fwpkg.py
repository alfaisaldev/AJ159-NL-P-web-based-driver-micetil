#!/usr/bin/env python3
"""Carve the firmware blobs out of an AJAZZ .fwpkg package.

Container layout (reverse engineered from BurnTool's bs20_all.fwpkg):
    0x00  magic "dfadbeef"
    0x04  u32  (0x6832a)  - total size / build field
    0x08  u32  (0x9f7f4)  - payload size
    0x0c  table: 6 entries x 0x34 bytes
              +0x00  char[32]  file name (NUL padded)
              +0x20  u32        size in flash
              +0x24  u32        size in package
              +0x28  u32        load address
              +0x2c  u32        flags
    0x144 data area: the blobs back to back, in table order

Usage: python3 tools/extract_fwpkg.py <pkg.fwpkg> [outdir]
"""
import os
import struct
import sys

MAGIC = b"\xdf\xad\xbe\xef"
ENTRY_SIZE = 0x34


def main():
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "fw_out"
    data = open(path, "rb").read()
    if data[:4] != MAGIC:
        raise SystemExit("not an fwpkg package")

    os.makedirs(outdir, exist_ok=True)
    print(f"package: {path}  ({len(data)} bytes)")
    print(f"header : field1={struct.unpack_from('<I', data, 4)[0]}  "
          f"field2={struct.unpack_from('<I', data, 8)[0]}")

    # the table starts right after the header; entries are 0x34 bytes
    table_off = 0x0C
    entries = []
    off = table_off
    while off + ENTRY_SIZE <= len(data):
        name = data[off:off + 32].split(b"\x00")[0]
        if not name or not all(32 <= b < 127 for b in name):
            break
        flash_size, pkg_size, addr, flags = struct.unpack_from("<IIII", data, off + 0x20)
        entries.append((name.decode(), flash_size, pkg_size, addr, flags))
        off += ENTRY_SIZE

    data_off = off
    print(f"table  : {len(entries)} entries, data starts at 0x{data_off:x}\n")
    print(f"  {'file':<26}{'flash size':>12}{'pkg size':>11}{'load addr':>13}{'flags':>8}")

    cursor = data_off
    for name, flash_size, pkg_size, addr, flags in entries:
        blob = data[cursor:cursor + pkg_size]
        out = os.path.join(outdir, name)
        with open(out, "wb") as fh:
            fh.write(blob)
        print(f"  {name:<26}{flash_size:>12}{pkg_size:>11}{addr:>#13x}{flags:>8}   -> {out}")
        cursor += pkg_size

    print(f"\ndata consumed: {cursor} / {len(data)} bytes")


if __name__ == "__main__":
    main()
