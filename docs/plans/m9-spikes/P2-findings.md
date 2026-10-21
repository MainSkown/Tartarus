# P2 findings: memory-image import (M9)

Spike on the real stack, 2026-10-21, Volatility3 2.28.2 as shipped in the `cape` image, control service as built in M8.
No product code was changed. The 4 GB dump, the two derived images, the fake task folders and every temporary change in
the container were deleted or reverted (`P-notes.md`).

## Verdict

**Go.** The control service's Volatility step already runs on a standalone image: it only needs
`storage/analyses/<digits>/memory.dmp` as a regular file, no CAPE task, no report. Two things are missing and both are
small: a mode that does not need the pids (today the two plugins that find injections are skipped without them), and
a place where the backend can put a large upload so the `cape` container sees it. An unknown Windows build resolves its
own symbols over the existing `POST /symbols` (needs the cape container's internet access).

## The check (could fail, did not)

Source: the dump of the injecting run, Tartarus analysis 370 (CAPE task 367), `memory_dump` + `keep_memory_dump`:
`memory.dmp` **4,294,776,995 bytes**, 4096 MB guest, `lab3` (build 10.0.26200, ISF `ntkrnlmp-24DE...E11.json.xz`).
The run's own memory step (with the report's pids 3344 and 3888) wrote 4 malfind rows, all `PING.EXE`, one with
`Notes: MZ header`.

The same file was hard-linked as `storage/analyses/900001/memory.dmp` (a task id CAPE never had, no report, no
`reports/`), which is the "re-upload" as far as the cape container can tell. It was not uploaded over HTTP: there is no
import endpoint yet.

| Step | Result |
|---|---|
| `POST /memory/900001/analyse` (control service, bearer token) as built | 200 in **2.1 s**: `pslist` 147 rows, `cmdline` 147 rows; `malfind` and `hollowprocesses` **skipped** (`"the report names no process of the analysis"`, `pids: []`) |
| `vol ... windows.malware.malfind` with no `--pid`, as user `cape`, `--offline` | **63 s**, 16 rows, 25,934 bytes; contains `PING.EXE` pid **3888**, `PAGE_EXECUTE_READWRITE`, `Notes: MZ header`, start 0x1d853720000: **the injection target is named** |
| `windows.malware.hollowprocesses` with no `--pid` | 66 s, 0 rows (the sample does not hollow); run in parallel with malfind the pair takes 66 s |
| Both findings through the product `VolatilityNormalizer`, report `{}`, `memory/` folder as above | 26 events (13 findings + 13 detections), 3 monitor pages dropped; the `PING.EXE` 3888 detection has severity **3**, the other 12 rows (11 `MsMpEng.exe`, 1 `OneDrive.exe`) severity 2 |
| Negative control: an 8 MB file of random bytes as the image | 200 in 0.2 s, every plugin `"no symbols for this Windows build"` and **no** `missing_symbols`: the run fails, but with a misleading message |

Scripts: `scripts/volt.py`, `scripts/vol_norm.py`. Fixtures: `fixtures/vol3-2.28.2-windows.malware.malfind.all-pids.json`,
`fixtures/vol3-2.28.2-windows.pslist.p9.json`.

## Formats

| Format | How tested | Result |
|---|---|---|
| ELF64 core (libvirt `coreDump`, what CAPE writes) | the original | works; `Elf64Layer`; 16 malfind rows |
| Flat raw | converted from the ELF segments (`PT_LOAD` at their physical addresses, sparse): 6,442,450,944 bytes logical, 4.29 GB on disk | works through the control service and `vol`; **identical** 16 rows. `dump_bytes` in `run.json` is the logical size (6.4 GB), not the disk size |
| Windows complete crash dump (`PAGEDU64`, type 1) | **synthetic**: header written by a script from the ELF segments, 4,294,778,880 bytes | works; `WindowsCrashDump64Layer`; **identical** 16 rows. Not a file Windows wrote, so a real `MEMORY.DMP` is unproven |
| Windows kernel or small crash dump | read from `volatility3/framework/layers/crash.py`: only types `0x1` (complete) and `0x5` (bitmap) are accepted | not usable for malfind (no user memory) |
| LiME, VMware `.vmem`, VirtualBox core, user-mode minidump | not tested | LiME and the others need a Linux ISF or are not Windows kernel images; out of v1 (the symbols step is `ntkrnlmp` only) |

