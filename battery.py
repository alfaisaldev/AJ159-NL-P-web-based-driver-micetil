"""
AJAZZ AJ159 NL P (NearLink) — battery reader.

Device
------
The USB device 7768:6425 ("AJAZZ AJAZZ NearLink") is the NearLink dongle.
It exposes two HID interfaces:

  * interface 0 — the classic mouse (report ids 1..4, no feature reports)
  * interface 1 — the vendor collection:
        usage page 0xFFB1 : report id 8  — 12 byte feature (LED state)
        usage page 0xFFB2 : report id 6  — 63 byte INPUT  (status packet)
        usage page 0xFFB3 : report id 7  —  9 byte feature + input

Battery
-------
The dongle relays the mouse's telemetry as a 63-byte interrupt-IN packet
with report id 6, roughly every 30 seconds. The frame is one TLV entry
behind a 5 byte header:

    offset 0 : report id       0x06
    offset 1 : message id      0xfa   (unsolicited status push)
    offset 2 : entry length    L      (1 tag byte + L-1 value bytes)
    offset 3 : reserved        0x00
    offset 4 : reserved        0x00
    offset 5 : tag
    offset 6 : value (L-1 bytes)

Known tags (confirmed against live hardware):

    0x01  link state   1 byte   flips 0 <-> 1 when the mouse switches
                                   between NearLink and Bluetooth
    0x02  DPI          3 bytes  stage index, then the stage value as a
                                   little-endian u16 — the AJ159 NL P
                                   reports 400/800/1200/1600/2400/3200
    0x03  battery      2 bytes  percentage, then a charging flag
    0x06  mode         1 byte

so the battery entry is

    06 fa 03 00 00 03 64 00
                  |  |  +-- charging flag (1 = the mouse is on USB power)
                  |  +----- percentage = 0x64 = 100 %
                  +-------- tag 0x03 = battery level

The reading is therefore event-driven: we keep a listener on the vendor
node and the panel shows the most recent packet the dongle pushed.
"""

from __future__ import annotations

import json
import os
import re
import select
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Dict, List, Optional

AJAZZ_VID = 0x7768
AJAZZ_PID = 0x6425  # the NearLink receiver (dongle)

# Known AJAZZ mice/receivers and where to find the battery. The mouse
# itself (wired over USB) is preferred: it reports faster (10 s instead of
# 30 s) and also reports whether it is charging.
KNOWN_DEVICES = {
    0x6D25: ("AJ159 NL P (wired)", 0),  # lower number = preferred
    0x6425: ("NearLink receiver", 1),
}

VENDOR_USAGE_PAGE = 0xFFB2  # the interface that carries the status packet
STATUS_REPORT_ID = 0x06
STATUS_MESSAGE_ID = 0xFA

# vendor command channel (same report as the status pushes, different class)
VENDOR_REPORT_ID = 0x06
VENDOR_REPORT_LEN = 64

# The dongle pushes status on its own schedule (measured ~30 s, and only while
# the mouse is awake).  The same numbers are available on demand in the
# class-0x05 info block, which the vendor app reads on every start - so poll
# it, and the panel always shows a measured value instead of waiting.
INFO_CLASS = 0x05
INFO_POLL_SECONDS = 15.0
INFO_RETRY_SECONDS = 5.0

# Last good reading, so a restart (or a mouse that is asleep) still shows a
# real number with its age instead of "--".
STATE_FILE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "ajazz-panel", "last.json")
INFO_PERCENT = 7      # battery % in the info block
INFO_RATE = 24        # report-rate index in the info block (0..3)
RATE_HZ = {0: 125, 1: 250, 2: 500, 3: 1000}

# Every distinct battery reading is appended here, so "is it stuck?" is a
# question with a datable answer instead of an opinion.
LOG_FILE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "ajazz-panel", "battery.log")


def _private_dir(path: str) -> None:
    """Create the state directory, readable by its owner only.

    The panel's state is small, but there is no reason for it to be
    world-readable on a shared machine.
    """
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _ioc(direction: int, typ: int, nr: int, size: int) -> int:
    return (direction << 30) | ((size & 0xFFFF) << 16) | ((typ & 0xFF) << 8) | (nr & 0xFF)


HIDIOCSOUTPUT = lambda n: _ioc(3, ord("H"), 0x0B, n)


