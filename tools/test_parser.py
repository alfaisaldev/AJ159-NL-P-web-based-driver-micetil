#!/usr/bin/env python3
"""Replay the frames captured from the real dongle through the parser."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from battery import parse_status_packet  # noqa: E402

FRAMES = [
    ("battery", "06 fa 03 00 00 03 64 00 00 00 00 00 00 00 00 00"),
    ("battery", "06 fa 03 00 00 03 64 00 00 00 00 00 00 00 00 00"),
    ("battery+chg", "06 fa 03 00 00 03 64 01 00 00 00 00 00 00 00 00"),
    ("dpi 1200", "06 fa 04 00 00 02 02 b0 04 00 00 00 00 00 00 00 00"),
    ("dpi 1600", "06 fa 04 00 00 02 03 40 06 00 00 00 00 00 00 00 00"),
    ("dpi 2400", "06 fa 04 00 00 02 04 60 09 00 00 00 00 00 00 00 00"),
    ("dpi 3200", "06 fa 04 00 00 02 05 80 0c 00 00 00 00 00 00 00 00"),
    ("dpi  400", "06 fa 04 00 00 02 00 90 01 00 00 00 00 00 00 00 00"),
    ("dpi  800", "06 fa 04 00 00 02 01 20 03 00 00 00 00 00 00 00 00"),
    ("link 0", "06 fa 02 00 00 01 00 00 00 00 00 00 00 00 00 00"),
    ("link 1", "06 fa 02 00 00 01 01 00 00 00 00 00 00 00 00 00 00"),
    ("mode 0", "06 fa 02 00 00 06 00 00 00 00 00 00 00 00 00 00"),
    ("garbage", "06 fa 03 00 00 03 ff 00 00 00 00 00 00 00 00 00"),
    ("not a frame", "01 00 01 00 00 00 00 00 00 00"),
]

for label, hexstr in FRAMES:
    raw = bytes.fromhex(hexstr)
    print(f"{label:12} -> {parse_status_packet(raw)}")
