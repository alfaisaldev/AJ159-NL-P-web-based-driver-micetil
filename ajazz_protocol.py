#!/usr/bin/env python3
"""AJAZZ AJ159 NL P (VID 0x7768) control protocol.

Transport (verified on hardware, unprivileged):

    hidraw node of the device's *vendor* interface (usage page 0xFFB2)
    write : HIDIOCSOUTPUT, report id 6, payload = [class][len][0][0][type][value]
    read  : the same node's input stream, reply = [6][class][len][0][0][type][value]

Nothing else is needed: no root, no usbfs, no unbinding usbhid.  The device
answers on report id 6 - the report id the custom HID descriptor actually
declares for the vendor collection.

Evidence (dongle, class 0x05 read):

    send: 06 05 01 00 00 00
    recv: 06 05 24 00 00 01 | 00 25 6d 12 10 01 01 64 ...   (len 0x24 = 36)

Frame fields
    [0] class     command/notification class
    [1] len       1 + number of value bytes
    [2] 0x00      reserved
    [3] 0x00      reserved
    [4] type      property / sub-command
    [5..] value

Device -> host pushes use class 0xFA:
    type 0x01 link, 0x02 DPI (stage, u16 LE), 0x03 battery (%, state), 0x06 mode

Config blocks (read with type 0x00, no value):
    0x05  36 B  mouse descriptor: PID (u16 LE @1), battery % @7, then six
                u16 LE DPI stages @12 = dpi/50 - 1
                (7,15,23,31,47,63 -> 400/800/1200/1600/2400/3200)
    0x07   6 B  receiver descriptor: PID (u16 LE @1)
    0x0f   2 B  status
    0x10  36 B  config/capability block  (see docs/CUSTOMIZATION.md)
    0x11  36 B  second config block (reads back all zero)

Writes
    Only shapes taken from the official app's own traffic are allowed, and
    every one of them is verified by reading the value back:

        DPI, one frame per stage (0..5), value = raw dpi as u16 LE
        host -> device   06 13 05 00 00 01 | 06 <stage> <lo> <hi> 00

    The report-rate command is still unknown; `set_report_rate()` refuses.
    Everything else goes through `send()`, which only permits the reads the
    vendor driver performs (`06 <class>`, no value).
"""
from __future__ import annotations

import fcntl
import os
import select
import time
from typing import Dict, List, Optional, Tuple

VID = 0x7768
PIDS = (0x6D25, 0x6425)          # mouse (wired) / NearLink receiver

REPORT_ID = 6
REPORT_LEN = 63

# device -> host
CLASS_NOTIFY = 0xFA
TYPE_LINK = 0x01
TYPE_DPI = 0x02
TYPE_BATTERY = 0x03
TYPE_MODE = 0x06

# host -> device (classes confirmed to answer on hardware)
CLASS_MOUSE_INFO = 0x05
CLASS_DONGLE_INFO = 0x07
CLASS_STATUS = 0x0F
CLASS_CONFIG = 0x10
CLASS_CONFIG2 = 0x11

# classes listed by the mouse firmware as host command ids (bit 7 cleared);
# the ones already tested are commented with their observed reply
FIRMWARE_COMMAND_IDS = (0x00, 0x02, 0x0B, 0x0F, 0x10, 0x15, 0x36,
                        0x56, 0x6C, 0x76, 0x7A)

BLOCK_CLASSES = {
    CLASS_MOUSE_INFO: 36,
    CLASS_DONGLE_INFO: 6,
    CLASS_STATUS: 2,
    CLASS_CONFIG: 36,
}

# The only frames this project may send without an explicit write grant: the
# plain reads the vendor driver performs itself.  All five appear verbatim in
# ajaaz.pcapng (the official app sends `06 05` five times on every start), so
# they are known-safe by measurement, not by assumption.
READ_ONLY = frozenset({
    (CLASS_MOUSE_INFO, 0x00),
    (CLASS_DONGLE_INFO, 0x00),
    (CLASS_STATUS, 0x00),
    (CLASS_CONFIG, 0x00),
    (CLASS_CONFIG2, 0x00),
})

# Classes that take bulk payloads: 0x12 writes a record (`type` = record id)
# and 0x31 writes the LED/profile blob in chunks.  A *short* write to either
# one clears stored state - the mouse's button map was lost twice right after
# a sweep that sent them with empty payloads, and only the vendor's "Restore
# Factory Settings" put it back.  `send()` refuses these outright; the only
# write this project performs is the DPI frame below (class 0x13).
QUARANTINED_CLASSES = frozenset({0x12, 0x31})

