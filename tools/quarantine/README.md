# Quarantined: blind-write / blind-sweep tools

These scripts send frames that are **not** in the read-only whitelist in
`ajazz_protocol.py`. One of those frames is `06 11 01 00 00 00`, which
commits an empty staging buffer and **clears the mouse's button map in NV**
(it survives a power cycle; only the vendor's "Restore Factory Settings"
rewrites it).

Measured twice, both times right after a sweep that included that frame.

Do not run anything in this directory. The supported path is:

* reads: `python3 ajazz_protocol.py` (class 0x05 / 0x07 / 0x0f / 0x10 only)
* writes: only with a decoded capture of the official Windows app
  (`tools/parse_capture.py`) - i.e. with evidence, never by guessing.