def _write_frame(fd: int, cls: int, type_: int, value: bytes) -> None:
    """Send one vendor frame on the node the reader already owns."""
    import fcntl

    body = bytes([VENDOR_REPORT_ID, cls, len(value) + 1, 0x00, 0x00, type_]) + bytes(value)
    buf = bytearray(body).ljust(VENDOR_REPORT_LEN, b"\x00")
    fcntl.ioctl(fd, HIDIOCSOUTPUT(len(buf)), buf, True)


def _decode_reply(frame: bytes) -> Optional[Dict]:
    if len(frame) < 6 or frame[0] != VENDOR_REPORT_ID:
        return None
    ln, type_ = frame[2], frame[5]
    return {
        "class": frame[1],
        "type": type_,
        "len": ln,
        "value": frame[6:6 + ln] if ln else b"",
    }
HEADER_LEN = 5  # id, message id, entry length, 2 reserved bytes
TAG_LINK = 0x01
TAG_DPI = 0x02
TAG_BATTERY = 0x03
TAG_MODE = 0x06


@dataclass
class BatteryReading:
    percent: Optional[int] = None
    ok: bool = False
    detail: str = "waiting for the dongle's status packet…"
    node: str = ""
    device: str = ""
    raw: str = ""
    updated_at: float = 0.0
    dpi: Optional[int] = None
    dpi_stage: Optional[int] = None
    link: Optional[int] = None
    mode: Optional[int] = None
    charging: bool = False
    charge_state: Optional[int] = None
    source: str = ""
    since: float = 0.0
    rate_hz: Optional[int] = None

    @property
    def is_charging(self) -> bool:
        """True only when the mouse itself says it is on USB power.

        The receiver always relays charge state 1, so trust it only when
        the reading came from the mouse's own wired interface.
        """
        if self.charge_state is None:
            return False
        if "receiver" in (self.source or "").lower():
            return False
        return self.charge_state == 1

    def as_dict(self) -> Dict:
        age = (time.time() - self.updated_at) if self.updated_at else None
        return {
            "percent": self.percent,
            "since": int(self.since * 1000) if self.since else 0,
            "rateHz": self.rate_hz,
            "ok": self.ok,
            "detail": self.detail,
            "node": self.node,
            "device": self.device,
            "source": self.source,
            "charging": self.is_charging,
            "chargeState": self.charge_state,
            "raw": self.raw,
            "updatedAt": int(self.updated_at * 1000) if self.updated_at else 0,
            "age": int(age) if age is not None else None,
            "dpi": self.dpi,
            "dpiStage": self.dpi_stage,
            "link": self.link,
            "mode": self.mode,
        }


def claim_device(fd: int, path: str = "") -> None:
    """Take an exclusive advisory lock on a hidraw node.

    hidraw is not multicast: if two processes read the same node they split
    the frame stream, so the panel would silently swallow the mouse's
    telemetry (and any reply to a command).  The lock makes the ownership
    explicit - a second process gets EAGAIN instead of half the frames.
    """
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        where = f" ({path})" if path else ""
        raise OSError(
            exc.errno,
            f"another process already owns the HID node{where}: {exc.strerror}",
        ) from exc


def _claim_device(fd: int, path: str) -> None:
    claim_device(fd, path)


