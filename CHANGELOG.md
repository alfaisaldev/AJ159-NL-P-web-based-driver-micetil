# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-10-22

The first public release: a local control panel for the AJAZZ AJ159 NL P
mouse, and the protocol notes that came with it.

### Added

- **Battery** readout from the vendor HID collection (report id 6), with
  charging state, the source node and the age of the reading.
- **DPI stages**: read the six stored stages and change any of them in
  50 DPI steps, verified by reading the table back.
- **Active stage**: choose which of the six stages the mouse is using.
  There is no such command in the protocol; the device activates whichever
  stage frame it received last, so the table is rewritten with the chosen
  stage sent last.
- **Report rate**: 125 / 250 / 500 / 1000 Hz, read back from byte 24 of the
  device's info block.
- **Verification with rollback** on every write: the value is read back
  through an independent path, and the previous value is written again if it
  does not match.
- A desktop-style interface with a device column and cards for the pointer
  stages, the polling rate and the device, with a system / light / dark
  theme switch.
- `install.sh`: udev rule, systemd user service and an app-menu launcher.
- A self-test that runs without the mouse, and a CI workflow on Python
  3.9, 3.11 and 3.12.
- The protocol notes (`docs/CUSTOMIZATION.md`), the wiki, and the brand
  assets cropped from the identity board.

### Security

- The file server resolves the requested path and confines it to `static/`
  and `assets/`; a request could previously walk out of the directory with
  `..`.
- Requests whose `Host` is not the loopback are refused, so a rebound DNS
  name cannot talk to the panel.
- Writes whose `Origin` is not the loopback are refused, and writes must be
  `application/json`, so a page on the internet cannot drive the mouse.
- The request body is capped at 4 KB.
- The panel's state directory is `0700` and its files `0600`.
- The USB capture the protocol was decoded from is not published: it
  carries the recording machine's details.

### Known limitations

- The mouse's button map is not editable from Linux. The frames that write
  it were never captured, and a guess would cost the user their buttons.
- The older AJ-series mice (`0x3151:…`) use a different protocol and are
  not supported.

[Unreleased]: https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/alfaisaldev/AJ159-NL-P-web-based-driver-micetil/releases/tag/v1.0.0