Type sniffing for the import: `\x7fELF` with `e_type` 4, or `PAGEDU64` at offset 0; anything else can only be accepted
as "raw" by exclusion, so the endpoint should say what it assumed. The size is limited by the disk, not by Volatility:
the raw conversion of 4 GB took 4.4 s locally.

## Symbols for an unknown build

Tested by moving the guest's ISF out of the symbols directory (restored byte-identical afterwards):

1. `analyse` answers in **0.3 s** with every plugin `"no symbols for this Windows build"` and
   `"missing_symbols": {"guid": "24DE61DB3A27C5B383DFF181CB51F7E1", "age": 1}`.
2. `POST /symbols {"guid": ..., "age": 1}` answers `{"created": true}` in **20.5 s** (fetch of the 11.3 MB PDB from
   `msdl.microsoft.com`, conversion with `pdbconv`, 708,124 bytes as `.json.xz`).
3. `analyse` again: 2.0 s, `errors: {}`.

So the "unknown build" case resolves itself, on a machine whose `cape` container can reach Microsoft's symbol server;
without that, import is limited to builds that already have a file (every current guest is 10.0.26200). Side effect
seen again (as in S3): the failed lookup created `site-packages/volatility3/symbols/windows/ntkrnlmp.pdb/` in the image;
harmless, removed by hand. The image's own build is read from the image, so no guest is involved.

## What the endpoint needs

- **Control service.** A route for an image without a CAPE task, for example `POST /memory-images/{analysis_id}/analyse`
  (body `{"pids": null}` means all). `_dump_of` and the `memory/` output folder stay; `pids_from_report` is skipped. With
  no pids the two per-process plugins run unrestricted and **in parallel** (66 s, not 129 s in sequence): the existing
  limits (120 s per plugin, 300 s overall) hold for this 4 GB / 147-process image, with little margin for a bigger one
  (not measured). A cheaper partial mode exists: `--pid` of the processes with `SessionId > 0` took **13.6 s** and kept
  the `PING.EXE` row, but would miss anything in session 0 (services), so not a default.
- **A shared folder.** The backend sees `cape-storage` read-only; the upload must land where `cape` can read and delete
  it, i.e. a new volume (read-write in the backend, read-write in `cape`) or a route that streams the body to the control
  service. The control service refuses symlinks, so the file must be real (a hard link worked).
- **Error classes.** Separate "not a memory image / no kernel found" from "no symbols for this build": today both read
  "no symbols for this Windows build", and only the second carries `missing_symbols`.
- **Time of the findings.** There is no report, so no `info.ended`; `windows.info` has `SystemTime`. Here it read
  `2026-10-21 10:54:23+00:00` while the host clock said 12:54 UTC at the dump, so the guest clock was 2 hours behind;
  an imported finding's time is the guest's belief, not UTC truth. Use it labelled as such.
- **Noise.** Without the run's pids the Defender and OneDrive rows come back: 12 of 13 findings are noise; only the
  `MZ header` row has severity 3. The capemon-page rule still drops 3 pages in an image from a monitored guest and does
  nothing for an image from elsewhere.
- **Limits that exist today.** `frontend/nginx.conf` allows 512 MB for `/api` bodies with `proxy_request_buffering off`
  and `proxy_read_timeout 300s`: a 4 GB upload needs its own larger location. `memory_disk.py`'s free-space check
  must apply (an image costs its size, and CAPE's own 50 GB floor does not cover it). The dump is deleted after the
  findings unless kept, through the existing delete route.

## Not verified

The HTTP upload path (nginx, backend, shared volume); a real Windows-written `MEMORY.DMP`; an image of another Windows
build or of Windows 10; images larger than 4 GB or with far more processes (plugin time and memory scale unmeasured,
RSS not measured here, S3 saw 237 MB); a cold page cache (the file was cached); non-injection findings (hollowing,
ghosting) from an imported image; behaviour when `cape` has no internet and no ISF exists.
