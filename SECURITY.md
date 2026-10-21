# Security policy

## What the panel enforces

The panel is a desktop tool with no authentication, so it defends itself
with a few small rules. All of them are covered by `tools/selftest.py`:

| rule | why |
|---|---|
| it binds `127.0.0.1` only | it is not reachable from the network |
| a request whose `Host` is not the loopback is refused (403) | DNS rebinding: a page cannot point a name at 127.0.0.1 and then talk to the panel |
| a write whose `Origin` is not the loopback is refused (403) | cross-site request forgery: another site cannot drive your mouse |
| a write must be `Content-Type: application/json` (415 otherwise) | a browser can only send a preflight-free cross-origin POST as a form, and that is refused |
| every served path is resolved and confined to `static/` and `assets/` (404 otherwise) | path traversal: no reading of `~/.ssh`, `~/.config` or anything else |
| the request body is capped at 4 KB (413 otherwise) | no memory abuse |
| the process runs as your user, never as root | a compromise of the panel is a compromise of your session, not of the machine |
| its state directory is `0700` and its files `0600` | nothing readable by other users on a shared machine |
| the only device it ever opens is a `0x7768` hidraw node | your other mice and keyboards are never touched |

There is no `subprocess`, no `eval`, no shell-out and no network client in
the panel. The only thing it writes to is the mouse, and only with the
frames that were measured (see [[Protocol]] in the wiki, or
`docs/CUSTOMIZATION.md`).

## What this tool is exposed to

Micetil talks to one device: an AJAZZ mouse with USB vendor id `0x7768`,
over a vendor HID collection on a hidraw node. It listens on
`127.0.0.1` and serves a static page plus a small JSON API.

The panel does not make outbound network connections, does not read files
outside its own cache directory (`~/.cache/ajazz-panel/`), and does not
need root.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it
privately to the maintainers at **faisalbiswas229@gmail.com** with:

* what the problem is,
* how to reproduce it,
* the panel version (the commit) and your OS.

You will get an acknowledgement, and a fix or an explanation.

## Things that are bugs, not vulnerabilities

* The panel only binds to `127.0.0.1`. It is not reachable from the
  network, and it is not authenticated — do not expose it through a proxy
  or a tunnel.
* The panel can write to the mouse. That is the point, and it is why the
  write path is restricted: only the frames that were measured are
  allowed, and classes `0x12` and `0x31` are refused outright.
* A raw USB capture contains the recording machine's details (OS build, CPU
  model). Captures are deliberately not committed to this repository.

## If you find a write that can damage the mouse's state

That is the highest-severity bug in this project, because the button map
and the LED profile cannot be restored from Linux today. Report it the same
way, and please include the frame you sent and the reply you got.

Until it is fixed, prefer the vendor's own "Restore Factory Settings" over
any experiment with the record/profile classes.
