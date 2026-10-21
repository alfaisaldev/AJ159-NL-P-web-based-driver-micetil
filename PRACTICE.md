# Micetil — development practice

The rules this project works by. They are short because the project is
small, but they are strict because the code touches somebody's real mouse.

If a rule here and your pull request disagree, the rule wins until
someone changes it in this file.

---

## 1. Evidence beats inference

This is the rule the whole project is built on.

* Every statement about the device is either **measured** (it was sent, and
  the device answered) or it is labelled **inferred** (it is a hypothesis,
  and it says so).
* A protocol change needs a trace: a frame from the vendor application, a
  reply from the mouse, or a capture. A plausible guess is not a reason to
  send bytes to somebody's hardware.
* When a guess turns out to be wrong, the wrong claim gets corrected in the
  same change that fixes it. `docs/CUSTOMIZATION.md` carries a "Correction
  to §3g" section for exactly this — wrong beliefs are recorded, not hidden.

The rule exists because guessing is expensive here: an early sweep that sent
a frame with an empty payload to class `0x12` cleared the mouse's **button
map**, twice, and only the vendor's "Restore Factory Settings" brought it
back.

## 2. The write discipline

The panel may write to the mouse. Everything else may not.

| rule | where it lives |
|------|-----------------|
| Reads are the default: only the five frames the vendor driver itself sends | `ajazz_protocol.READ_ONLY` |
| Classes `0x12` (records) and `0x31` (LED/profile) are refused outright | `ajazz_protocol.QUARANTINED_CLASSES` |
| A frame with a payload is refused unless the write path explicitly allows it | `AjazzDevice.send()` |
| Every write is read back and compared; on a mismatch the previous state is written again | `battery.py::_confirm_dpi`, `server.py::_handle_dpi` |

Rules for anything new that writes:

1. Take the frame shape from the vendor application's own traffic. Do not
   invent one.
2. Write it, then read the value back through an independent path.
3. If the read-back does not match, restore the previous state before
   reporting anything.
4. If the value cannot be read back, say so in the API response and in the
   UI. Never report an optimistic value.

Never run a sweep against a device that is not yours, and never send a
frame that the project has not already proven harmless.

## 3. Working with the hardware

* Only touch USB devices with vendor id **`0x7768`**. Other HID devices on
  the machine (a personal mouse, a keyboard) are never opened, unbound or
  written to.
* No root for normal use. The udev rule makes the vendor nodes readable by
  the `plugdev` group. `pkexec` is acceptable for a one-off, privileged
  step, and nothing else.
* The mouse must survive the change. If a change can leave the device in a
  state the vendor's own app cannot recover from, it does not ship.
* The receiver relays writes with a delay: a read straight after a write can
  return the previous block. Verification polls for up to ~3 s.
* Report what the device said, not what the panel wanted. The API returns
  the values it read back, and the UI shows them.

## 4. Code style

**Runtime dependencies: none.** Standard library only, on the panel side
and in the tools. The panel has to run on a bare Linux install, and the
tools have to run on a machine where nobody wants to install a toolchain.

* Python 3.8+, four-space indent, PEP 8, 90-column soft limit.
* Type hints on public functions; `from __future__ import annotations`.
* Docstrings say **what** the function does and **why** it does it that
  way. If a constant encodes a measurement, the comment carries the
  measurement, not a restatement of the name.
  ```python
  # The active DPI stage is byte 11 of the class-0x05 block, zero based.
  # Measured: all six stages written, stage 3 last -> byte 11 = 3.
  INFO_ACTIVE_STAGE = 11
  ```
* Comments explain *why*, never *what*. The code already says what.
* No clever code. This project is read by people trying to work out what a
  byte on the wire means; clarity beats elegance every time.
* The UI is one HTML file (`static/index.html`) with no framework and no
  build step. Keep it that way: the whole panel must be servable from a
  directory copy.
* Never log a raw capture or a device serial to a shared log. The panel's
  own logs stay in `~/.cache/ajazz-panel/`.

## 5. Tests

```bash
python3 tools/selftest.py        # no hardware needed
```

The self-test covers the wire format, the DPI and rate encodings, the
read-only guard rails and the agreement between the HTML and the script
that drives it. It runs in CI on every push.

Rules:

* A bug fix comes with a test that fails before the fix.
* A protocol change comes with a test that encodes the measured value
  (the real block, the real frame) — not a value invented for the test.
* Tests must run without the mouse. If a test needs hardware, it lives in
  `tools/` as a script you run on purpose, not in the CI suite.

## 6. Documentation

* `docs/CUSTOMIZATION.md` is the protocol log: every frame, every
  measurement, every correction. New protocol knowledge goes there first.
* The README is the guide: what the panel does, how it talks to the mouse,
  the safety model, the API, the file map.
* `PRACTICE.md` (this file) and `CONTRIBUTING.md` say how the work is done.
* When you add a file, add it to the file map in the README. A map that
  lies is worse than no map.

## 7. Commits, branches, releases

* Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/):
  `feat(ui): …`, `fix(protocol): …`, `docs: …`, `test: …`, `chore: …`.
* One logical change per commit. A protocol fix and a UI restyle are two
  commits.
* Branches: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`.
* Every commit is signed off (`git commit -s`) — see `CONTRIBUTING.md`.
* Versions follow [SemVer](https://semver.org): a bug fix is a patch, a new
  capability is a minor, a changed API or a changed wire behaviour is a
  major.
* Release checklist: the self-test passes, the README and the API table
  match the code, `docs/panel.png` shows the current UI, and the tag
  points at a clean tree.

## 8. What this project will not do

* No Wine, no Windows-only tooling, no vendor driver installed on Linux.
* Nothing downloaded from a third-party repository is executed here. Other
  people's code is read and analysed, never run.
* No blind sweeps against hardware, no "let's see what class 0x2a does".
* No scraping, no telemetry, no network calls out of the panel. It talks to
  the mouse and to nothing else.
* The button map stays untouched until it is understood well enough to be
  written correctly — a capture or nothing.
