# AJ159 NL P — customizability, protocol status, and the firmware pull

Research notes, 2026-10-21. Marked **verified** = observed on the live device.
**Driver** = read out of the vendor's own Windows package (AJAZZ Driver (W1)
1.0.7.6) that the user supplied.

## 1. Identity (from the driver's own `config.xml`)

```xml
<mouse name="AJ159 NL P" device_type="101" device_attr="mouse">
    <mode value="0" desc="USB"  vid="7768" pid="6d25" hid_interface="VID_7768&PID_6D25&MI_01"/>
    <mode value="1" desc="2.4G" vid="7768" pid="6425" hid_interface="VID_7768&PID_6425&MI_01"/>
</mouse>
```

`MI_01` = interface 1 = the vendor HID collection = our `hidraw5`. The whole
NearLink family is on VID `0x7768`:

| model | USB (wired) | receiver | device_type |
|---|---|---|---|
| AJ159 NL P | `6d25` | `6425` | 101 |
| AJ159 NL | `6d26` | `6426` | 102 |
| AJ179 NL P | `6d2E` | `642E` | 103 |
| AJ179 NL | `6d2D` | `642D` | 104 |
| AJ179 V2 NL P | `6d32` | `6432` | 105 |
| AJ139 V2 NL P | `6d30` | `6430` | 107 |

## 2. What can be customized (the driver's feature list)

Tabs: **Home · Mouse · DPI · Macro · Lighting · Settings**.

| # | Feature | Detail | Available on this model |
|---|---|---|---|
| 1 | **DPI** | 6 stages, factory 400 / 800 (green) / 1200 (red) / 1600 (blue) / 2400 (yellow) / 3200 (pink); driver range 50–12000 DPI in 50 steps (P: up to 26000); configurable **DPI count**; per-stage indicator colour | ✅ |
| 2 | **Report rate** | 125 / 250 / 500 / 1000 Hz (wired and NearLink); Bluetooth fixed 125 Hz; "High-Speed Mode" note mentions 2K+ | ✅ |
| 3 | **Button assignment** | 5 buttons + DPI key → mouse features, multimedia, system shortcuts, macros, sniper key, disable, launch program, open URL, send text; per-button and global reset | ✅ |
| 4 | **Macros** | editor, up to 200 events, delay modes (none / record / uniform), loop modes (until release / until press again / N times), mouse + keyboard events | ✅ |
| 5 | **Lighting** | effects Off / Solid / Breathing / Spectrum Cycle / Flowing / Solid Marquee / Neon + brightness / speed / saturation / custom colour | ❌ **disabled** — `device/mouse.xml` has `<menu light="0"/>` |
| 6 | **Sensor** | LOD 1–2 mm, Ripple Control, Linear Correction (angle snap), Motion Sync, scroll direction, key response delay (debounce), high-speed mode | ✅ |
| 7 | **Sleep** | auto-sleep timer (sec/min/hours) | ✅ |
| 8 | **Profiles** | profile selector (Standard / Profile) in the driver | ⚠️ number of onboard layers unverified for the NL family |
| 9 | **Maintenance** | mouse / receiver / driver version, Restore Factory Settings, firmware upgrade (OTA) for mouse and receiver, NearLink pairing (hold L+M+R 5 s) | ✅ |

The only thing this mouse **does not** expose is RGB lighting control.

## 3. The HID surface (verified on hardware)

Interface 0 (`hidraw4`) — the mouse:

| id | dir | len | contents |
|---|---|---|---|
| 1 | Input | 7 | 5 buttons + X + Y + wheel |
| 2 | Input | 8 | consumer-page keys |
| 3 | Input | 2 | vendor page `0xFF0C` (rarely sent) |
| 4 | Input | 1 | vendor page `0xFF00` (rarely sent) |

No outputs → nothing here is configurable.

Interface 1 (`hidraw5`) — the vendor collection:

| id | dir | len | usage page | role |
|---|---|---|---|---|
| 6 | Input | 63 | `0xFFB2` | **telemetry** |
| 6 | Output | 63 | `0xFFB2` | config channel |
| 7 | Input / Output | 9 | `0xFFB3` | state / config |
| 8 | Output | 12 | `0xFFB1` | config channel |

There are **no feature reports**; every control path is an output report. (The
Windows driver uses `HidD_SetFeature`/`HidD_GetFeature`; on Linux the
equivalent is `HIDIOCSOUTPUT`/`HIDIOCGFEATURE`, and the device accepts
either — the report id is stripped by the kernel, so the device's body starts
at our byte 1.)

### Telemetry frame (verified)

```
body:  [0] 0xfa  [1] len  [2] 0x00  [3] 0x00  [4] tag  [5..] value
```

| tag | meaning | value |
|---|---|---|
| `0x01` | link state | 1 byte (0/1) — flips on NearLink↔Bluetooth |
| `0x02` | DPI | stage index + u16 LE DPI (verified against the 6 factory stages) |
| `0x03` | battery | percent + state byte (1 = charging, 2 = on battery) |
| `0x06` | mode | 1 byte |

Push cadence: every 10 s over USB, every 30 s through the receiver.

## 3b. The HID surface, decoded exactly

`tools/hid_reports.py` walks the raw descriptor (from
`/sys/class/hidraw/hidrawN/device/report_descriptor`):

```
Collection (Application)  usage page 0xFFB1      ; "page 1"
  Report ID 8  ->  Output  2 bytes
Collection (Application)  usage page 0xFFB2      ; "page 2"
  Report ID 6  ->  Output 63 bytes, Input 63 bytes
Collection (Application)  usage page 0xFFB3      ; "page 3"
  Report ID 7  ->  Output  9 bytes, Input  9 bytes
```

**There are no feature reports.** That matters: the vendor's Windows driver
uses `HidD_GetFeature` / `HidD_SetFeature` only (no `HidD_SetOutputReport`),
and Linux's hidraw refuses `HIDIOCSFEATURE` for a device with no feature
report (`EINVAL`). So the command channel may well be a *feature* report that
only raw USB can reach.

## 3c. Raw USB: what the device actually accepts

`tools/usb_feature_test.py` (root) unbinds `usbhid` from the vendor
interface via sysfs, claims it with `USBDEVFS_CLAIMINTERFACE`, and talks to
the device directly:

| request | result |
|---|---|
| `GET_REPORT` Feature/Output/Input, ids 6/7/8 | accepted, **returns zeros** |
| `SET_REPORT` Feature/Output, ids 6/7 | **accepted (no error)** |

So the device tolerates every report type, but only *input* reports carry
data - the telemetry only ever arrives on the interrupt endpoint, and
`GET_REPORT` is a dead end (no read-back channel).

**Taking the interface away from the kernel** (needed for any raw-USB work):

```bash
# as root
echo "1-14.1:1.1" > /sys/bus/usb/drivers/usbhid/unbind      # vendor interface
#   ... talk to /dev/bus/usb/001/0NN with USBDEVFS_CONTROL ...
echo "1-14.1:1.1" > /sys/bus/usb/drivers/usbhid/bind        # give it back
```

`USBDEVFS_DISCONNECT` / `USBDEVFS_DISCONNECT_CLAIM` return `ENOTTY` on this
kernel; the sysfs `unbind`/`bind` path is what works. While `usbhid` is
unbound, `hidraw5` disappears - the panel shows stale data until it is
re-bound (or the mouse is replugged).

The `usbhid` binding is also why the earlier sweeps failed with
`EBUSY`: the kernel driver owned the interface, so every control transfer was
rejected before it reached the device.

## 3d. Reference protocols (for comparison)

No protocol has ever been published for VID `0x7768`. The closest
documented relatives in the same vendor family:

| family | frame | commands |
|---|---|---|
| AJ-series (VID 0x3151) | 64-byte, report id 5, `cmd` in byte 1, checksum `sum(body[1..63]) & 0x7f` in byte 64 | rate `0x04` (code 8/4/2/1 = 125/250/500/1000 Hz), DPI table `0x54` (u16-LE values at bytes 8..23), RGB `0x07`, reset `0x02`, battery `0xF7` + `GET_FEATURE 0x05` |
| AJ159/AJ179 (VID 0x248a/0x249a) | 32-byte, `family, 0, mode, opcode, payload[27], checksum` | rate family `0x02`/op `0x01` (interval ms 8/4/2/1), DPI family `0x03`/op `0x25` (6 x 4 bytes) |
| IRIS v2 NearLink (VID 0x363C) | 64-byte, report id 0x0B, write `[cmd][payload]`, read `[cmd][status][data]` | `0x13` info, `0x17` get config, `0x18` set config, `0x19`/`0x1A` DPI config, rate `1/2/4/8` = 1000/500/250/125 Hz |

Our device's own firmware says the same thing: the reply builder ORs `0x80`
into the header (`lui`/`ori` at `0x90124994`), i.e. **bit 7 marks the
device -> host direction**, and the host command ids that the app answers
are the same values with bit 7 clear (`0x02, 0x10, 0x15, 0x36, 0x6c, 0x56,
0x76, 0x00, 0x0b, 0x0f`).


The device **echoes the first body byte** in its reply frame and answers
malformed frames with an error frame (`msg=echo, len=01, tag=01/02`).
Well-formed frames are accepted **silently** — no reply at all. The old
AJ-series opcode table (0x21 DPI, 0x22 poll rate, 0x30 RGB, 0x40 battery,
0x50 commit, 0x83 get battery, 0xF7 status poll…) does **not** answer on this
firmware.

> ⚠️ **Measurement pitfall that invalidated earlier sweeps:** the panel
> daemon (`battery.py`) opens *every* AJAZZ vendor hidraw node (mouse **and**
> receiver) and holds them open. `hidraw` is not multicast — two readers split
> the frame stream, so the daemon silently swallows the mouse's replies and
> telemetry. Every "the mouse does not answer" result obtained while the
> service was running is a **false negative**. Stop the service
> (`systemctl --user stop ajazz-panel`) before probing, and make sure only one
> process reads the node.

The command encoding is recovered from the firmware itself (below) — no
emulator needed.

## 3f. ⭐ The command channel is report id 0 (the hidden feature report)

The device's descriptor advertises only report ids 6 (63 B, in+out), 7 (9 B)
and 8 (12 B, out) — and **nothing answers on them**.  But sending on
**report id 0 or 1** (the old AJ-family *feature report 0* convention, which
this device does *not* declare) makes the device reply:

```
host -> device   report 0, class 0x06            (SET_REPORT, Output)
device -> host   06 04 01 00 00 02 00 …          (class 0x04, len 1, type 0x02)
device -> host   06 02 01 00 00 02 00 …          (class 0x02, len 1, type 0x02)
```

This is why nothing worked before:

* the Windows driver uses `HidD_Get/SetFeature` — i.e. **feature** reports,
  and the older AJ-family puts its commands in **feature report 0**;
* Linux's `hidraw` refuses `HIDIOCSFEATURE` for a device whose descriptor
  declares no feature report (`EINVAL`), so this channel is unreachable
  from hidraw — but it is trivially reachable over raw USB
  (`SET_REPORT`, `wValue = (type<<8) | id`).

So the command channel is the *hidden* feature report 0, and the frame
layout is the same TLV as the telemetry:

```
[0] class      [1] len      [2] 0x00     [3] 0x00     [4] type     [5..] value
```

(the report id lives in the USB `wValue`, not in the payload).


The application image is a linked RISC-V (RV32 + RVC compressed) binary, base
`0x90115000`, ~216k instructions, ~2k functions. (An earlier note in this
document guessed "Thumb ARM" — that was wrong; the 2-byte-stride tables and
the 1991 `c.jr ra` returns give it away.)

Layout of `application_sign.bin`:

