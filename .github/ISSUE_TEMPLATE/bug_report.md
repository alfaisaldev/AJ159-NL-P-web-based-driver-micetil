---
name: Bug report
about: Something in the panel is wrong
title: ""
labels: bug
assignees: ""
---

**What happened**

<!-- what you saw -->

**What you expected**

<!-- what should have happened -->

**The panel's own answers**

<!--
the output of:
  curl -s http://127.0.0.1:8778/api/battery
  curl -s http://127.0.0.1:8778/api/dpi
-->

```
```

**Setup**

- mouse USB id: `7768:6d25` (wired) / `7768:6425` (receiver)
- hidraw node the panel used:
- distro and kernel:
- python version:
- panel version (commit):

**Service log**

```
journalctl --user -u ajazz-panel -n 50
```