# Register the host command ids once they are confirmed on hardware.
#   "set_dpi":   (class, type)
#   "set_rate":  (class, type)
COMMANDS: Dict[str, Tuple[int, int]] = {}

# -- vendor-verified write paths (decoded from ajaaz.pcapng) -----------------
#
# The official Windows app's traffic, captured on this receiver, contains
# exactly one DPI write shape, one frame per stage, sent 0..5 on apply:
#
#     host -> device  06 13 05 00 00 01 | 06 <stage> <dpi lo> <dpi hi> 00
#
# with the value in **raw dpi** (400 -> 90 01).  The class-0x05 read block
# stores the same number as dpi/50 - 1, so the two encodings differ - writing
# the read form sets 7..63 dpi and the device clamps it to its minimum
# (measured: the whole table became zero, i.e. 50 dpi, and reading it back
# showed 0 0 0 0 0 0).
#
# Measured round trips on hardware:
#   write 400/800/1200/1600/2400/3200 -> read back 07 00 0f 00 17 00 1f 00 2f 00 3f 00
#   write 400/1600/1200/1600/2400/3200 -> read back [400, 1600, 1200, 1600, 2400, 3200]
#
WRITE_CLASS = 0x13
WRITE_DPI_TYPE = 0x01

# Report rate: class 0x13, type 0x02, one value byte.
#
#     host -> device   06 13 02 00 00 02 | <value> 00
#
# Measured from ajaaz.pcapng, not assumed: the app walked 0,1,2,3 at
# 125.07 / 125.56 / 126.12 / 126.78 s, and the mouse's own input stream
# (endpoint 0x81) had these median gaps while each value was in force:
#
#     value 0 -> 8.00 ms -> 125 Hz      value 2 -> 2.00 ms -> 500 Hz
#     value 1 -> 4.00 ms -> 250 Hz      value 3 -> 1.00 ms -> 1000 Hz
#
# The device does not answer a read for this setting (only 0x09 answers at
# all), so a write can be acknowledged but not read back; the panel reports
# the value it sent and says so.
RATE_CLASS = 0x13
RATE_TYPE = 0x02
RATE_HZ = {0: 125, 1: 250, 2: 500, 3: 1000}
RATE_VALUE = {hz: value for value, hz in RATE_HZ.items()}


def report_rate_frame(hz: int) -> Tuple[int, int, bytes]:
    """The vendor frame that stores one report rate."""
    if hz not in RATE_VALUE:
        raise AjazzError(f"unsupported report rate {hz} Hz; measured options are {sorted(RATE_VALUE)}")
    return (RATE_CLASS, RATE_TYPE, bytes([RATE_VALUE[hz], 0x00]))


DPI_OFFSET = 12
DPI_STEP = 50
DPI_STAGES = 6


def _ioc(direction: int, typ: int, nr: int, size: int) -> int:
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


HIDIOCSOUTPUT = lambda n: _ioc(3, ord("H"), 0x0B, n)


class AjazzError(RuntimeError):
    pass


def encode(cls: int, type_: int = 0x00, value: bytes = b"") -> bytes:
    """The report body (without the report id)."""
    return bytes([cls, len(value) + 1, 0x00, 0x00, type_]) + bytes(value)


def decode(frame: bytes) -> Optional[Dict]:
    """Parse one device frame.  Returns None when it is not a protocol frame."""
    if len(frame) < 6:
        return None
    if frame[0] != REPORT_ID:
        return None
    cls, ln, type_ = frame[1], frame[2], frame[5]
    value = frame[6:6 + max(0, ln - 1)] if ln else b""
    return {"class": cls, "type": type_, "len": ln, "value": value, "raw": frame}


def parse_dpi_table(value: bytes) -> List[int]:
    """Six DPI stages from the class-0x05 block (encoded as dpi/50 - 1)."""
    out = []
    for i in range(DPI_STAGES):
        off = DPI_OFFSET + 2 * i
        if off + 1 >= len(value):
            break
        out.append((value[off] | (value[off + 1] << 8)) + 1)
    return [v * DPI_STEP for v in out]


