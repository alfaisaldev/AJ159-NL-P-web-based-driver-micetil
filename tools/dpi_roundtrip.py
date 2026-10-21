#!/usr/bin/env python3
"""Round-trip the DPI table using the vendor's own frame, and verify it.

The frame comes straight out of ajaaz.pcapng (the official Windows app,
captured on this same receiver):

    host -> device  06 13 05 00 00 01 | 06 <stage> <dpi lo> <dpi hi> 00
    device -> host  06 05 24 00 00 01 | ...  six u16 LE @12 = dpi/50 - 1

The app sends one frame per stage, 0..5, when a setting is applied.

Usage:
    python3 tools/dpi_roundtrip.py            # no-op: write the current table back
    python3 tools/dpi_roundtrip.py 1 1600     # stage 1 := 1600 dpi, then restore
    python3 tools/dpi_roundtrip.py 1 1600 --keep
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ajazz_protocol import AjazzDevice, find_vendor_nodes, parse_dpi_table  # noqa: E402

WRITE_CLASS = 0x13
WRITE_TYPE = 0x01
STAGES = 6


def raw_table(dev):
    """The six u16 codes (dpi/50 - 1) as stored, for an exact comparison."""
    value = dev.block(0x05)
    if not value:
        return None, None
    codes = [value[12 + 2 * i] | (value[13 + 2 * i] << 8) for i in range(STAGES)]
    return value, codes


def write_table(dev, dpi_values):
    """Send the vendor's six per-stage frames.

    The value here is the **raw DPI as u16 LE** (400 -> 90 01), unlike the
    class-0x05 read block which stores dpi/50 - 1.  Sending the read form
    here sets 7..63 dpi instead; the device clamps that to its minimum.
    """
    for stage, dpi in enumerate(dpi_values):
        dpi = max(50, int(dpi))
        body = bytes([STAGES, stage, dpi & 0xFF, (dpi >> 8) & 0xFF, 0x00])
        dev.send(WRITE_CLASS, WRITE_TYPE, body, allow_write=True)
        time.sleep(0.08)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = "--keep" in sys.argv

    nodes = find_vendor_nodes()
    if not nodes:
        raise SystemExit("no AJAZZ 0x7768 vendor node")
    node = nodes[0]["node"]
    print(f"node {node}  ({nodes[0]['name']})")

    with AjazzDevice(node) as dev:
        raw_before, codes_before = raw_table(dev)
        dpi_before = parse_dpi_table(raw_before)
        print("before  codes", codes_before, " dpi", dpi_before)

        target = list(dpi_before)
        if args:
            stage, dpi = int(args[0]), int(args[1])
            target[stage] = dpi
            print(f"target  stage {stage} := {dpi} dpi -> {target}")

        write_table(dev, target)
        time.sleep(0.5)

        raw_after, codes_after = raw_table(dev)
        print("after   codes", codes_after, " dpi", parse_dpi_table(raw_after))

        if codes_after == [int(round(d / 50)) - 1 for d in target]:
            print("RESULT: device stored exactly what was sent")
        else:
            print("RESULT: MISMATCH - restoring the backup table")
            write_table(dev, dpi_before)
            time.sleep(0.5)
            print("restored codes", raw_table(dev)[1])

        if args and not keep:
            write_table(dev, dpi_before)
            time.sleep(0.5)
            print("reverted to", raw_table(dev)[1])


if __name__ == "__main__":
    main()
