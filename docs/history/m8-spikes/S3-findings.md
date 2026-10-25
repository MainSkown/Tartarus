# S3 findings: memory dump and Volatility3 findings (M8)

Spike on the real stack, 2026-10-19. Guest `m8-s3` (a throwaway clone of `lab3`, Windows 11 25H2, build 10.0.26200,
2 vCPU, 4096 MB RAM, `memballoon` none), CAPE at the pinned `CAPE_REF`, Volatility3 2.28.2. No product code was
committed and nothing was staged. Every change inside the `cape` container was reverted (list at the end), the guest,
all analyses and all dumps were deleted, and free space on `/` is back to 398 GB. The repo tree only gained
`docs/history/m8-spikes/S3-notes.md` and this file.

## Verdict

**Ship in v1 as dump + findings**, with four conditions that the measurements below force:

1. **Volatility runs Tartarus-side, not in CAPE's `memory.py`.** CAPE's module scans all 144 processes (62 to 69 s
   each for malfind and hollowprocesses, 136 to 154 s in total added to `reported`), cannot restrict to the sample's
   pids, cannot dump regions, and left every processed `memory.dmp` held open by `cape-processor` (4.3 GB each not
   freed after the task was deleted). The same plugins with `--pid` take 0.8 s.
2. **Symbols are offline files generated per guest build**, 0.7 MB each (`.json.xz`); no ISF, no findings (the dump
   still ships).
3. **Findings are filtered**: 12 of 22 malfind rows were Defender and OneDrive, 8 of the other 10 were capemon's own
   RWX pages. Only the two injections carried the `MZ header` tag.
4. **`netscan` is not part of v1**: it returned 0 rows on build 26200 although the guest's agent listens on port 8000.

The dump itself is cheap to take (1 to 2 s typical, 10.7 s once under page-cache pressure) and does not change the
analysis. The cost is disk: **4,294,776,995 bytes (4.0 GiB) per analysis** for a 4096 MB guest.

## Numbers

| Item | Measured |
|---|---|
| Dump format | ELF64 core file (`ET_CORE`, x86-64): 1 `PT_NOTE` + 8 `PT_LOAD`; Volatility3 stacks it as `Elf64Layer` with no conversion |
| Dump size (4096 MB guest) | 4,294,776,995 bytes in all 4 dumps (the 4 GiB of RAM minus the PCI hole, plus 10 KB of headers) |
| Written by | libvirt `coreDump(..., VIR_DUMP_MEMORY_ONLY)`, owned `cape`, mode 0644, at `storage/analyses/<id>/memory.dmp`, never compressed |
| Dump time (guest finished to task released) | no dump 1.2 s (3 runs); dump 2.1, 2.2, 2.2 s; one run at 10.7 s (4th dump in 8 minutes, page cache full) |
| Guest analysis length (agent start to finish), same sample | memory=1: 64.1 s, 65.1 s; memory=0: 66.2 s, 64.3 s |
| Score and signatures, same sample | memory=1: 6.0 and 20, 6.0 and 20; memory=0: 6.0 and 20, 6.0 and 20; the four signature sets are identical |
| `completed` to `reported` | no dump 3.1 to 7.2 s; dump, CAPE memory module off 4.2 and 8.2 s; dump + CAPE memory module on 162 s and 157 s |
| `report.json` | 3.97 / 4.03 MB (memory=0) vs 4.10 / 4.15 MB (memory=1 + CAPE module); the `memory` section is ~100 KB |
| Volatility3 wheel | 1.42 MB, pure Python, sha256 `0461d6dd71b9ddbaf70c96e079c06efdf174ac65383b3dcf10dd165181fbd3c3`; installed 10.1 MB (15 MB with `.pyc`); only dependency `pefile >= 2024.8.26` (the CAPE venv has 2024.8.26) |
| Kernel symbols | PDB `ntkrnlmp.pdb`, GUID `24DE61DB3A27C5B383DFF181CB51F7E1`, age 1; PDB download 11.3 MB; ISF 7.56 MB JSON, **708,160 bytes as `.json.xz`**; fetch + convert about 30 s (from file timestamps) |
| Guest's own `ntoskrnl.exe` | 13,039,048 bytes through the agent in 0.1 s; its debug directory gives the same GUID and age as the dump |
| Plugin peak memory | 237 MB RSS, one CPU core, for the slowest plugin |