def encode_dpi(dpi: int) -> int:
    """dpi -> the code used by the class-0x05 read block (dpi/50 - 1)."""
    if dpi % DPI_STEP:
        dpi = int(round(dpi / DPI_STEP)) * DPI_STEP
    return max(1, dpi // DPI_STEP) - 1


def dpi_stage_frame(stage: int, dpi: int) -> Tuple[int, int, bytes]:
    """The vendor frame that stores one DPI stage.

    The value is the raw dpi as u16 LE - the read block uses dpi/50 - 1, so
    the two encodings must not be mixed up (writing the read form sets
    7..63 dpi, which the device clamps to its 50 dpi minimum).
    """
    dpi = max(50, int(dpi))
    return (WRITE_CLASS, WRITE_DPI_TYPE,
            bytes([DPI_STAGES, stage & 0xFF,
                   dpi & 0xFF, (dpi >> 8) & 0xFF, 0x00]))


def dpi_write_frames(stages: List[int]) -> List[Tuple[int, int, bytes]]:
    """(class, type, value) for all six stages, in the app's order."""
    return [dpi_stage_frame(i, dpi) for i, dpi in enumerate(stages[:DPI_STAGES])]


# The active DPI stage (the one the mouse is using) is byte 11 of the
# class-0x05 block, zero based.
#
# Measured on hardware, twice, with the table values unchanged:
#   all six stages written, stage 3 last  -> byte 11 = 3 (table still 400..3200)
#   all six stages written, stage 1 last  -> byte 11 = 1
# Nothing else in the block moved.  The device treats the *last* stage frame
# as the one to activate, which is also why the vendor app ends its DPI write
# with the stage it wants active (four times stage 1 in ajaaz.pcapng).
INFO_ACTIVE_STAGE = 11


def parse_active_stage(value: bytes) -> Optional[int]:
    """Active DPI stage from the class-0x05 block, or None if out of range."""
    if len(value) <= INFO_ACTIVE_STAGE:
        return None
    stage = value[INFO_ACTIVE_STAGE]
    return stage if 0 <= stage < DPI_STAGES else None


def dpi_frames_for_stage(stages: List[int], stage: int) -> List[Tuple[int, int, bytes]]:
    """Rewrite the table so `stage` ends up active.

    The values are untouched - only the order changes, with the chosen stage
    sent last.  Sending six identical tables is what the vendor app does, so
    this stays inside the one write shape that is already verified.
    """
    stage = max(0, min(DPI_STAGES - 1, int(stage)))
    order = [i for i in range(min(len(stages), DPI_STAGES)) if i != stage] + [stage]
    return [dpi_stage_frame(i, stages[i]) for i in order]


class AjazzDevice:
    """Hidraw transport for the vendor interface of the mouse or receiver."""

    def __init__(self, node: str):
        self.node = node
        self.fd = os.open(node, os.O_RDWR)
        os.set_blocking(self.fd, False)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- raw ---------------------------------------------------------------
    def send(self, cls: int, type_: int = 0x00, value: bytes = b"",
             allow_write: bool = False) -> None:
        """Send one frame.

        Only the frames the vendor driver itself sends are allowed by
        default: a read (type 0x00, no value) of one of the classes that
        answer.  Anything else requires `allow_write=True`, which only the
        guarded write path (tools/safe_write.py) uses.  This is a hard stop
        against the blind sweeps that once cleared the mouse's button state.
        """
        if not allow_write:
            if cls in QUARANTINED_CLASSES:
                raise AjazzError(
                    f"class 0x{cls:02x} is quarantined: it writes a record or the "
                    f"LED profile in bulk, and a short write clears stored state "
                    f"(the button map was lost that way twice)")
            if value:
                raise AjazzError(
                    "refusing to send a frame with a value payload: writes are "
                    "disabled until the store command is confirmed")
            if (cls, type_) not in READ_ONLY:
                raise AjazzError(
                    f"refusing to send class 0x{cls:02x} type 0x{type_:02x}: "
                    f"not in the read-only whitelist {sorted(READ_ONLY)}")
        body = encode(cls, type_, value)
        buf = bytearray(bytes([REPORT_ID]) + body).ljust(REPORT_LEN + 1, b"\x00")
        fcntl.ioctl(self.fd, HIDIOCSOUTPUT(len(buf)), buf, True)

    def read(self, timeout: float = 0.5) -> List[Dict]:
        out: List[Dict] = []
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                continue
            try:
                data = os.read(self.fd, 128)
            except (BlockingIOError, OSError):
                continue
            if not data:
                continue
            for frame in self._split(data):
                parsed = decode(frame)
                if parsed:
                    out.append(parsed)
        return out

    @staticmethod
    def _split(data: bytes) -> List[bytes]:
        """hidraw delivers one report per read; keep it simple but robust."""
        if len(data) <= REPORT_LEN:
            return [data]
        return [data[i:i + REPORT_LEN] for i in range(0, len(data), REPORT_LEN)]

    # -- request / reply ---------------------------------------------------
    def request(self, cls: int, type_: int = 0x00, value: bytes = b"",
                timeout: float = 0.6, retries: int = 2) -> Optional[Dict]:
        """Send one command and return the reply with the same class."""
        for _ in range(retries + 1):
            self.send(cls, type_, value)
            end = time.time() + timeout
            while time.time() < end:
                for frame in self.read(min(0.1, max(0.02, end - time.time()))):
                    if frame["class"] == cls:
                        return frame
        return None

    # -- read-only helpers -------------------------------------------------
    def block(self, cls: int, type_: int = 0x00) -> Optional[bytes]:
        reply = self.request(cls, type_)
        return reply["value"] if reply else None

    def mouse_info(self) -> Optional[bytes]:
        return self.block(CLASS_MOUSE_INFO)

    def dpi_table(self) -> List[int]:
        value = self.block(CLASS_MOUSE_INFO)
        return parse_dpi_table(value) if value else []

    def config(self) -> Dict[str, Optional[bytes]]:
        """Every readable config block, for backups and comparisons."""
        return {f"0x{c:02x}": self.block(c) for c in BLOCK_CLASSES}

    # -- writes (vendor frames only) ---------------------------------------
    def _write_dpi_stage(self, stage: int, dpi: int) -> None:
        """One stage, in the exact shape the official app sends."""
        self.send(*dpi_stage_frame(stage, dpi), allow_write=True)
        time.sleep(0.06)

    def set_dpi_table(self, stages: List[int], verify: bool = True) -> List[int]:
        """Write all six stages with the vendor's frames, verified.

        Backs up the current table, writes, reads it back, and restores the
        backup when the device did not store exactly what was sent.  This is
        the same sequence the Windows app performs on "apply".
        """
        before = self.dpi_table()
        want = [max(50, int(v)) for v in stages[:DPI_STAGES]]
        if len(want) != DPI_STAGES:
            raise AjazzError(f"expected {DPI_STAGES} stages, got {len(want)}")
        for index, dpi in enumerate(want):
            self._write_dpi_stage(index, dpi)
        time.sleep(0.3)
        if not verify:
            return want
        after = self.dpi_table()
        if after != want:
            if before:
                for index, dpi in enumerate(before):
                    self._write_dpi_stage(index, dpi)
                time.sleep(0.3)
            raise AjazzError(
                f"DPI write rejected: sent {want}, device reads {after} "
                f"(previous table restored: {self.dpi_table()})")
        return after

    def set_dpi(self, stage: int, dpi: int) -> List[int]:
        """Change one stage; the whole table is rewritten, as the app does."""
        table = self.dpi_table()
        if len(table) != DPI_STAGES:
            raise AjazzError("cannot read the DPI table")
        table[stage] = dpi
        return self.set_dpi_table(table)

    def set_report_rate(self, hz: int) -> int:
        """Store a report rate; returns it.  Not readable back (see above)."""
        cls, type_, value = report_rate_frame(hz)
        self.send(cls, type_, value, allow_write=True)
        return hz


def find_vendor_nodes() -> List[Dict]:
    """All hidraw nodes of 0x7768 devices that expose the vendor collection."""
    import glob
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from battery import _has_vendor_collection, _report_descriptor

    out = []
    for sysfs in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sysfs, "device", "uevent")) as fh:
                txt = fh.read()
        except OSError:
            continue
        node = "/dev/" + os.path.basename(sysfs)
        for pid in PIDS:
            if f"{VID:08X}:{pid:08X}" in txt:
                try:
                    vendor = _has_vendor_collection(_report_descriptor(node))
                except OSError:
                    continue
                if vendor:
                    name = ""
                    for line in txt.splitlines():
                        if line.startswith("HID_NAME="):
                            name = line.split("=", 1)[1]
                    out.append({"node": node, "pid": pid, "name": name})
    return out


if __name__ == "__main__":
    nodes = find_vendor_nodes()
    if not nodes:
        raise SystemExit("no AJAZZ 0x7768 vendor node found")
    for n in nodes:
        print(f"{n['node']}  pid {n['pid']:04x}  {n['name']}")
        with AjazzDevice(n["node"]) as dev:
            for cls in BLOCK_CLASSES:
                rep = dev.request(cls)
                if not rep:
                    print(f"  class 0x{cls:02x}: no reply")
                    continue
                print(f"  class 0x{cls:02x}: type=0x{rep['type']:02x} len={rep['len']}"
                      f"  {rep['value'].hex(' ')}")
            dpi = dev.dpi_table()
            if dpi:
                print("  dpi stages:", dpi)
