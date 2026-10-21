#!/usr/bin/env python3
"""Extract the AJAZZ NL host->mouse frames from a USB capture.

This is the "load-bearing artifact" the upstream project asks for: a capture
of the vendor driver while the user changes DPI / report rate.  With a capture
in hand the exact command bytes fall out of the file, so this parser prints
every SET_REPORT the host sends to the mouse (VID 0x7768) and every
notification the device sends back, grouped and diffed against a baseline.

It reads either
  * a USBPcap / Windows pcapng  (linktype USBPcap 220, or DLT_USBPCAP)
  * a Linux usbmon text capture   (`cat /sys/kernel/debug/usb/devices > dump`)

Usage:
  python3 tools/parse_capture.py capture.pcapng
  python3 tools/parse_capture.py usbmon.txt
"""
import re
import struct
import sys

# USBPcap pseudo-header
USBPcap_ID = struct.Struct("<BBHBBBBBBH")
DLT_USBPCAP = 220
DLT_USBPCAP_WIN = 249


def pcap_records(data):
    """Yield (linktype, ts, payload) from a pcap or pcapng file."""
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
        endian = "<" if magic == b"\xd4\xc3\xb2\xa1" else ">"
        linktype = struct.unpack_from(endian + "I", data, 20)[0]
        off = 24
        while off + 16 <= len(data):
            ts, us, cap, orig = struct.unpack_from(endian + "IIII", data, off)
            off += 16
            yield linktype, ts + us / 1e6, data[off:off + cap]
            off += cap
    elif magic == b"\x0a\x0d\x0d\x0a":
        # pcapng
        off = 0
        linktype = None
        endian = "<"
        while off + 8 <= len(data):
            btype, blen = struct.unpack_from(endian + "II", data, off)
            if btype == 0x0A0D0D0A:
                bom = struct.unpack_from(endian + "I", data, off + 8)[0]
                endian = "<" if bom == 0x1A2B3C4D else ">"
                btype, blen = struct.unpack_from(endian + "II", data, off)
            if btype == 1:  # IDB
                linktype = struct.unpack_from(endian + "H", data, off + 8)[0]
            if btype == 6:  # EPB
                ts_hi, ts_lo, cap, orig = struct.unpack_from(endian + "IIII", data, off + 8)
                yield linktype, ts_hi + ts_lo / 1e6, data[off + 28:off + 28 + cap]
            off += blen
    else:
        raise SystemExit("not a pcap/pcapng file")


def usbpcap_packets(payload):
    """Yield (urb_type, transfer_type, endpoint, data) from USBPcap records."""
    if len(payload) < USBPcap_ID.size:
        return
    (hdrlen, _) = USBPcap_ID.unpack_from(payload)[:2]
    off = 0
    while off + USBPcap_ID.size <= len(payload):
        h = USBPcap_ID.unpack_from(payload, off)
        hdrlen, irpstatus, function, transfer, endpoint, maxlen, interval, start, xferflags, ndesc = h
        body = payload[off + hdrlen: off + hdrlen + maxlen]
        yield function, transfer, endpoint, body
        off += hdrlen + maxlen


def usbmon_lines(text):
    """Parse Linux usbmon text dumps into (direction, type, endpoint, data)."""
    for line in text.splitlines():
        if not line or line[0] in "S=":
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        # S: bus:dev:port S: timestamp type:count:status ... len:data
        try:
            kind = parts[2][0]
            if kind not in ("S", "C"):
                continue
            direction = "out" if kind == "S" else "in"
            # find the "len:" and "data:" fields
            m = re.search(r"len:\s*(\d+)", line)
            if not m:
                continue
            length = int(m.group(1))
            d = re.search(r"data:\s*([0-9a-f ]+)", line)
            if not d or length == 0:
                continue
            hexs = d.group(1).replace(" ", "")
            data = bytes.fromhex(hexs[:length * 2])
            yield direction, data
        except ValueError:
            continue