Plugin runtimes (offline, dump 4.3 GB, 144 processes, file mostly in page cache):

| Plugin | Time | JSON size | Result on the injecting sample |
|---|---|---|---|
| `windows.info` | 0.6 s | 2 KB | kernel base, DTB, symbols file |
| `windows.pslist` | 0.8 s | 45 KB | 144 rows; the injected and the hollowed `PING.EXE` with their parent |
| `windows.pstree` | 1.0 s | 110 KB | same, as a tree (`__children`) |
| `windows.cmdline` | 0.8 s | 33 KB | `Args` per pid; the frozen hollowed process has `null` |
| `windows.psscan` | 8.7 s | 51 KB | pool scan; same columns as pslist (finds exited processes) |
| `windows.malware.malfind` (all) | 62 to 65 s | 36 KB (22 rows) | **found the injection** |
| `windows.malware.malfind --pid a b c` | 0.8 to 0.9 s | 9 to 14 KB | same two true positives, without the system noise |
| `windows.malware.hollowprocesses` (all) | 65 to 69 s | 0.4 KB | **found the hollowed process** (2 notes) |
| `windows.malware.hollowprocesses --pid a b c` | 0.8 to 0.9 s | 0.4 KB | same |
| `windows.netscan` | 14 s | 4 bytes (`[]`) | **0 rows**: only false-positive pool tags, on build 26200 |
| `windows.netstat` | n/a | n/a | needs `tcpip.pdb`, a second fetch; not tried |

## Method

Sample: `memtest3.exe` (C, built with mingw in the cape container, harmless, source kept in the scratchpad). It starts
two `ping.exe -n 1000/1001`; into one it writes a `MZ`/PE-looking 1 KB buffer with a `xor eax,eax; ret` stub in an
`PAGE_EXECUTE_READWRITE` allocation and runs it with `CreateRemoteThread`; the other it hollows (freeze all threads,
`NtUnmapViewOfSection`, map its own image at 0x140000000 as RWX, patch `PEB.ImageBaseAddress`) and leaves frozen. Two
earlier versions: v1 resumed the hollowed process and it exited within a second (probably CFG on a private
indirect-call target; not proven), v2 hollowed a never-run suspended process, which `hollowprocesses` skips (it
ignores a process with fewer than 3 loaded DLLs). v3 is the one that works. Runs went straight to CAPE's `apiv2` from
inside the cape container (the backend has no `memory` field yet) with the driver `run3.py`; 9 tasks of mine (plus the clone's self-test), 4 dumps, never
more than 2 dumps on disk, each deleted through CAPE's task delete with a check afterwards.

Volatility3 was installed with `pip install --target /opt/vol3-spike` (plus a `.pth` in the CAPE venv) from a wheel
downloaded on the host. The ISF was built **on the host** with Volatility's own converter (one fetch of
`ntkrnlmp.pdb` from msdl.microsoft.com), then copied into the container.

## 1. The dump

- **How CAPE does it.** `analysis_manager.machine_running()` calls `dump_machine_memory()` after the guest reports
  the analysis finished and before `stop_machine`; it runs when `cuckoo.conf [cuckoo] memory_dump = yes` or the task
  has `memory` set. For `kvm` the abstract libvirt machinery's `dump_memory()` pre-creates the file as `cape`, then
  `vm.coreDump(path, flags=VIR_DUMP_MEMORY_ONLY)`: QEMU's ELF dump of guest physical memory. The guest is paused for
  the dump (no `VIR_DUMP_LIVE`), which is the 1 to 2 s. Path from `get_memdump_path()`:
  `storage/analyses/<task>/memory.dmp`. Nothing compresses it.
- **The spec is wrong about how to ask.** `docs/specs/cape-integration.md` ("Submit") says `memory=1` goes into the
  `options` string. Measured: `options=memory=1` produced **no dump** (task 333); the **form field** `memory=1`
  (`task.memory`) did. The backend's `task_fields={"memory": True}` already sends the right thing
  (`_form_fields` turns `True` into `"1"`); `memory_dump` in the analysis options must feed `task_fields`, not
  `options`.
- **Works with this guest's domain.** UEFI + Secure Boot + swtpm, `migratable='on'`, `memballoon model='none'`,
  restored from the external `tartarus-clean` memory snapshot: four dumps, and the next run on the same guest was
  normal each time. `memballoon none` is why the size is the full 4 GiB every time (it would shrink with a balloon).