def _report_descriptor(path: str) -> bytes:
    """Read the raw HID report descriptor from sysfs (world readable)."""
    base = os.path.join("/sys/class/hidraw", os.path.basename(path), "device")
    try:
        with open(os.path.join(base, "report_descriptor"), "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _has_vendor_collection(descriptor: bytes) -> bool:
    """True if the descriptor declares the vendor usage page we need."""
    # Usage Page (0xFFB2) -> item 06 B2 FF
    return b"\x06\xb2\xff" in descriptor


def find_vendor_nodes(vid: int = AJAZZ_VID) -> List[Dict]:
    """Return every AJAZZ hidraw node that carries the vendor collection.

    Each entry: {"path", "pid", "name", "rank"}. The mouse's own wired
    interface ranks before the receiver, because it reports faster and
    knows whether the battery is charging.
    """
    found: List[Dict] = []
    try:
        names = sorted(n for n in os.listdir("/dev") if n.startswith("hidraw"))
    except OSError:
        return found
    for name in names:
        path = f"/dev/{name}"
        try:
            with open(f"/sys/class/hidraw/{name}/device/uevent") as fh:
                uevent = fh.read()
        except OSError:
            continue
        m = re.search(r"HID_ID=0003:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})", uevent)
        if not m or int(m.group(1), 16) != vid:
            continue
        pid = int(m.group(2), 16)
        if not _has_vendor_collection(_report_descriptor(path)):
            continue
        label, rank = KNOWN_DEVICES.get(pid, (f"unknown ({pid:04x})", 9))
        found.append({"path": path, "pid": pid, "name": label, "rank": rank})
    found.sort(key=lambda d: (d["rank"], d["path"]))
    return found


def parse_status_packet(packet: bytes) -> Dict:
    """Decode a vendor status frame into its tag/value entry.

    Returns a dict with ``tag``, ``value`` and the decoded fields. An empty
    dict is returned for anything that is not a status frame.
    """
    if len(packet) < HEADER_LEN + 2:
        return {}
    if packet[0] != STATUS_REPORT_ID or packet[1] != STATUS_MESSAGE_ID:
        return {}

    length = packet[2]
    tag = packet[HEADER_LEN]
    value = packet[HEADER_LEN + 1 : HEADER_LEN + length]
    if len(value) != max(0, length - 1):
        return {}

    out: Dict = {"tag": tag, "value": value.hex(" ")}
    if tag == TAG_BATTERY and len(value) >= 1:
        percent = value[0]
        if percent <= 100:
            out["percent"] = percent
        if len(value) >= 2:
            # charge state: 1 = charging, 2 = running on battery. Only the
            # mouse itself reports it truthfully - the receiver always
            # relays 1 - so the caller checks the source.
            out["chargeState"] = value[1]
    elif tag == TAG_DPI and len(value) >= 3:
        out["dpiStage"] = value[0]
        out["dpi"] = int.from_bytes(value[1:3], "little")
    elif tag == TAG_LINK and len(value) >= 1:
        out["link"] = value[0]
    elif tag == TAG_MODE and len(value) >= 1:
        out["mode"] = value[0]
    return out


class AjazzBattery:
    """Listens for the dongle's status packets and keeps the last reading."""

    def __init__(self, vid: int = AJAZZ_VID, pid: int = AJAZZ_PID):
        self.vid = vid
        self.pid = pid
        self._lock = threading.Lock()
        self._reading = BatteryReading(device=f"{vid:04x}:{pid:04x}")
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._node: Optional[str] = None
        self._queue: "Queue[Dict]" = Queue()
        self._next_poll = 0.0
        self._rescan_at = 0.0
        self._load_state()
        self._load_log_tail()

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def rate_hz(self) -> Optional[int]:
        """Report rate, read back from the info block (byte 24 = index)."""
        reply = self.command(0x05)
        if not reply or len(reply["value"]) <= INFO_RATE:
            return None
        return RATE_HZ.get(reply["value"][INFO_RATE])

    def dpi_table(self) -> List[int]:
        """The six DPI stages, read from the class-0x05 block."""
        reply = self.command(0x05)
        if not reply:
            return []
        from ajazz_protocol import parse_dpi_table

        return parse_dpi_table(reply["value"])

    def dpi_info(self) -> Dict:
        """Table plus the stage the mouse is actually on (byte 11)."""
        from ajazz_protocol import parse_active_stage, parse_dpi_table

        reply = self.command(0x05)
        if not reply:
            raise TimeoutError("the mouse did not answer the DPI read")
        return {"table": parse_dpi_table(reply["value"]),
                "active": parse_active_stage(reply["value"]),
                "raw": reply["value"].hex(" ")}

    def _write_dpi_frames(self, frames) -> None:
        for cls, type_, value in frames:
            self.command(cls, type_, value, want_reply=False)
            time.sleep(0.06)
        time.sleep(0.3)

    def _confirm_dpi(self, table: List[int], active: Optional[int],
                     timeout: float = 3.0):
        """Wait for the device to show exactly this table and active stage.

        The receiver relays writes, so its next read can still return the
        previous block; polling for the expected state is what makes the
        verification honest instead of a race.
        """
        last = None
        end = time.time() + timeout
        while True:
            last = self.dpi_info()
            if last["table"] == table and last["active"] == active:
                return True, last
            if time.time() >= end:
                return False, last
            time.sleep(0.25)

    def set_dpi_stage(self, stage: int) -> Dict:
        """Make `stage` the active one, then read the device back.

        Verified path: the table is rewritten with the chosen stage last and
        the device reports it in byte 11.  On a mismatch the previous stage is
        written back, so a failed call never leaves the mouse on a stage the
        caller did not ask for.
        """
        from ajazz_protocol import DPI_STAGES, dpi_frames_for_stage

        before = self.dpi_info()
        table, current = before["table"], before["active"]
        if len(table) != DPI_STAGES:
            raise OSError("cannot read the DPI table")
        if current == stage:
            return {"stage": stage, "dpi": table[stage], "table": table,
                    "changed": False}
        self._write_dpi_frames(dpi_frames_for_stage(table, stage))
        ok, after = self._confirm_dpi(table, stage)
        if not ok:
            if current is not None:
                self._write_dpi_frames(dpi_frames_for_stage(after["table"] or table, current))
                self._confirm_dpi(table, current)
            raise OSError(f"device kept stage {after['active']}, wanted {stage}; "
                          f"restored stage {current}")
        return {"stage": after["active"], "dpi": after["table"][stage],
                "table": after["table"], "changed": True}

    # -- reading -------------------------------------------------------------
    def snapshot(self) -> Dict:
        with self._lock:
            return self._reading.as_dict()

    def _set(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._reading, key, value)

    # -- commands -------------------------------------------------------------
    def command(self, cls: int, type_: int = 0x00, value: bytes = b"",
                timeout: float = 2.0, want_reply: bool = True) -> Optional[Dict]:
        """Send one vendor frame and return the reply of the same class.

        hidraw is not multicast and this reader owns the node, so the frame is
        handed to the listener thread, which writes it on the fd it already
        holds and picks the matching reply out of the input stream.
        """
        req = {
            "cls": cls, "type": type_, "value": value, "timeout": timeout,
            "want_reply": want_reply, "reply": None, "error": None,
            "event": threading.Event(),
        }
        self._queue.put(req)
        if not req["event"].wait(timeout + 1.0):
            raise TimeoutError(f"no reply to class 0x{cls:02x}")
        if req["error"]:
            raise OSError(req["error"])
        return req["reply"]

    def _load_state(self) -> None:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        percent = data.get("percent")
        if isinstance(percent, int) and 0 <= percent <= 100:
            self._set(percent=percent, ok=True,
                      updated_at=float(data.get("updated_at") or 0.0),
                      since=float(data.get("since") or 0.0),
                      detail="last known reading")

    def _load_log_tail(self) -> None:
        try:
            with open(LOG_FILE, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - 200))
                last = fh.read().decode("utf-8", "replace").strip().splitlines()[-1]
            self._logged = int(last.split()[1])
        except (OSError, IndexError, ValueError):
            pass

    def _log_reading(self, percent: int) -> None:
        """Append a line only when the number actually changes."""
        state = self._reading.charge_state
        if getattr(self, "_logged", None) == percent:
            return
        self._logged = percent
        try:
            _private_dir(os.path.dirname(LOG_FILE))
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write("%s %3d %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                                          percent,
                                          "-" if state is None else state))
        except OSError:
            pass

    def _save_state(self) -> None:
        try:
            _private_dir(os.path.dirname(STATE_FILE))
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump({"percent": self._reading.percent,
                           "since": self._reading.since,
                           "updated_at": self._reading.updated_at}, fh)
        except OSError:
            pass

    def _apply_info(self, value: bytes) -> None:
        """Battery level from the class-0x05 info block (a real read).

        Measured layout: byte 1..2 = product id, byte 7 = battery percent,
        byte 10 = DPI stage count, then six u16 stages at 12.  A silent
        (asleep) mouse leaves the block empty, so an all-zero header is
        ignored rather than reported as 0 %.
        """
        if len(value) < INFO_PERCENT + 1 or value[1:3] == b"\x00\x00":
            return
        percent = value[INFO_PERCENT]
        if percent > 100:
            return
        rate = RATE_HZ.get(value[INFO_RATE]) if len(value) > INFO_RATE else None
        changed = percent != self._reading.percent
        self._set(
            percent=percent,
            rate_hz=rate,
            ok=True,
            detail="battery read from the mouse",
            updated_at=time.time(),
            raw=value.hex(" "),
        )
        if changed:
            self._set(since=time.time())
        elif not self._reading.since:
            self._set(since=self._reading.updated_at or time.time())
        self._log_reading(percent)
        self._save_state()

    def _run(self) -> None:
        while not self._stop.is_set():
            nodes = find_vendor_nodes(self.vid)
            if not nodes:
                self._set(
                    ok=False,
                    detail="no AJAZZ mouse or receiver found",
                    percent=None,
                    node="",
                    source="",
                )
                self._stop.wait(2.0)
                continue
            node = nodes[0]
            if node["path"] != self._node:
                self._node = node["path"]
                self._set(
                    node=node["path"],
                    source=node["name"],
                    device=f"{self.vid:04x}:{node['pid']:04x}",
                )
            try:
                self._listen(node)
            except OSError as exc:
                self._set(ok=False, detail=f"HID read error: {exc}")
            self._stop.wait(1.0)

    def _listen(self, node: Dict) -> None:
        fd = os.open(node["path"], os.O_RDWR | os.O_NONBLOCK)
        try:
            _claim_device(fd, node["path"])
        except OSError as exc:
            os.close(fd)
            self._set(ok=False, detail=f"HID read error: {exc}")
            return
        pending: Optional[Dict] = None
        try:
            while not self._stop.is_set():
                # Follow the better node: when the mouse is plugged in, its own
                # interface ranks above the receiver's relay, so drop the
                # receiver and let _run() pick the mouse up.
                if pending is None and time.time() >= self._rescan_at:
                    self._rescan_at = time.time() + 5.0
                    if node.get("rank", 0) > 0:
                        best = find_vendor_nodes(self.vid)
                        if best and best[0]["path"] != node["path"]:
                            return
                if pending is None and time.time() >= self._next_poll:
                    self._next_poll = time.time() + INFO_POLL_SECONDS
                    try:
                        _write_frame(fd, INFO_CLASS, 0x00, b"")
                    except OSError:
                        pass
                    else:
                        pending = {
                            "cls": INFO_CLASS, "internal": True,
                            "deadline": time.time() + 1.0,
                            "event": threading.Event(), "reply": None, "error": None,
                        }
                    continue
                if pending is None:
                    try:
                        req = self._queue.get_nowait()
                    except Empty:
                        req = None
                    if req is not None:
                        # Replies are not tagged, so anything still queued in
                        # the hidraw buffer is stale (the device replies to
                        # every write, and the UI polls).  Flush it before
                        # sending, otherwise the read-back returns an older
                        # answer and a correct write looks rejected.
                        while True:
                            try:
                                os.read(fd, 64)
                            except BlockingIOError:
                                break
                            except OSError:
                                return
                        try:
                            _write_frame(fd, req["cls"], req["type"], req["value"])
                        except OSError as exc:
                            req["error"] = str(exc)
                            req["event"].set()
                        else:
                            if req.get("want_reply", True):
                                req["deadline"] = time.time() + req["timeout"]
                                pending = req
                            else:
                                req["event"].set()
                        continue
                ready, _, _ = select.select([fd], [], [], 0.2)
                if not ready:
                    if pending is not None and time.time() > pending["deadline"]:
                        if pending.get("internal"):
                            self._next_poll = time.time() + INFO_RETRY_SECONDS
                        pending["error"] = f"no reply to class 0x{pending['cls']:02x}"
                        pending["event"].set()
                        pending = None
                    continue
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    continue
                except OSError:
                    return
                if not data:
                    continue
                if data[0] == VENDOR_REPORT_ID:
                    frame = _decode_reply(data)
                    if (pending is not None and frame is not None
                            and frame["class"] == pending["cls"]):
                        if pending.get("internal"):
                            self._apply_info(frame["value"])
                        else:
                            pending["reply"] = frame
                        pending["event"].set()
                        pending = None
                        continue
                entry = parse_status_packet(data)
                if not entry:
                    continue
                self._set(
                    raw=data[:12].hex(" "),
                    updated_at=time.time(),
                )
                if "percent" in entry:
                    changed = entry["percent"] != self._reading.percent
                    self._set(
                        percent=entry["percent"],
                        ok=True,
                        detail="battery reported",
                        charge_state=entry.get("chargeState"),
                    )
                    if changed:
                        self._set(since=time.time())
                    elif not self._reading.since:
                        self._set(since=self._reading.updated_at or time.time())
                    self._log_reading(entry["percent"])
                    self._save_state()
                elif "dpi" in entry:
                    self._set(dpi=entry["dpi"], dpi_stage=entry["dpiStage"])
                elif "link" in entry:
                    # 0 = the mouse is asleep/out of range, so a class-0x05
                    # read gets no answer.  Keep the last real value and say
                    # what it is instead of dropping to "--".
                    if entry["link"]:
                        self._set(link=1, detail="battery read from the mouse")
                    else:
                        self._set(link=0, ok=False,
                                  detail="mouse not linked - last reading kept")
                elif "mode" in entry:
                    self._set(mode=entry["mode"])
        finally:
            os.close(fd)