| file range | content |
|---|---|
| `0x0000-0x1800` | image header / vector area |
| `0x1800-0x76000` | code (RISC-V + RVC) |
| `0x76000-0x7a600` | `.rodata` — log strings **and** the settings tables |
| `0x7a800+` | data tables: handler tables, jump tables, log-string table |

### The wire format, read out of the firmware

The firmware's own log line documents the message layout:

```
"%s() msg_len:%d, header:0x%02X, type:0x%02X, val_len:%d"
```

and the frame builder (`0x90127862`, called with `a0`=report id, `a1`=header,
`a2`=payload) assembles the report as:

```
report id 6 :  [6] [header] [len] [payload…]
body the device sees:  [0] header  [1] len  [2] 0x00  [3] 0x00  [4] type  [5..] value
```

which matches the telemetry exactly: `06 fa 03 00 00 03 64 02` =
id 6, header `0xfa`, len 3 (1 type + 2 value bytes), type `0x03` (battery),
value 100 / state 2.

### Direction bit

The reply builder ORs `0x80` into the header
(`lbu a1,0x11(sp); ori a1,a1,0x80`), i.e. **bit 7 = "device → host"**.
The device's own message headers found in the app module are therefore
`0x82, 0x90, 0x95, 0xb6, 0xfa, 0xec, 0xd6, 0xf6, 0x80, 0x8b, 0x8f`; the
matching **host command ids** are the same values with bit 7 clear:
`0x02, 0x10, 0x15, 0x36, 0x7a, 0x6c, 0x56, 0x76, 0x00, 0x0b, 0x0f`.

### The settings tables (found in `.rodata`)

| file offset | contents |
|---|---|
| `0x75c98` | polling rates **250, 500, 1000, 2000** |
| `0x75ca4` | polling rates **8000, 125, 250, 500, 1000, 2000, 4000, 8000, 8000, 4000, −1** (terminator) |
| `0x75c18` | sensitivity steps **500, 250, 150, 100, 75, 50, 30, 20** |

So the firmware drives the report rate from a table of 125/250/500/1000/2000/
4000/8000 Hz — the driver's UI offers 125/250/500/1000.

### Tools for this firmware

`tools/rv_*.py` (need the capstone venv: `python3 -m venv /tmp/opencode/venv
&& /tmp/opencode/venv/bin/pip install capstone`):

| tool | purpose |
|---|---|
| `rv_find.py` | rebuild `lui`/`auipc` + `addi` address pairs, list referenced strings |
| `rv_use.py` | find the code that uses a given string (absolute or PC-relative) |
| `rv_addr.py` | find code that touches a given data table / address |
| `rv_map.py` | map code addresses → string literals |

Strings are *not* referenced by a plain pointer table: the app indexes a
log-string table (`0x7d000-0x7f000`) with 16-bit offsets, so the string → code
mapping has to be done through those tables.


## 3g. ⭐ Verified transport: report id **6** over hidraw (no root, no usbfs)

Correction to §3f: the command channel *is* reachable unprivileged through
hidraw, and the report id to use is **6** — the id the vendor collection
actually declares.  Report id 0 only appeared to work because the raw-USB
tests also carried `0x06` in the payload.

```
fd  = open(vendor hidraw node)                 # e.g. /dev/hidraw3
buf = [0x06] + [class, len, 0x00, 0x00, type] + value
ioctl(fd, HIDIOCSOUTPUT, buf)                  # 64-byte buffer
reply = read(fd)                               # [6][class][len][0][0][type][value…]
```

Measured on the receiver (7768:6425), class-0x05 read:

```
send: 06 05 01 00 00 00
recv: 06 05 24 00 00 01 00 25 6d 12 10 01 01 64 …
```

usbfs is *not* usable while usbhid owns the interface: `GET_DESCRIPTOR`
works, every `GET_REPORT`/`SET_REPORT` returns **EBUSY (16)** (measured),
and unbinding usbhid would delete the telemetry hidraw node.  hidraw is both
simpler and safe — it leaves the mouse's normal HID operation untouched.

### Class map (measured)

