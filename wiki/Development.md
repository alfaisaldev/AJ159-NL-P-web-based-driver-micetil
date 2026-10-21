# Development

The rules are in the repository:
[`PRACTICE.md`](https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil/blob/main/PRACTICE.md)
(how the work is done) and
[`CONTRIBUTING.md`](https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil/blob/main/CONTRIBUTING.md)
(how to contribute).

## Setup

```bash
git clone https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil.git
cd AJ159-NL-P-web-based-driver-micetil
python3 tools/selftest.py        # 25 checks, no hardware needed
python3 server.py --port 8778    # run the panel
```

Standard library only — no dependencies to install, on either side.

## The self-test

```bash
python3 tools/selftest.py
```

It covers the parts that are pure logic, and needs no mouse:

* the wire format (encode/decode),
* the DPI and rate encodings, including the stage ordering,
* the read-only whitelist and the quarantined classes,
* that every element id the script asks for exists in the HTML.

CI runs it on Python 3.9, 3.11 and 3.12, plus a check that the panel starts
and answers `/api/health`.

## Layout of the code

| file | what lives there |
|---|---|
| `server.py` | the HTTP server: routes, the JSON API, the verify-and-roll-back write handlers |
| `battery.py` | device access: finding the vendor node, listening for the pushes, parsing the TLV entries, reading and writing the DPI table / stage / rate |
| `ajazz_protocol.py` | the wire format, the read-only whitelist, the quarantined classes, the frame builders |
| `static/index.html` | the entire UI — one file, no framework, no build step |
| `tools/` | the reverse-engineering tools and the checks |
| `docs/CUSTOMIZATION.md` | the protocol log: every frame, every measurement, every correction |

## Adding a protocol feature

1. **Find the frame.** From a capture of the vendor application, from a
   reply the mouse already gives, or from a measurement. A guess is not
   enough — an early guess cleared the mouse's button map.
2. **Read the value back** through a path that does not depend on the write.
   If the value cannot be read back, the API has to say so and the UI has to
   show it as unverified.
3. **Roll back** on a mismatch: write the previous value again and report
   the failure.
4. **Document it** in `docs/CUSTOMIZATION.md` with the frames, the
   measurements and the date.
5. **Test it** in `tools/selftest.py` with the measured values, not with
   values invented for the test.

Useful tools while you work:

```bash
python3 tools/read_blocks.py            # every config block, read-only
python3 tools/dpi_roundtrip.py 1 1600   # write stage 2 = 1600 DPI, verified
python3 tools/measure_rate.py           # the mouse's real USB polling rate
python3 tools/monitor_input.py          # raw interrupt-IN traffic
python3 tools/parse_capture.py file.pcapng
```

## The tools that must never be run on a device

`tools/quarantine/` holds the enumeration and sweep scripts from the
discovery phase — they send frames the device was not yet known to accept.
Read `tools/quarantine/README.md` first.

## Working on the UI

* `static/index.html` only, one file.
* The script and the HTML must keep agreeing on element ids — the
  self-test checks it.
* Check both themes and a narrow window.
* Refresh `docs/panel.png` if the window changed visibly.

## Commits

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/), and every
commit is signed off:

```bash
git config commit.signoff true
```

```
feat(ui): add a report-rate read-back row
fix(protocol): keep the current stage last when a DPI stage is edited
docs: document the byte 11 active-stage measurement
```