- **Does the dump make CAPE skip it silently?** Yes, by design: if free space on the storage volume is below
  `cuckoo.conf freespace` (default **50,000 MB**) CAPE logs `Not enough free disk space! Could not dump ram` and the
  task still ends `reported` with no `memory.dmp`. Read from source, not triggered. The same 50 GB floor stops
  CAPE from starting any task.
- **Backend artifacts view.** `views/artifacts.py` expects exactly `memory.dmp` in the folder; it reports `size` from
  `stat`, `sha256`/`md5` null, `downloadable` true. Download packs the whole file into an AES zip in a temp file in
  the **backend container's `/tmp`**: measured 76 s and a 1.24 GB temp file (3.5:1) for a 4.3 GB dump, so the first
  byte of a download is 76 s away. Only the pack function was timed, not the HTTP endpoint.
- **A deleted dump is not freed.** After `tasks/delete`, `df` did not change: `cape-processor` (`process.py auto`)
  still had `memory.dmp` open for the tasks it had processed with the Memory module (4 handles, 8.6 GB). Restarting
  `cape-processor` freed it at once (369 GB to 377 GB free). The reprocess run (`process.py -r`, which exits) did not
  leak. Cause not diagnosed.

## 2. Volatility3 in the image

- CAPE's `modules/processing/memory.py` imports `volatility3` as a library, builds a `JsonRenderer` subclass, runs
  the plugins listed in `conf/default/memory.conf.default` by the old class names (`windows.malfind.Malfind`,
  `windows.hollowprocesses.HollowProcesses`, ...), and puts each result list under `report.json["memory"][<key>]`.
  `processing.conf [memory] enabled = no` and every plugin in `memory.conf` is `enabled = no`. CAPE's own
  `pyproject.toml` has `# "volatility3==2.11.0"` commented out.
- **Version.** 2.28.2 renamed those plugins to `windows.malware.malfind` and `windows.malware.hollowprocesses`; the old
  names still work as deprecated aliases (same output, same 33,062 bytes, a `FutureWarning` that says they go after
  2026-06-07 and have not). Pin **2.28.2 exactly** and re-run the fixtures on a bump.
- **`memory.conf [basic] dostrings = yes` must be `no`.** The code reads the whole dump with `Path.read_bytes()` and
  regexes it (4.3 GB into Python memory, then a `.strings` file next to the dump). I did not run it: the host had 9 GB
  available.
- **Dockerfile change (not built; the build cache is empty and a rebuild recompiles QEMU):** in the `cape-build` stage,
  after `uv sync --frozen --no-dev`:

  ```dockerfile
  COPY cape/build/volatility3.requirements /build/
  RUN uv pip install --python .venv/bin/python --no-deps --require-hashes -r /build/volatility3.requirements
  ```

  with `cape/build/volatility3.requirements` holding
  `volatility3==2.28.2 --hash=sha256:0461d6dd71b9ddbaf70c96e079c06efdf174ac65383b3dcf10dd165181fbd3c3`. The wheel is
  fetched from PyPI at image build (the build has network), so nothing is vendored in the repo; vendoring the 1.4 MB
  wheel under `cape/vendor/` and `--no-index --find-links` is the offline-build alternative. Size added to the 3.87 GB
  image: about **15 MB**.

## 3. Symbols

- **Identity.** The kernel PDB GUID and age come from the dump (`PdbSignatureScanner`) **or from the guest before any
  run**: the agent's `/retrieve` returned `ntoskrnl.exe` in 0.1 s, and `pefile` on its debug directory gave
  `ntkrnlmp.pdb`, GUID `24DE61DB3A27C5B383DFF181CB51F7E1`, age 1, equal to the dump's. The agent is 32-bit, so the
  path must be `C:\Windows\Sysnative\ntoskrnl.exe`; `System32\...` is redirected and answers 404.
- **Making the ISF.** `python -m volatility3.framework.symbols.windows.pdbconv -p ntkrnlmp.pdb -g <GUID><AGE>
  -o out.json` fetches the PDB and converts it (the GUID argument is the GUID with the age appended:
  `24DE...F7E1` + `1`). Output 7.56 MB JSON (48,485 symbols, 1,963 types), 0.71 MB after `xz -9`; Volatility reads
  `.json.xz` directly.