| class | reply type | len | meaning |
|---|---|---|---|
| `0x05` | `0x01` | 36 | mouse descriptor: PID u16 @1, battery % @7, six u16 DPI stages @12 = `dpi/50 − 1` |
| `0x07` | `0x01` | 6 | receiver descriptor: PID u16 @1 |
| `0x0f` | `0xff` | 2 | status (`02`) |
| `0x10` | `0x10` | 36 | config block: 9 × 4 B (`1,2,4,16,8,32,64` @ `0x1000`, then 287, 31) |
| `0x11` | `0x0f` | 36 | **write staging buffer — DANGER, see below** |
| other | `0x02` | 1 | not supported |

Reads ignore the type byte: every type `0x00–0x0f` returns the same block.

### ⛔ DANGER: short writes to the record/profile classes

*(Superseded in part by §3h: the capture shows the vendor app itself sends
`06 11` on every start, so that frame is a read.  The attribution below was
wrong; what still holds is that a short write clears state, and that the
classes taking bulk payloads are 0x12 and 0x31.)*

`06 11 01 00 00 00` (class `0x11`, **no payload**) commits the staging
buffer.  With an empty buffer (36 zero bytes) that commit clears the mouse's
**button map in NV**: the device still moves, but HID report 1 never sets a
button bit again, and it survives a power cycle.

Measured twice, both times right after a sweep that included that frame;
`0x05`, `0x07` and `0x10` read back byte-identical before and after, so
nothing else changed.  Only the vendor's **Restore Factory Settings**
rewrote it.

Enforced in code:

* `ajazz_protocol.QUARANTINED` refuses class `0x11` outright;
* `READ_ONLY` allows exactly `0x05/0x07/0x0f/0x10`, type `0x00`, no value;
* every blind-sweep tool was moved to `tools/quarantine/`.

### What is still missing, and how to get it with evidence

The **store** commands for DPI and report rate.  The vendor app is the only
remaining source: capture it on Windows with USBPcap + Wireshark while it
(1) changes one DPI stage, (2) changes the report rate, (3) runs *Restore
Factory Settings* — that last one also yields the correct 36-byte button
map, so the buttons become repairable from Linux.

```
python3 tools/parse_capture.py capture.pcapng
```

## 3h. The Windows capture, decoded (ajaaz.pcapng)

USBPcap + Wireshark on Windows 11, 179 s, 71 k packets, receiver 7768:6425.
Every host -> device frame is a **class control transfer**, `SET_REPORT` with
`wValue=0x0206` (output report id **6**), `wIndex=1`, `wLength=64` — the same
transport this project uses.

```
06 | class | len | 00 00 | type | data[len]        len = length of data
```

Reads are sent as `06 <class>` and nothing else.

| what | frame | note |
|---|---|---|
| read record | `06 05` `06 07` `06 10` `06 11` | the app's startup probe (`06 05` 5x on connect) |
| write config record | `06 12 20 00 00 10` + 32 B | payload = the class-0x10 block, byte for byte |
| **set one DPI stage** | `06 13 05 00 00 01` + `06 <stage> <lo> <hi> 00` | sent once per stage, 0..5 |
| setting write | `06 13 02 00 00 <id> <value> 00` | ids seen: 0x02 (values 0..3), 0x05 (u32), 0x06, 0x07, 0x08, 0x0a |
| LED / profile | `06 31 <chunk> <total> 00 00 …` | multi-chunk, `83 01` terminator |

The six DPI writes in the capture, verbatim:

```
06 13 05 00 00 01 06 00 90 01 00    stage 0 = 0x0190 =  400 dpi
06 13 05 00 00 01 06 01 20 03 00    stage 1 = 0x0320 =  800 dpi
06 13 05 00 00 01 06 02 b0 04 00    stage 2 = 0x04b0 = 1200 dpi
06 13 05 00 00 01 06 03 40 06 00    stage 3 = 0x0640 = 1600 dpi
06 13 05 00 00 01 06 04 60 09 00    stage 4 = 0x0960 = 2400 dpi
06 13 05 00 00 01 06 05 80 0c 00    stage 5 = 0x0c80 = 3200 dpi
```

