# Tartarus user guide

Tartarus is a local malware-analysis workbench for one analyst. You drop a Windows sample in, and it runs inside an isolated, hardened Windows VM while you watch processes, files, registry, network and detections appear live. Afterwards you explore the result with linked views and a query bar, annotate what matters, and export IOCs and a report.

Read [safety](safety.md) before you run anything. Tartarus runs live malware.

## Pages

| Page | Read it when |
|---|---|
| [Install](install.md) | You set up the stack on a Linux machine. |
| [Building a guest](building-a-guest.md) | You need a Windows VM to run samples in. |
| [Your first analysis](first-analysis.md) | You want to submit a sample and watch it run. |
| [Reading a report](reading-a-report.md) | An analysis has finished and you want to find what matters. |
| [Backup and disk](backup-and-disk.md) | Disk is filling up, or you want to keep your data. |
| [Troubleshooting](troubleshooting.md) | Something failed, or the page does not load. |
| [Safety](safety.md) | You want to know what a sample can reach. |

## More

- [Overview](../overview.md): what Tartarus is and why it exists next to CAPE.
- [Architecture](../architecture.md): the containers and how they connect.
- [Security](../security.md): the threat model, the fixes and the risks that remain.
- [GUI spec](../specs/gui.md): the exact behaviour of each screen.
- [README](../../README.md): the quick start for developers.

Commands in this guide are run from the repository folder. Button labels are written as the app shows them, in brackets.