- **All current guests have the same build.** `win`, `lab1`, `lab3`, `lab5` are all `Win11_25H2_Polish_x64_v2.iso`,
  10.0.26200, updates off; `lab3` is a clone of `lab1`, `lab5` of `lab3`. One ISF serves them (only `lab3`'s clone was
  checked by GUID). Windows 10 22H2 (M10) needs its own, made the same way.
- **Offline, proven.** Every standalone run used `--offline`. CAPE's own `VolatilityAPI` (no offline flag) ran
  `pslist` (148 rows, 0.6 s) inside `unshare -n`, a network namespace with only `lo`. With the ISF removed and no
  network, the same call raised `UnsatisfiedException` in 2 s (CAPE's manager catches it and the report simply has no
  memory section).
- **How the ISF is passed.** Two places work in library mode (CAPE has no `--symbol-dirs`):
  `<site-packages>/volatility3/symbols/windows/` and `$HOME/.cache/volatility3/symbols/windows/` (`HOME=/home/cape`).
  **A symlinked directory is not followed** (`symbols/windows -> elsewhere` failed, rc 1); a symlinked ISF *file*
  inside a real directory works. A failed lookup also creates `<name>.pdb/` directories inside the symbol directory,
  so it must be writable or those writes must be tolerated (a read-only mount was not tried). The identifier cache
  (`identifier.cache`, 49 KB) goes to `$HOME/.cache/volatility3`.
