<!--
What changed, and why.

If this touches the wire protocol, the "Measured" section is required:
the frame you sent, what the device answered, and how you read the value
back.  A protocol change without a read-back will not be merged.
-->

## What changed

<!-- one or two sentences -->

## Why

<!-- the problem this solves, or the measurement that motivated it -->

## How it was tested

- [ ] `python3 tools/selftest.py` passes
- [ ] checked in the browser (both themes, and a narrow window)
- [ ] tested on the hardware (mouse and/or receiver)

<!-- paste the self-test output, and what you did on the device -->

## Measured

<!--
For protocol changes: the exact frames, the replies, the read-back
values, and the date they were taken.  Delete this section if the change
does not touch the wire.
-->

```
```

## What could break

<!-- anything that might leave the mouse in a different state, or affect
     somebody else's setup -->

## Checklist

- [ ] the change is signed off (`git commit -s`)
- [ ] no new runtime dependency
- [ ] `docs/CUSTOMIZATION.md` updated, if the protocol changed
- [ ] the file map in `README.md` updated, if files were added or removed
- [ ] `docs/panel.png` refreshed, if the window changed visibly
