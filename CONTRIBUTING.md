# Contributing to Micetil

Thanks for looking at Micetil — a local control panel for the AJAZZ
AJ159 NL P mouse, written against the vendor HID protocol that was
reverse-engineered on Linux.

This project has two very different kinds of contribution, and they carry
different risk. Read the section that matches yours.

* **Interface, documentation and tooling** — low risk, easy to review.
* **Anything that writes to the mouse** — high risk. It is reviewed hard,
  and it needs evidence.

---

## The short version

1. Open an issue first for anything bigger than a bug fix, so we do not
   waste your time on a change that will not be merged.
2. Sign off every commit (`git commit -s`).
3. Keep the change small and the commit history readable.
4. Run `python3 tools/selftest.py` before you push.
5. Follow `PRACTICE.md` — it is the short version of this file, and it
   wins in a disagreement.

## Before you start

**Sign your work.** Micetil uses the [Developer Certificate of
Origin](https://developercertificate.org/): add `-s` to your commits, and
GitHub will add the `Signed-off-by` trailer for you.

```bash
git config commit.signoff true
```

**No third-party code gets executed here.** Do not commit binaries, build
artefacts or code you did not write. Reading and analysing other people's
code is fine; running it is not part of this project's practice.

**Runtime dependencies stay at zero.** The panel and the tools use the
Python standard library only. A pull request that adds a dependency needs a
very good reason and a discussion first.

## Setting up

```bash
git clone https://github.com/alfaisaldev/micetil.git
cd micetil
python3 tools/selftest.py        # 25 checks, no hardware needed
python3 server.py --port 8778    # the panel, on your own machine
```

For the hardware path you need the mouse plugged in (or its NearLink
receiver) and read access to the vendor hidraw node. `install.sh` sets
that up with a udev rule — read it before you run it, it touches
`/etc/udev/rules.d`.

You do not need root for development; you only need it for the udev rule.

## What a change to the UI should look like

* `static/index.html` only — one file, no framework, no build step.
* Keep the element ids the script uses (`pct`, `stageSeg`, `rateSeg`,
  `dpiList`, `dpiHint`, …). The self-test checks that the script and the
  HTML still agree, so a rename that breaks the wiring fails the test.
* Check both themes (system / light / dark) and a narrow window.
* Refresh the screenshot in `docs/panel.png` if the window changed
  visibly.

## What a change to the protocol must include

This is the part that matters. A pull request that sends new frames to the
mouse has to answer all of these:

1. **Where does the frame come from?** A capture of the vendor application,
   a reply from the mouse, or a measurement. Not a guess.
2. **What is the read-back path?** How do you prove the device stored the
   value?
3. **What happens on a mismatch?** The old value has to be restored, and
   the failure has to be reported — not hidden.
4. **Does it touch a quarantined class?** `0x12` and `0x31` are refused by
   `ajazz_protocol.py` and they stay refused. Changing that needs a
   discussion in an issue, not a patch.
5. **Is it documented?** A section in `docs/CUSTOMIZATION.md` with the
   frames, the measurements and the date they were taken.

A protocol change without a read-back is not ready. "The panel now says it
wrote 1600 DPI" is not an acceptable outcome; "the panel wrote 1600 DPI
and the mouse read 1600 DPI back" is.

## Commits

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/):

```
feat(ui): add a report-rate read-back row
fix(protocol): keep the current stage last when a DPI stage is edited
docs: document the byte 11 active-stage measurement
test: cover the stage ordering in dpi_frames_for_stage
```

* one logical change per commit
* no "fixed stuff" and no "WIP" in a merged branch
* `git rebase -i` before you ask for a review, if it makes the history
  easier to read

## Opening a pull request

Describe:

* **what changed** and **why**,
* **how you tested it** (self-test output, and what you did on hardware),
* **what you measured**, with the frames or the values,
* **what could break** on somebody else's mouse.

A pull request that changes the wire behaviour should include the
before/after read-back values.

## Reporting a bug

Open an issue with:

* the mouse's USB id (`7768:6d25` wired, `7768:6425` receiver) and the
  hidraw node the panel used,
* the panel's output: `curl -s http://127.0.0.1:8778/api/battery` and
  `curl -s http://127.0.0.1:8778/api/dpi`,
* the service log: `journalctl --user -u ajazz-panel -n 50`,
* what you expected and what happened.

Never attach a raw USB capture to an issue without checking it first: a
capture carries the recording machine's details. `git ls-files` in this
repository does not contain a capture for exactly that reason.

## Security

Do not open a public issue for a bug that could brick the mouse or leak
data. Follow `SECURITY.md`.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
Report unacceptable behaviour to the maintainers; the contact address is in
that file.

## License

Micetil is released under the license this repository is published under.
Contributions are accepted under the same terms.
