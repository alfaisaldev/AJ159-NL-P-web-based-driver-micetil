#!/usr/bin/env python3
"""Read-only map of the (class, type) command space.

Every frame carries *no value bytes* (len = 1), so a setter has nothing to
store - this probe cannot change a setting.  It records which (class, type)
pairs answer and what they answer, and it proves afterwards that every
readable config block is byte-identical to the baseline.

Run: python3 tools/probe_classes.py [--pid 0x6425]
"""
import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ajazz_protocol import (AjazzDevice, BLOCK_CLASSES, CLASS_MOUSE_INFO,
                            FIRMWARE_COMMAND_IDS, find_vendor_nodes)

EXTRA = [0x02, 0x06, 0x12, 0x30, 0x31]
TYPES = range(0x00, 0x10)


def digest(blocks):
    h = hashlib.sha256()
    for cls in sorted(blocks):
        h.update(str(cls).encode())
        h.update(b"-" if blocks[cls] is None else blocks[cls])
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=None)
    args = ap.parse_args()

    nodes = [n for n in find_vendor_nodes()
             if args.pid is None or n["pid"] == args.pid]
    if not nodes:
        raise SystemExit("no matching AJAZZ vendor node")

    for node in nodes:
        print(f"== {node['node']}  pid {node['pid']:04x}  {node['name']}")
        with AjazzDevice(node["node"]) as dev:
            base = dev.config()
            before = digest(base)
            print("   baseline blocks:")
            for cls, val in base.items():
                print(f"      {cls}: {val.hex(' ') if val else None}")
            print(f"   baseline digest {before}\n")

            classes = sorted(set(list(FIRMWARE_COMMAND_IDS) + EXTRA + list(BLOCK_CLASSES)))
            for cls in classes:
                hits = []
                for t in TYPES:
                    rep = dev.request(cls, t, b"", timeout=0.35, retries=0)
                    if not rep:
                        continue
                    hits.append(rep)
                if not hits:
                    continue
                print(f"   class 0x{cls:02x}:")
                for rep in hits:
                    val = rep["value"]
                    print(f"      type 0x{rep['type']:02x} len={rep['len']:2d}  {val.hex(' ')}")

            after_blocks = dev.config()
            after = digest(after_blocks)
            print(f"\n   digest after probe {after}  ->",
                  "UNCHANGED" if after == before else "*** CHANGED ***")
            if after != before:
                for cls in base:
                    if base[cls] != after_blocks.get(cls):
                        print(f"      {cls}: {base[cls]} -> {after_blocks.get(cls)}")


if __name__ == "__main__":
    main()