Verified on hardware (round trip, 2026-10-21):

```
write 400/800/1200/1600/2400/3200 -> read 07 00 0f 00 17 00 1f 00 2f 00 3f 00
write 400/1600/1200/1600/2400/3200 -> read [400, 1600, 1200, 1600, 2400, 3200]
```

### ⚠ the two encodings are different

```
read block  (class 0x05, offset 12)   dpi/50 - 1     400 -> 7
write frame (class 0x13, type 0x01)   raw dpi        400 -> 90 01
```

Mixing them up was measured: it wrote 7..63 dpi, which the device clamps to
its minimum, so all six stages read back as 0 (= 50 dpi).

### Correction to §3g

`06 11` is a **read** — the official app sends it on every start.  The
earlier claim that it commits an empty staging buffer was wrong.  What is
still true: short writes to the bulk classes clear state, and 0x12 (records,
`type` = record id) plus 0x31 (profile, multi-chunk) are the only classes
that take large payloads in the capture.  This project never sends either.

### Report rate — solved and measured

```
host -> device   06 13 02 00 00 02 | <value> 00
```

The mouse's own input stream (endpoint 0x81) says what each value does,
measured over the exact spans between the app's four writes at 125.07,
125.56, 126.12 and 126.78 s:

| value | median gap between reports | rate |
|---|---|---|
| 0 | 8.00 ms | 125 Hz |
| 1 | 4.00 ms | 250 Hz |
| 2 | 2.00 ms | 500 Hz |
| 3 | 1.00 ms | 1000 Hz |

The windows before (1.50 s) and after (2.00 s) both sit at 1.00 ms, so the
change is the setting and not load.  Verified on hardware through the
panel's selector.

Reading the setting back: `06 13 01 00 00 <id>` is only answered for
`id = 0x09` (reply 2 bytes); 0x02..0x08 answer with an empty ACK.  The value
is in the **info block instead — byte 24 is the rate index**, verified live
(write 2 → byte 24 = 2, write 0 → byte 24 = 0, read back through the
receiver).  `/api/rate` reads it from there and only falls back to the stored
value when the device does not answer.

### Active DPI stage — solved and measured

The mouse is on exactly one of the six stages; the vendor app never writes a
"select stage" command, because **the device activates whichever stage frame
it received last**.  The state is readable:

```
class 0x05 block, byte 11   zero-based index of the active stage
```

Measured on hardware, with the table values held constant so nothing else
could move:

| write order | byte 11 | table |
|---|---|---|
| before | 1 | 400 800 1200 1600 2400 3200 |
| all six, stage **3** last | **3** | unchanged |
| all six, stage **1** last | **1** | unchanged |

Nothing else in the block changed, and the change survives (polled for 12 s
without drifting).  The vendor capture agrees: its DPI session writes stages
0..5 and then repeats stage 1 four times, i.e. it ends on the stage it wants
active.

So "select stage N" is the ordinary verified DPI write with the chosen stage
moved to the end — no new command, no new risk:

```python
dpi_frames_for_stage(table, stage)   # five others, then `stage`
```

Two consequences:

* the panel's stage editor used to write 0..5 in order, so **every DPI edit
  silently moved the mouse to stage 6 (3200 DPI)**.  It now re-sends the
  current stage last, which keeps the mouse where it was;
* the receiver applies relayed writes with a delay, so the read-back has to
  be polled (~3 s) instead of sampled once — a single read right after the
  write can still return the previous block.

### Still unknown

* **button map** — no `06 12 … 11` write and no restore appear in the
  capture, so the correct 36-byte map is not in it.

