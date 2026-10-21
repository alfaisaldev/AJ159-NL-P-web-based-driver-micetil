#!/usr/bin/env python3
"""Fast USBPcap/pcapng extractor for the AJAZZ vendor frames.

Prints every HID class control transfer (SET_REPORT / GET_REPORT) in
chronological order, one line each, so a capture of the vendor app can be
read off directly.

    python3 tools/usbpcap_extract.py capture.pcapng [--all]

--all also lists standard-descriptor traffic (used to find the device's
VID/PID and bus/device address).
"""
import struct
import sys

USBPcap1 = struct.Struct("<HQIIBHHBBI")   # 27 bytes
USBPcap2 = struct.Struct("<HQIIBHHBBII")  # 35 bytes


def blocks(data):
    off = 0
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if blen < 12 or off + blen > len(data):
            return
        yield btype, data[off + 8:off + blen - 4]
        off += blen


def interfaces(data):
    """interface id -> linktype"""
    out = {}
    for btype, body in blocks(data):
        if btype == 1:                                   # IDB
            linktype = struct.unpack_from("<H", body, 0)[0]
            out[len(out)] = linktype
    return out


def packets(data):
    iface = interfaces(data)
    for btype, body in blocks(data):
        if btype != 6:                                   # EPB
            continue
        iid, ts_hi, ts_lo, caplen, _ = struct.unpack_from("<IIIII", body, 0)
        yield iface.get(iid, 0), (ts_hi << 32 | ts_lo) / 1e6, body[20:20 + caplen]


def usbpcap(pkt):
    """Return (header dict, payload) for one USBPcap packet."""
    if len(pkt) < 27:
        return None, b""
    hlen = struct.unpack_from("<H", pkt, 0)[0]
    if hlen == 27:
        _, irp, status, func, info, bus, dev, ep, xfer, dlen = USBPcap1.unpack_from(pkt, 0)
    elif hlen == 35:
        _, irp, status, func, info, bus, dev, ep, xfer, dlen, _ = USBPcap2.unpack_from(pkt, 0)
    else:
        return None, b""
    return ({"bus": bus, "dev": dev, "ep": ep, "xfer": xfer,
             "len": dlen, "status": status}, pkt[hlen:hlen + dlen])


def main():
    path = sys.argv[1]
    show_all = "--all" in sys.argv
    data = open(path, "rb").read()
    n = 0
    for linktype, ts, pkt in packets(data):
        if linktype not in (249, 220):
            continue
        h, payload = usbpcap(pkt)
        if not h or h["xfer"] != 2 or len(payload) < 8:
            continue
        bm, req = payload[0], payload[1]
        wval, widx, wlen = struct.unpack_from("<HHH", payload, 2)
        rtype, rid = (wval >> 8) & 0xFF, wval & 0xFF
        body = payload[8:]
        n += 1
        if not show_all:
            if not (bm == 0x21 and req == 0x09) and not (bm == 0xA1 and req == 0x01):
                continue
        tag = {0x21: "SET", 0xA1: "GET"}.get(bm, f"ctrl{bm:02x}")
        print(f"{ts:11.6f} {tag} bRequest={req:02x} rid={rid} type={rtype:02x} "
              f"idx={widx} len={wlen}  {body[:48].hex(' ')}")
    print(f"\ncontrol transfers: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