- **The cape container is not offline.** `tartarus-internal` is a plain bridge (`Internal=false`) with a default route;
  `curl http://msdl.microsoft.com/` from inside `tartarus-cape` answered 200. With no ISF on disk and `constants.OFFLINE`
  left `False` (CAPE's module never sets it) Volatility would fetch the PDB from Microsoft on its own. Whatever runs
  Volatility must set offline (`--offline` on the CLI).
- **Where ISFs live.** A data directory (`data/symbols`, like `data/iso`), not the image and not the repo: a
  per-build file of 0.7 MB, one per Windows build, created when a guest is registered. Mounted at
  `/home/cape/.cache/volatility3/symbols/windows` for the Volatility process. Generating at registration: a
  `symbols` step after `snapshot` in the build and clone pipelines (guest agent `/retrieve` of `ntoskrnl.exe`,
  RSDS parse with `pefile`, skip if the file exists, else `pdbconv`). The conversion needs the PDB from msdl; either
  the control service does it (the cape container has egress, see above, which contradicts "no internet by design"),
  or an explicit host step (`make symbols`) for an air-gapped install, with the GUID recorded in the guest's
  record so the GUI can say "no symbols for build 10.0.26200.x".

## 4. Plugins and findings

Columns of the JSON renderer (CAPE's `ReturnJsonRenderer` and the CLI agree, plus `__children`):

- **malfind**: `PID`, `Process`, `Start VPN`, `End VPN` (integers, not hex strings), `Protection`
  (`PAGE_EXECUTE_READWRITE`), `Tag` (`VadS`), `PrivateMemory`, `CommitCharge`, `Notes` (`MZ header` / `Function
  prologue` / null), `Hexdump`, `Disasm`, `File output` (`Disabled`, or the file name with `--dump`). Maps to
  `process.pid` = `PID`, `tartarus.memory.plugin` = `windows.malware.malfind`, `.address` = `Start VPN` (as hex),
  `.protection` = `Protection`, `.dump_ref` = the artifact made from `File output`. The injected region
  (0x1e3eba60000, size 0x2000, `MZ header`) is exactly the allocation the sample wrote; the dumped 8,192-byte file
  has the stub at 0x200.
- **hollowprocesses**: only `PID`, `Process`, `Notes`; the address is inside the note text
  (`The ImageBaseAddress reported from the PEB (0x140000000) does not match the process SectionBaseAddress
  (0x7ff7d7a90000)`, `There is no VAD starting at the base address of the process executable (...)`). No
  protection or dump. It flags a process only after its loader ran (>= 3 DLLs) and only while it is alive.
- **pslist / psscan / pstree**: `PID`, `PPID`, `ImageFileName`, `CreateTime`, `ExitTime`, `Threads`, `Handles`,
  `SessionId`, `Wow64`, `Offset(V)`. **cmdline**: `PID`, `Process`, `Args`.
- **Noise (dump of the injecting sample, 22 malfind rows):** 11 `MsMpEng.exe` (the Defender service runs even on this
  Defender-off guest), 1 `OneDrive.exe`, 8 capemon pages in the sample's processes, 2 true positives. The capemon
  pages sit at the **same addresses in every monitored process and in all 4 runs**
  (0x7ffbbf7c0000, 0x7ffbc09c0000, 0x7ffbc0bd0000), untagged. Rule that fits the evidence: keep a row only for a pid
  the analysis's own events know about, and drop a region that appears at the same address in two or more of the
  analysis's processes; the `MZ header` tag is a strong positive but real shellcode has none. Not tested beyond this
  sample.
- **Which side runs it.** CAPE's module: 136 s (reprocess) and 154 s (in the pipeline) added before `reported`, all
  processes, no region dumps, no `--pid`, the `dostrings` trap, the leaked file handle, and the old plugin names.
  Tartarus-side: 0.8 s per plugin with `--pid`, `--dump` yields the region files (4 to 140 KB), and a subprocess
  releases its handles on exit. **Recommended: the guest-control service in the `cape` container runs `vol` as a
  subprocess** (`--offline`, `--pid <pids from the analysis events>`, `-r json`, a timeout, an address-space limit,
  the unprivileged `cape` user), and the backend calls it over the existing control network after the callback and
  turns the JSON into `memory-finding` events. Reasons: the dump is local and writable there (the backend sees
  `/cape-storage` read-only, so it can read it but cannot delete it), the symbol directory and internet access are
  already there, and parsing a hostile guest's memory belongs in the container that already runs QEMU rather than in
  the process holding the database and OpenSearch credentials. The backend-side alternative works for reading
  (the dump is readable there; I read all 4.3 GB in the zip test) but was not run with Volatility.

## 5. Does `memory=1` change the analysis?

No. Same sample (`memtest3.exe`), same guest, two runs each: score 6.0 and 20 signatures in all four, identical
signature sets, guest analysis length 64.1 / 65.1 s (memory=1) vs 66.2 / 64.3 s (memory=0). `info.duration` is 5 to 10
s longer with a dump because CAPE counts the dump in it. That is two runs each, one guest, one sample.

## 6. Recommendation

**Ship in v1: dump + findings (malfind, hollowprocesses, with pslist and cmdline as context).** Details:

- **Submit.** The checkbox "Full memory dump" sets `options.memory_dump` and sends `task_fields["memory"] = True`
  (not `options`). Warning text numbers, computed from the chosen guest: "about 4.3 GB of disk (the guest's RAM,
  4096 MB), 2 to 11 seconds added to the run, findings about 5 seconds later". The size is `ram_mb` of the guest
  plus 10 KB, for any guest.
- **Disk check before accepting.** Required free space on the CAPE storage volume =
  `max(CAPE's freespace (50 GB), disk_block_gb (20) + ram_mb)`; refuse below that, warn below
  `disk_warn_gb (50) + ram_mb`. Today **nothing enforces the backend's `disk_block_gb`/`disk_warn_gb`**: they are
  stored settings only (`GET /system/disk` and the `disk` WebSocket frame have no backing code), so the check is new
  work. Without it CAPE drops the dump silently below 50 GB free, and the analysis still reports success; the
  backend should also show "dump not taken" when `memory_dump` was requested and no `memory.dmp` exists.
- **Plugins.** `windows.malware.malfind` and `windows.malware.hollowprocesses` with `--pid` of the analysis's
  processes (and `--dump` into a Tartarus-owned folder for `dump_ref`), `windows.pslist` and `windows.cmdline` once
  for the process table (about 2 s). `netscan`, `psscan` not in v1.
- **Time.** Whole memory step about 5 s per analysis with `--pid` (4 plugins, measured 0.6 to 1 s each on a
  mostly-cached dump), versus 136 to 154 s with CAPE's module.
- **Retention.** A dump is 4.3 GB, so ten analyses are 43 GB, which is already below the 50 GB warn line. Default:
  **delete the dump as soon as the findings are extracted**, with a per-analysis "keep the dump" choice made at
  submit (the checkbox gets two states: findings only / findings + keep the dump) and a one-click delete on the
  artifact. Deletion needs a control-service endpoint (`DELETE /tasks/<id>/memory-dump`) because the backend mount
  is read-only and `tasks/delete` removes the whole task. A kept dump follows the analysis's own retention.
  Disk accounting must count held-open deleted files if CAPE's module is ever used.
- **Tests first** (rule 2): the RSDS parser and the plugin-output mapper are pure functions with the fixtures below;
  the `vol` subprocess call is the only integration test.

## Not verified

- No image build with the Dockerfile change; Volatility was run from a `--target` copy as `root` and (through
  `process.py`) as `cape`, never from the control service or the backend container.
- Plugin times are with the dump largely in the host page cache (30 GB RAM host); a cold file was not measured.
- GUIDs of `win`, `lab1`, `lab5` were not read (same ISO, no updates, and `lab3`/`lab5` are clones); no Windows 10.
- `windows.netstat` (needs `tcpip.pdb`, a second fetch) and any plugin beyond the eight listed.
- A hollowed process that keeps running (the resumed version crashed); other injection kinds (ghosting,
  doppelganging, module stomping, APC, reflective DLL) and real malware, by instruction.
- `dostrings = yes` (not run), a full disk (CAPE's skip is from the source), the HTTP artifact download of a dump,
  an interactive run's dump, a guest with more than 4 GB of RAM, concurrent dumps.
- Why `cape-processor` keeps the dump open; whether `delete_memdump = yes` in CAPE's module frees it.
- Whether a read-only symbol directory works, and a top-level symlinked `symbols` directory.
- The capemon-noise rule rests on one guest and 4 runs.
- **A slip in the brief's rules:** to see whether the cape container is offline I ran `curl` against
  `http://msdl.microsoft.com/` from inside it twice (a GET and a HEAD of the front page, HTTP 200 both). No sample or
  guest data was sent; the PDB itself was fetched on the host as instructed.

## Cleanup

Reverted in the `cape` container: `/opt/vol3-spike`, the `.pth` in the venv, `custom/conf/processing.conf.d/` and
`custom/conf/memory.conf.d/` (both new), `/home/cape/.cache`, `/root/.cache`, the scripts and samples in `/tmp`,
`modules/processing/__pycache__/memory.cpython-312.pyc`, the upload folders and `process-3xx.log` files of my tasks,
and `pefile.py` was never touched. `docker diff` against the one taken at the start differs only by two rotated log
files (`cuckoo.log.2026-10-18`, `process.log.2026-10-18`). `cape` and `cape-processor` were restarted, then the stack
was stopped (as found). Deleted: guest `m8-s3` (disk, memory snapshot, overlay, nvram, definition, guest folder, both
logs: `find / -iname '*m8-s3*'` empty), its self-test analysis 336 (CAPE task 324), tasks 325 to 333, the three sample
binaries from `storage/binaries`, the host `~/.cache/volatility3` (11 MB), the unpacked wheel, the ISF and the wheels.
No dump was kept. `df -h /`: 398 GB free at start and at end; the lowest point was 369 GB (clone + two dumps).

## Re-running the checks

```sh
cd /home/mainskown/Pulpit/Coding/Tartarus && docker compose up -d
S=/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s3
curl -s -XPOST localhost:8080/api/guests/lab3/clone -H 'content-type: application/json' -d '{"name":"m8-s3"}'
# in the cape container: pip install --target /opt/vol3-spike volatility3-2.28.2-py3-none-any.whl, add a .pth
python3 $S/run3.py M-mem $S/memtest3.exe m8-s3 --memory 1 --timeout 45      # dump; --memory 0 for the baseline
docker exec tartarus-cape sh /tmp/vol.sh <dump> -q --offline -r json windows.malware.malfind --pid <pids> --dump
# GUID from the guest while a run is up: POST filepath=C:\Windows\Sysnative\ntoskrnl.exe to http://<guest>:8000/retrieve
# ISF: PYTHONPATH=<unzipped wheel> python3 -m volatility3.framework.symbols.windows.pdbconv -p ntkrnlmp.pdb -g <GUID><AGE> -o out.json
```

Scratch kept (small): `$S/fixtures/` (real plugin output: `vol3-2.28.2-windows.{info,pslist,pstree,cmdline,psscan}.json`,
`...windows.malware.{malfind,hollowprocesses}.json`, `...malfind.pid-filtered.json`, `...netscan.empty.json`,
`cape-report-memory-section-task328.json`, `injected-region-0x1bccc4e0000.bin`; all parse), the drivers
`run3.py`, `summ.py`, `vol.sh`, `volrun*.sh`, `capeapi.py`, the samples `memtest{,2,3}.{c,exe}`, `runs/` (timelines).