Peripheral hint: the app also writes a 4-byte setting at `0x13/0x05` and
5-byte ones at `0x13/0x0b` (`… 0a 00 28 00 00` → 40, `… 0a 00 58 02 00` →
600); these were not identified either, but they are not needed for the DPI
stage (the last-frame rule above explains the app's behaviour).

## 4c. The vendor's own driver: the real frame classes ⭐

Disassembling the official driver (`AJAZZ Driver（W1）` 1.0.7.6, the exact
build for this mouse) gives the protocol shape the vendor itself uses.

**Outbound frame** (the driver builds a 64-byte buffer, `memset` to 0, then
stores the header, then `WriteFile` on the HID handle — Windows takes byte 0
as the report id):

```
[0] report id   (0x06)
[1] class       (0x05 probe, 0x07 query, 0x10 read config,
                  0x11 write config, 0x31, 0x06, ...)
[2] len
[3] 0x00
[4] 0x00
[5] type
[6..] data
```

— i.e. **exactly the same TLV shape as the inbound telemetry**; only the
class byte differs (the device pushes with class `0xFA`).

**Probe**: the driver sends `06 05 00 00 00 00 …` (63 bytes) **five times,
20 ms apart**, right after opening the device.

**Inbound**: `[0] report id, [1] class, [2] len, [3] 0, [4] 0, [5] type/status,
[6..] data`. The driver checks `buf[5] == 1` for the class-`0x07` reply and
logs the values at `buf[9]` and `buf[10]`. It also filters inbound classes
`0x05` and `0x13` (with sub `0x01`, type `0x09`).

**The device's settings schema** (the driver's config keys, in order):

```
report_rate   report_count   report_flag   sensor_flag
dpi_flag      dpi_index      dpi_count
dpi_group0_value .. dpi_group5_value      (6 DPI stages)
dpi_group0_rgb    .. dpi_group5_rgb
notify_dpi    notify_light   notify_devsleep   sleep_light
```

so the mouse stores 6 DPI stages plus a report rate, and the driver reads and
writes them through the class-`0x10` / `0x11` config frames.