def usbmon_mmap_header(rec):
    """Decode a DLT_USB_LINUX_MMAPPED (220) record header.

    Layout (empirically verified against a live capture on this machine):
        0   u32  id
        4   u32  (kernel-internal)
        8   u8   type          'S' submit / 'C' complete
        9   u8   transfer type 0 iso, 1 interrupt, 2 control, 3 bulk
        10  u8   endpoint
        11  u8   device address
        12  u16  bus id
        14  u8   flag_setup
        15  u8   flag_data
        16  s64  ts_sec
        24  s32  ts_usec
        28  s32  status
        32  u32  urb_len
        36  u32  data_len
        40  8    setup packet (control transfers)
        64  ...  payload
    """
    if len(rec) < 64:
        return None
    kind = chr(rec[8])
    xfer = rec[9]
    ep = rec[10]
    dev = rec[11]
    bus = struct.unpack_from("<H", rec, 12)[0]
    ts = struct.unpack_from("<q", rec, 16)[0] + struct.unpack_from("<i", rec, 24)[0] / 1e6
    urb_len, data_len = struct.unpack_from("<II", rec, 32)
    setup = rec[40:48] if xfer == 2 else b""
    return {
        "kind": kind, "xfer": xfer, "ep": ep, "dev": dev, "bus": bus,
        "ts": ts, "urb_len": urb_len, "data_len": data_len, "setup": setup,
        "data": rec[64:64 + data_len],
    }


def main():
    path = sys.argv[1]
    raw = open(path, "rb").read()

    if raw[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x0a\x0d\x0d\x0a"):
        out_frames = []
        in_frames = []
        for linktype, ts, payload in pcap_records(raw):
            if linktype in (220, 189):        # linux usbmon
                h = usbmon_mmap_header(payload)
                if not h or h["xfer"] != 2 or not h["setup"]:
                    continue
                bm_request_type = h["setup"][0]
                b_request = h["setup"][1]
                w_value = struct.unpack_from("<H", h["setup"], 2)[0]
                w_length = struct.unpack_from("<H", h["setup"], 6)[0]
                rtype = (w_value >> 8) & 0xFF
                rid = w_value & 0xFF
                if bm_request_type == 0x21 and b_request == 0x09:   # SET_REPORT
                    out_frames.append((h["ts"], rid, rtype, h["data"].hex(" ")))
                elif bm_request_type == 0xA1 and b_request == 0x01:  # GET_REPORT
                    in_frames.append((h["ts"], rid, rtype, "<GET>"))
                continue
            for function, transfer, endpoint, body in usbpcap_packets(payload):
                if not body:
                    continue
                if len(body) >= 3 and body[0] == 0x21:
                    bmRequest = body[1]
                    wValue = struct.unpack_from("<H", body, 2)[0]
                    rtype = (wValue >> 8) & 0xFF
                    rid = wValue & 0xFF
                    if bmRequest == 0x09:      # SET_REPORT
                        out_frames.append((ts, rid, rtype, body[8:].hex(" ")))
                    elif bmRequest == 0x01:    # GET_REPORT
                        in_frames.append((ts, rid, rtype, "<GET>"))
        print(f"host -> device SET_REPORT frames: {len(out_frames)}")
        for ts, rid, rtype, data in out_frames:
            print(f"  {ts:12.6f}  report {rid} type {rtype}  {data}")
        print(f"\ndevice -> host GET_REPORT frames: {len(in_frames)}")
    else:
        text = raw.decode("utf-8", "replace")
        outs, ins = [], []
        for direction, data in usbmon_lines(text):
            (outs if direction == "out" else ins).append(data)
        print(f"out frames: {len(outs)}   in frames: {len(ins)}")
        print("\n-- host -> device (first 60) --")
        for d in outs[:60]:
            print("   ", d.hex(" "))
        print("\n-- device -> host (first 40) --")
        for d in ins[:40]:
            print("   ", d.hex(" "))


if __name__ == "__main__":
    main()