**Where the rest of the protocol hides:** the W1 exe is a UI shell. Its
strings show it *downloads and runs* a per-device helper
(`mouse-setup-<key>.zip` → `mouse-setup-<key>.exe -autorun`) from
`https://mouse-upgrade-1331323773.cos.ap-guangzhou.myqcloud.com/software-upgrade/AJAZZ/release/`
and that helper is what owns the setters. The `<key>` could not be guessed
(≈150 candidates 404'd), so capturing the WinINet request on Windows is the
shortest route to it. A USB capture would reveal the same thing.

DFU/OTA uses HID usage page `0xFFB1` usage `0x01` via
`BurnTool.exe -dfu -vid:0x7768 -pid:0x6d25`.

## 5. Firmware — pulled ✅

The vendor installer ships the flash images for this exact chip (BS20 /
SparkLink) inside `app/BurnTool/firmware/`:

```
mouse/bs20_all.fwpkg      653,300 bytes
dongle/bs20_all.fwpkg     607,508 bytes
```

Container format (reverse engineered, `tools/extract_fwpkg.py`):

```
0x00  magic "dfadbeef"
0x04  u32 build field
0x08  u32 payload size
0x0c  table: 6 entries × 0x34 bytes
        +0x00 char[32] name
        +0x20 u32 size in flash   +0x24 u32 size in package
        +0x28 u32 load address    +0x2c u32 flags
0x144 data area, blobs back-to-back in table order
```

Extracted blobs (mouse):

| file | flash size | load address | what it is |
|---|---|---|---|
| `loaderboot_sign.bin` | 324 | – | loader/bootloader |
| `partition.bin` | 25,236 | `0x90100000` | flash partition table |
| `flashboot_sign_a.bin` | 26,276 | `0x90101000` | flash bootloader A |
| `flashboot_sign_b.bin` | 64,244 | `0x9010b000` | flash bootloader B |
| `application_sign.bin` | 102,212 | `0x90115000` | **the application firmware** |
| `bs20_all_nv.bin` | 649,188 | `0x901fe000` | NV / config area |

The application image identifies itself as **`bs20 1.0.13`** and contains the
NearLink (SLE) SDK strings — so the "AT command" layer in it (`+HELP:cmd
cnt:%d`, `SETSLEEP`, `SLEPAIR`, …) is the *radio* SDK's command set, not the
HID control set. The mouse's own handlers are visible as
`GUI set DPI error: max_step = %d`, `DPI reset default`,
`button_event_report_rate_set`, `pm_set_sleep_duration`, `charge_status : %d`,
`----------macro data---------------`, `mouse_macro_data_update in ======`.

**No bootloader mode exists on the wired path:** holding the DPI/Pair button
while replugging the cable just re-enumerates the mouse as the same
`7768:6d25` (verified — no new PID, no DFU interface). The `BurnTool`'s DFU
config is empty (`VID=`, `PID=`), so there is no known DFU PID to switch to.

## 6. Next steps

### 6.1 The one artifact that finishes this

Upstream agrees (Aiacos/ajazz-control-center issue #87): *"a USB capture is
the load-bearing artifact"* — for the NearLink transport nothing is public
and the vendor driver keeps the setters in a helper it downloads at runtime
(`mouse-setup-<key>.exe`, key not guessable, the COS bucket is not listable).

So: **capture the vendor driver talking to the mouse**, then

```bash
python3 tools/parse_capture.py capture.pcapng     # Windows USBPcap
python3 tools/parse_capture.py usb.pcap           # Linux usbmon (tcpdump)
python3 tools/parse_capture.py usbmon.txt         # Linux usbmon text dump
```

which prints every `SET_REPORT` the host sends (report id, class, type,
payload) and the device's replies.  From that, the DPI and report-rate
commands are read straight off the wire, registered in
`ajazz_protocol.COMMANDS`, and the panel controls go live.

**The Linux capture is already validated on this machine** (it extracted our
own probe frames byte-for-byte):

```bash
sudo modprobe usbmon
sudo tcpdump -i usbmon0 -s 0 -w /tmp/usb.pcap      # while the vendor app acts
python3 tools/parse_capture.py /tmp/usb.pcap
```

How to capture the vendor app:

* **Windows** (any machine with the vendor driver): USBPcap + Wireshark,
  filter on the `7768:6d25` device, then in the vendor app click through the
  DPI stages and the report-rate dropdown.  Export as `.pcapng`.
* **Linux**: same tcpdump line above, performed while the vendor app (or
  the vendor's web driver, if it ever supports this model) makes the change.
* The vendor's **web driver** (`ajazz.szslxd-tech.com`) would also do, but
  it only covers the older mouse family (no `7768` in its device list).


### 6.2 Everything else that is ready

* `ajazz_protocol.py` — the transport layer with the confirmed frame layout,
  the confirmed classes, the confirmed telemetry types and the device's
  settings schema.  `COMMANDS` is the single place to register the setter
  opcodes; the setters refuse to send anything until then, so no guess can
  ever reach the mouse.
* `battery.py` / `server.py` — the read-only panel (battery %, charge state,
  link, mode, DPI stage + value) with a macOS-style UI on `http://127.0.0.1:8778`.
* `tools/hid_reports.py` — exact HID descriptor decode.
* `tools/usb_*.py` — raw-USB tooling: interface takeover via sysfs
  unbind/bind, `GET/SET_REPORT` in every type, and the sweeps over classes,
  types and report ids.  Run with `sudo` (or `pkexec`).
* `tools/rv_*.py` — RISC-V firmware analysis (capstone venv required).
* `tools/parse_capture.py` — the capture reader.
* `battery.claim_device()` — an advisory lock so the panel and a probe
  cannot silently split the HID frame stream (that bug invalidated an early
  round of experiments).

### 6.3 Still open

* The exact class/type pair for *set DPI* and *set report rate*.
* Whether the device needs a session handshake before it answers anything
  (it has never answered a single one of the ~2000 frames we sent, over
  both hidraw and raw USB, wired and wireless).
* Report id 7 (9 B) and report id 8 (12 B) are output-only in the
  descriptor and unused by us so far; the driver uses all three ids.
* Firmware diffing — the vendor ships `aj159nlp` firmware **1.0.21**; the
  device runs **1.0.13** (the image inside the installer).  Comparing the two
  would show whether the protocol changed.

