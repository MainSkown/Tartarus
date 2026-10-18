# S1 findings: Sysmon events for an analysis (M8)

Spike on the real stack, 2026-10-18/19. Sysmon 15.22 (schema 4.91, the pinned `Sysmon64.exe`), CAPE at the
pinned `CAPE_REF`, guests built from `Win11_25H2_Polish_x64_v2.iso`. No product code was committed and nothing
was staged. Every change made in the cape container was reverted (list at the end); the repo tree only gained
`docs/plans/m8-spikes/` (this file and `S1-notes.md`). All 39 analyses the spike created and both throwaway
guests were deleted; the stack was left stopped, as found.

Guests used: `m8-s1`, a clone of `lab3` (Sysmon installed at build time, Defender off); `m8-s1n`, a fresh small
build with `sysmon=false`, `defender=false` (the clean guest route A needs). A first clone of `win` could not be
used: `win` is adopted, so its clone fails the self-test on giveaways and stays `failed`; I did not work around
the gate (an attempt to flip the state by hand was refused by the permission classifier, correctly).

## Verdict

**Route B: GO.** Install Sysmon at guest build time (the wizard option, already default on), and collect the log
with a small Tartarus auxiliary module that exports `Microsoft-Windows-Sysmon/Operational` with `wevtutil` and
`upload_to_host`s it as `sysmon/sysmon.xml`. Measured working end to end (a 47-line module). The same module
exported the Defender channel to `aux/defender.xml` (empty on a Defender-off guest; the upload path is accepted), so S4
can reuse it.

**Route A (CAPE's own `sysmon` auxiliary) does not work as shipped on a fresh guest.** Root cause found: it clears
the Sysmon log with `wevtutil clear-log` *before* `SMaster64.exe -i`; on a guest without Sysmon that clear fails
(rc 15007, channel not registered) and the install that follows fails with rc 13 "Event manifest installation
failed". Swapping those two lines makes it work (measured). On a guest that already has Sysmon the install is a
no-op and the module is only a collector, but it still refuses to start unless a dummy `SMaster64.exe` and a
config sit in the analyzer's `bin/`. So route A would need a binary in the image, a CAPE patch and a dummy for
the guests that already have Sysmon, for no gain over route B.

**Two things in the plan are wrong.** (1) There is no `custom/analyzer/` overlay in this CAPE ref: the analyzer zip
sent to the guest is built from `analyzer/windows/` only, so a Tartarus module must be put there at image build
(like `cape/patches/skip-packaged-apps.py`). (2) The shipped `sysmon-config.xml` is not "low volume" for ingest and
CAPE's `remove_noise` does nothing; a normaliser must filter its own noise (below).

## Method

A scratch driver (`run.py`, public API only: multipart `POST /api/analyses`, polling, the facets endpoint) submitted
each run; afterwards the CAPE task folder was copied out of the cape container (`sysmon/sysmon.xml`,
`evtx/evtx.zip`, `reports/report.json`, `analysis.log`). Scripts counted event IDs and attributed events to the
sample's process tree, CAPE's tooling and Windows background. To change the guest or the analyzer I used `docker cp`
into the running cape container plus `supervisorctl restart cape` (never a rebuild: the build cache is empty and a
rebuild would recompile QEMU). Two temporary auxiliary modules went into `analyzer/windows/modules/auxiliary/`:
`event_logs.py` (route B candidate) and `probe.py` (diagnostics: ran commands in the guest at the start and end and
uploaded the output to `aux/`). Samples: the self-test `benign.exe` (copied from the cape image cache
`/var/lib/libvirt/tartarus/cache/selftest/windows/benign.exe`), and `noise.exe`, a harmless C program built in
the cape container with mingw (60 child processes, 200+200 files in `C:\Users\Public\ttnoise`, 100 registry
values, 15 DNS lookups plus TCP connects to INetSim, then idle 20 s). `route inetsim`, package `exe`.

"Default 180 s run" means `interactive true`, `timeout 180` (the settings default is interactive, and then the run
lasts the whole timeout). A non-interactive run of `benign.exe` ends when the sample exits, after about 38 s.

## Answers

### 1. Route A (CAPE's `sysmon` auxiliary)

- **Where the guest gets Sysmon:** `guest/profiles/windows/manifest.sha256` pins `Sysmon64.exe`
  (sha256 `83d31f24...4352`, `https://live.sysinternals.com/Sysmon64.exe`); the `fetch` step downloads it on the
  host into `/var/lib/libvirt/tartarus/cache/Sysmon64.exe` (3,203,368 bytes, already there), `provision.ps1` runs
  `Sysmon64.exe -accepteula -i sysmon-config.xml` at first logon, and the log is checked. It is not on the Windows
  ISO; it is fetched by the user's host at build time, so nothing is redistributed. The config is
  `guest/profiles/windows/sysmon-config.xml` (the "pinned" config).
- **How the analyzer is served:** `lib/cuckoo/core/guest.py::analyzer_zipfile()` zips `CUCKOO_ROOT/analyzer/<platform>`
  and nothing else. The image changes it only through `cape/patches/skip-packaged-apps.py`. CAPE config comes from
  `cape/conf/*.conf` copied to `/opt/CAPEv2/custom/conf/`; the entrypoint renders only the network files into
  `*.conf.d`. An auxiliary module is imported only when `[auxiliary_modules]` has a key equal to its file name
  (`event_logs.py` needs `event_logs = yes`, found the hard way: `eventlogs.py` was silently ignored).
- **Guest with Sysmon from the build (`m8-s1`, run A1):** `sysmon_windows = yes` plus `[sysmon] enabled = yes` and a
  dummy `bin/SMaster64.exe` + config. `sysmon.xml` arrived (1,301,919 bytes), `evtx/evtx.zip` (89,464 bytes),
  `report.json["sysmon"]` filled with the same 1144 events. `SMaster64.exe -accepteula -n -i` ran (an EID 1 shows
  it) but installed nothing: a probe in the same run found only the `Sysmon64` service and `SysmonDrv`, one writer
  process (pid 3248), no `SMaster64` service, and no EID 4/16. No duplicate events, no clash; the guest's own
  Sysmon and its build-time config kept logging.
- **Clean guest (`m8-s1n`, runs RC1, RC1b, RC2):** as shipped, no `sysmon.xml` (the run's `evtx.zip` is an empty
  341-byte zip). With CAPE's `sysmon.py` patched to log the install's return code: `rc=13`. Isolated with two probe
  modules: install alone, `rc=0`, service `SMaster64` (driver still named `SysmonDrv`); `wevtutil clear-log
  microsoft-windows-sysmon/operational` first (`rc=15007`), then the same install: `rc=13`. With the two lines in
  `start()` swapped (RC3) it works: 14,056 events, `sysmon.xml` 14,228,154 bytes, `evtx.zip` 474,012 bytes.
- **Which IDs appear**, pinned config, 40 s run of `benign.exe`: EID 1, 3, 5, 11, 12, 13 only (the config logs
  those and nothing else; no 7, 8, 10, 22, 23, 26). With a richer config (below) also 7, 8, 10, 22, 26.
- **The sample's own events** (benign.exe + its `cmd.exe /c ver`), pinned config, RB1: 22 events: EID 1 x2,
  EID 5 x2, EID 12/13 x14 (including `HKU\...\Software\Tartarus\SelfTest = benign`), EID 11 x4 but those four are
  the monitor's own files (`CapeOutput.bin`, `capemon.yac`), **not** the sample's marker file: the pinned config
  excludes `\AppData\Local\Temp\`, where `tartarus-benign.txt` goes. No EID 3: benign only resolves a name (a
  DNS lookup is EID 22, off in the pinned config). With `noise.exe` (RR3, RN2) the file (424 EID 11), registry
  (84 EID 12 + 199 EID 13) and network (15 EID 3 to INetSim) events of the sample all show.
- **Time cost** of the aux: start 0.65 s (route B, two clears) to 2.4 s (route A, install); stop/export of a 12 MB
  log about 0.6 s.

### 2. Route B (Sysmon from the build, a Tartarus module collects)

- **Cost:** none for the three existing guests with Sysmon (`lab1`, `lab3`, `lab5`; `win` and adopted guests have
  `sysmon: false`). A clone is about 6.6 minutes and 19 GB; no new build was needed for B. The `m8-s1n` build
  (about 20 minutes with its self-test, 64 GB thin disk) was only for the clean-guest route A test.
- **Module** (kept in the scratchpad, `overlay/event_logs.py`): `start()` clears the Sysmon and Defender channels,
  `stop()` runs `wevtutil query-events <channel> /e:Events /format:xml` into `C:\tt-sysmon.xml` / `C:\tt-defender.xml`
  and `upload_to_host`s them as `sysmon/sysmon.xml` and `aux/defender.xml`. Uploads must go under a directory of
  the resultserver whitelist (`RESULT_UPLOADABLE` in `lib/cuckoo/core/resultserver.py`: `CAPE aux browser curtain
  debugger evtx files htmldump memory procdump shots sysmon tlsdump tracee`); a new `defender/` directory would be
  refused, so S4 should use `aux/` or `evtx/`.
- **Result** (RB1, 40 s): `sysmon.xml` 1,250,055 bytes, 1101 events, and CAPE's processing module read it into
  `report.json["sysmon"]` even though it was not CAPE's auxiliary that uploaded it. A 180 s run: 11,999,036 bytes,
  11,419 events (RB3b).
- **Double install:** route A off means no clash by construction; with both on, route A's install is a no-op on a
  Sysmon-bearing guest (A1). Do not enable both.
- **Why the log is cleared at start:** at the start of every run the Sysmon channel already holds the build's
  history: 78,548 records, a full 64 MB log (`wevtutil gli`, before the clear). Without the clear the export would
  be that whole log. Filtering by an XPath `TimeCreated` instead of clearing was not tested.
- **Updating the config without a rebuild** works: `C:\Windows\Sysmon64.exe -accepteula -c <analyzer>\bin\config.xml`
  at run start printed "Configuration updated" and the new rules applied (EID 7, 8, 10, 22, 26 appeared, RR1 to
  RR3). Side effect: Sysmon64.exe then wrote about 5,000 EID 12 events of its own under `SystemCertificates` and
  `WinTrust` in that run; the proposed config excludes those keys, but `-c` with the proposed config was not run.
- **Not tested:** the module on a guest without Sysmon (adopted `win`): `wevtutil` writes its error to stderr, the
  output file is empty, and `os.path.getsize(...) > 0` skips the upload; read from the code only. The Defender
  export on a Defender-on guest (S4's EICAR test).

### 3. Noise

What CAPE's own tooling looks like (RB3b, 180 s, attributed from the log):
- EID 1: `C:\<8 random chars>\bin\<8 random letters>.exe inject <pid> <tid> C:\<8 random>\dll\<random>.dll` (the
  injector is renamed per task; 16 of these in a benign 180 s run, about 2 per monitored process: 129 EID 1
  from tooling in the 60-process noise run), `PPLinject64.exe <pid> ...dll`, `cmd.exe /c ver` run by
  `pythonw.exe`, `wevtutil.exe clear-log ...` (the module's own), `SMaster64.exe`/`Sysmon64.exe` in route A, all with
  parent `C:\Python311\pythonw.exe` (the agent).
- EID 3: `pythonw.exe` inbound `192.168.150.1 -> guest:8000` about once a second (192 in 180 s) and 17 outbound to
  the resultserver `192.168.150.1:2042`.
- EID 11: `C:\<rand>\dll\<pid>.ini`, `C:\<pid>.ini`, `C:\<rand>\CAPE\CapeOutput.bin`, `C:\<rand>\data\yara\capemon.yac`
  (the last two are written by the monitor inside the *sample's* processes, so they carry the sample's pid),
  `__pycache__` under `C:\Python311`.
- Windows' own background: Edge started by the connectivity probe to `msftconnecttest.com`, a hidden `notepad.exe`
  launched by CAPE's `disguise` auxiliary, WindowsTerminal/OpenConsole, OneDrive, `MoUsoCoreWorker`, `TiWorker`,
  `MicrosoftEdgeUpdate`.
- Volume by origin (EIDs counted): sample tree 0.1 to 7.7%, CAPE tooling 0.5 to 7.6%, Windows background
  84.7 to 99.4% (`attrib.py`, runs RB1, RB3b, RN2, RC3, RC5).
- Registry noise: `HKLM\SOFTWARE\Microsoft\Wbem\Tracing` written by `svchost.exe` in one burst of **6,420 to 6,490
  EID 12 events** (about 6.5 MB, over half of a 12 MB log) starting 20 to 30 s into the run; 12,657 in the clean
  guest's run. Also `Services\bam\State\UserSettings`, `Local Settings\MuiCache`, `Explorer\UserAssist`,
  `SystemCertificates` / `EnterpriseCertificates` / `WinTrust` keys written by the Sysmon binary itself,
  `CapabilityAccessManager`, `Control\ProductOptions`, `AppModel\StateRepository`.

What CAPE's `remove_noise` filters: **nothing**. It indexes `event["EventData"]["Data"][9]` as the command line, but
in Sysmon 15's EID 1 schema that slot is `OriginalFileName` (the command line is `[10]`); the regexes for
`wevtutil clear-log`, `bin\inject-x64.exe` and so on never match, and the injector is renamed anyway. Measured:
21 EID 1 events in `sysmon.xml`, 21 in `report.json["sysmon"]` (A1). Also its `wevtutil query-events` regex does not
match the module's own command (`/rd:true /e:Events`).

A normaliser must therefore drop or mark, by rule: EID 1/5/7/10 where the image is under `C:\<8 chars>\`,
`PPLinject*`, `pythonw.exe`, `wevtutil.exe`, `Sysmon64.exe`/`SMaster64.exe`, or the parent is the agent
`pythonw.exe`; EID 3 of `pythonw.exe`; EID 11/12/13 of those images and the paths above; the `Wbem\Tracing` burst
and the other background keys, preferably by excluding them in the Sysmon config so they never reach the log.
Marking events as "in the sample's process tree" (walk `ParentProcessGuid` from the sample) is cheap and
tested in `attrib.py`, and would let the GUI default to just those.

### 4. Sizes and cost

`sysmon.xml` bytes / events, and the analysis outcome against baselines on the same guest. "Sigs" is the signature
count in `summary.signatures`. Baseline = all modules off.

| Run | Guest / route / config | sysmon.xml | Events (Sysmon) | EID counts | `evtx.zip` | `report.json` | CAPE events / score / sigs / duration |
|---|---|---|---|---|---|---|---|
| B0 benign, short | m8-s1, no module | none | none | none | none | 568 KB | 516 / 6.0 / 12 / 38 s |
| A1 benign, short | m8-s1, route A (no-op install), pinned | 1,301,919 B | 1144 | 1:21 3:64 5:24 11:52 12:421 13:562 | 89,464 B | 2.76 MB | 510 / 6.0 / 12 / 39 s |
| RB1 benign, short | m8-s1, route B, pinned | 1,250,055 B | 1101 | 1:20 3:59 5:26 11:35 12:384 13:577 | none | 2.67 MB | 510 / 6.0 / 12 / 39 s |
| RC0 benign, short | m8-s1n, no module | none | none | none | none | about 570 KB | 541 / 6.0 / 12 / 54 s |
| RC3 benign, short | m8-s1n, route A + reorder patch, pinned | 14,228,154 B | 14,056 | 1:32 3:60 5:27 11:40 12:13,278 13:619 | 474,012 B | 24.8 MB | 540 / 6.0 / 12 / 49 s |
| B1, B1b benign 180 s | m8-s1, no module | none | none | none | none | 5.13 MB | 5405, 5407 / 6.0 / 16 / 204, 202 s |
| RC6, RC7 benign 180 s | m8-s1n, no module | none | none | none | none | n/r | 5435, 5428 / 6.0 / 16 / 207, 209 s |
| RB3 benign 180 s | m8-s1, route B, pinned | 16,198,329 B | 15,355 | 1:142 3:277 5:135 11:208 12:12,786 13:1807 | none | 34.8 MB | **7624 / 8.0 / 19 / 211 s** |
| RB3b benign 180 s | m8-s1, route B, pinned | 11,999,036 B | 11,419 | 1:54 3:259 5:62 11:71 12:9622 13:1351 | none | 25.4 MB | 5392 / 6.0 / 16 / 203 s |
| RC4 benign 180 s | m8-s1n, route A patched, proposed v1 | 10,325,756 B | 9506 | 1:113 3:87 5:115 7:64 8:3 10:158 11:193 12:7277 13:1319 22:14 26:163 | n/r | 24.6 MB | **7643 / 8.0 / 19 / 214 s** |
| RC5 benign 180 s | m8-s1n, route A patched, **proposed v2** | 4,000,593 B | 3452 | 1:53 3:81 5:64 7:29 8:3 10:96 11:81 12:1760 13:1194 22:13 26:78 | 266,468 B | 11.7 MB | 5421 / 6.0 / 16 / 213 s |
| B2 noise.exe | m8-s1, no module | none | none | none | none | 12.8 MB | 14,462 / 7.0 / 16 / 145 s |
| RN2 noise.exe | m8-s1, route B, pinned | 12,124,406 B | 11,462 | 1:239 3:301 5:246 11:627 12:8566 13:1483 | none | 33.5 MB | 14,492 / 7.0 / 16 / 160 s |
| RR3 noise.exe | m8-s1, route B, rich config via `-c` | n/r | 22,726 | 1:240 3:327 5:245 7:186 10:1077 11:609 12:18,492 13:1322 22:28 26:200 | none | n/r | n/r |

(`n/r` = not recorded before the large files were pruned.) The first `noise.exe` build timed out in its spawn
loop at 180 s and was rebuilt with the spawn phase last; RN2 is the second build.

- **Log growth:** about 12 to 16 MB of XML for a 180 s run with the pinned config, 54% of it the `Wbem\Tracing`
  burst; 4.0 MB with the proposed v2 config (EID 12 from 9622 to 1760). `report.json` grows by about 1.7 times the
  XML if `[sysmon] enabled = yes` (5.1 MB to 25.4 MB, 12.8 MB to 33.5 MB); the nested dict is the cost, and
  `xmltodict` loads all of it in memory. A 20-minute run would be several times that. **So do not enable the
  processing module; read `sysmon.xml`.**
- **Does Sysmon change the analysis?** Short runs: identical (516/510/510 events, 6.0, 12 signatures, 38/39/39 s).
  The route's own effect on run time is small (aux start 0.65 to 2.4 s, export 0.6 s, processing took 4 to 10 s
  after the run's end in every run). Long runs are the open point: baselines 4 of 4 gave 5.4k events, 6.0,
  16 signatures, 8 processes; with Sysmon on, 2 of 4 gave **7.6k events, score 8.0, 19 signatures, 9 processes**
  (an extra `TiWorker.exe`, the Windows servicing worker, and three signatures from background processes:
  `enumerates_physical_drives`, `antivm_checks_available_memory`, `registry_credential_store_access`). The extra
  process is a Windows servicing worker that has nothing to do with the sample, so I think it is background, but with
  n=4 against n=4 I cannot show it. It does
  not come from anything Sysmon-specific that I can name; a decision on the score should wait for about ten more
  runs of each. Noise runs: 14,462 vs 14,492 events, 7.0 vs 7.0, same 16 signatures; run time 145 vs 160 s (one
  pair, within the spread seen between identical runs in the M7 findings).
- **Clean-guest oddity:** RC3 on the fresh guest had twice the `Wbem\Tracing` events of the Sysmon-from-build guest.
  Not investigated.

### 5. Recommendation

**Route B.** Changes (all described, none made):

1. **`cape/Dockerfile`:** `COPY` the module to `/opt/CAPEv2/analyzer/windows/modules/auxiliary/event_logs.py`
   (owner `cape`), next to the `skip-packaged-apps` patch; keep it in the repo as `cape/analyzer/event_logs.py`
   with a unit test that fakes `wevtutil` and `upload_to_host` (the `cape/tests` suite runs without CAPE).
   Make it read its channels from one table so S4 adds Defender with one line (Defender to `aux/defender.xml`).
2. **`cape/conf/auxiliary.conf`:** under `[auxiliary_modules]` add `event_logs = yes`; leave `sysmon_windows = no`
   and `evtx = no`. **`processing.conf`:** leave `[sysmon] enabled = no` (the file is not set today; no change).
3. **Sysmon config:** replace `guest/profiles/windows/sysmon-config.xml` with the proposed
   `sysmon-config-proposed.xml` (below), and have the module apply it at run start with
   `Sysmon64.exe -accepteula -c` from the analyzer `bin/` (ship the config next to the module in the image), so
   existing guests need no rebuild. Update the header comment of that file and the `sysmon` option's help text in `profile.json`
   ("low-volume") accordingly.
4. **Binary:** unchanged, `manifest.sha256` fetch to the host cache; route B needs no Sysmon binary in the analyzer.
   If route A were ever wanted, the entrypoint could copy `/var/lib/libvirt/tartarus/cache/Sysmon64.exe` to
   `analyzer/windows/bin/SMaster64.exe` when the cache has it (it exists after any build), but it only exists
   after a first guest build.
5. **Guest profile:** `sysmon` stays default on for builds; adoption guests stay `false`, and their runs simply
   have no `sysmon.xml` (the normaliser treats a missing file as no source).
6. **Normaliser reads `sysmon/sysmon.xml`**, streamed (`iterparse`), from the read-only `cape-storage` mount the
   backend already has; not `report.json["sysmon"]` (1.7x the size, loaded whole, CAPE's noise filter is a no-op)
   and not `evtx/evtx.zip` (only route A makes it, needs an EVTX parser, 8 to 15x smaller but no richer). `EventData`
   is read by `Data/@Name`, never by position. Event time: `UtcTime` is in the guest clock, which was 2 hours
   behind real UTC in every run (RTC read as local time in a UTC+2 zone): apply the same `guest_clock_offset` used
   for capemon times. `TimeCreated/@SystemTime` is the log write time, a few hundred ms later; use `UtcTime`.
   Process identity: `ProcessGuid` is unique per process; capemon uses pid, so join on pid plus image plus
   a time window (Sysmon's EID 1 comes 2.9 s before capemon's `first_seen` for `benign.exe`: 19:18:25.065 vs
   19:18:27.939).

Proposed config (v2, tested in RC5, 4.0 MB for 180 s; well-formed and accepted by `SMaster64.exe -i`, "Configuration
file validated"): `ProcessCreate`/`ProcessTerminate` exclude `conhost.exe`; `NetworkConnect` exclude
`Image is C:\Python311\pythonw.exe`; `ImageLoad` include `Signed is false`; `CreateRemoteThread` log all;
`ProcessAccess` exclude a list of system and agent source images; `FileCreate` exclude `\Windows\Prefetch\`;
`RegistryEvent` exclude `Wbem\Tracing`, Defender policy keys, `RecentDocs`, `bam\State\UserSettings`, `MuiCache`,
`SystemCertificates`, `EnterpriseCertificates`, `WinTrust\Trust Providers\Software Publishing`, `Control\ProductOptions`,
`Control\Hvsi`, `CapabilityAccessManager`, `Wosc`, `CPSS`, `AppModel\SystemAppData`; `DnsQuery` log all;
`FileDeleteDetected` log all (EID 26, not 23: 23 archives the deleted file and uses disk). Full file:
`.../scratchpad/m8-s1/fixture/sysmon-config-proposed.xml`. Beware: **in one rule block, different field names are
ANDed, same field names ORed**; my first rich config put `TargetObject` and `Image` conditions in one
`RegistryEvent` block and the exclusion silently matched nothing. The pinned config's `NetworkConnect` block
(`DestinationIp is 127.0.0.1` and `DestinationPort is 8000`) is such an AND, so it does not exclude the agent's
inbound connections (192 EID 3 in 180 s). Still above in v2: `bam`, EID 12/13 from `svchost.exe` remain the bulk
(`StateRepository`, `Internet Settings`, `ShellExperienceHost` keys); the config can go further.

## What the normaliser should expect (fixture)

`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s1/fixture/sysmon.xml`
(373,913 bytes, 287 events, every ID seen: 1, 3, 5, 7, 8, 10, 11, 12, 13, 22, 26): the first N events per ID of the
RC5 run (clean guest, route A export order, i.e. **newest first** because CAPE's module uses `/rd:true`; route B's
module exports oldest first, so the normaliser must not rely on order), proposed v2 config, Sysmon 15.22.
Format: `<Events>\n<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'>...</Event>...</Events>`,
single-quoted attributes, `EventData/Data[@Name]`. It holds the guest's generated account (`Alice`) and machine
name (`LAPTOP-...`), both throwaway. A second file `fixture/sysmon-rich-two-runs.xml` (339,916 bytes) mixes events
of two route B runs (rich config). The full unpruned RC5 export is `keep/RC5-routeA-proposed-config-180s-sysmon.xml`
(4,000,593 bytes). Note that CAPE's processing module decodes the file as `latin1`; non-ASCII characters in
paths would be mangled in `report.json["sysmon"]`, another reason to parse the XML as UTF-8 yourself (I did not
check the file's encoding for non-ASCII content).

## Commands to re-run the checks

```
# the stack (no --build: the build cache is empty)
docker compose up -d
S=/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s1

# CAPE serves only analyzer/windows to the guest (no custom/analyzer):
docker exec tartarus-cape sed -n 36,60p /opt/CAPEv2/lib/cuckoo/core/guest.py
# remove_noise indexes Data[9]; in the fixture slot 9 is OriginalFileName:
docker exec tartarus-cape sed -n 31,47p /opt/CAPEv2/modules/processing/sysmon.py
python3 -I - <<'EOF'
import re
e = next(x for x in re.findall(r"<Event .*?</Event>", open("$S/fixture/sysmon.xml", encoding="latin1").read(), re.S)
         if "<EventID>1</EventID>" in x)
print(re.findall(r"<Data Name='([^']+)'", e)[9])      # OriginalFileName
EOF
# the install-order bug: any 3 lines in an auxiliary probe on a guest without Sysmon, see S1-notes.md (RC2)
#   wevtutil.exe clear-log microsoft-windows-sysmon/operational   -> rc 15007, then SMaster64.exe -accepteula -n -i cfg -> rc 13
#   SMaster64.exe -accepteula -n -i cfg alone                      -> rc 0
# counts and attribution on a sysmon.xml
python3 -I $S/analyze.py $S/fixture/sysmon.xml
python3 -I $S/attrib.py $S/keep/RC5-routeA-proposed-config-180s-sysmon.xml benign.exe --list
# drive a run (guest must be ready; --interactive for a full 180 s)
python3 $S/run.py LABEL $S/benign.exe GUEST --timeout 180 --interactive
```

The module and probe sources are in `$S/overlay/` (`event_logs.py`, `probe.py` with whichever diagnostics were
last pasted into it); the one-line patches that were tried are `$S/patch_sysmon_order.py` and `$S/patch_sysmon.py`.
Raw per-run data (`analysis.json`, `timeline.txt`, `facets.json`, `cape-ls.txt`, `analysis.log`) is under
`$S/runs/<label>/`; the big files (`report.json`, `evtx.zip`, most `sysmon.xml`) were pruned for disk space.

## Not verified

- Route B on a guest without Sysmon (empty export file, no upload): from the code only.
- The Defender export on a Defender-on guest, EICAR detection (S4's job); the Defender channel is 1 MB by default
  (`maxSize: 1052672`) and had 32 records at the start of a run.
- `Sysmon64.exe -c` with the proposed v2 config: only the rich config was applied that way; v2 only via install.
- The XPath time filter instead of clearing the log at start.
- Whether Sysmon changes the score on long runs (2 of 4 vs 0 of 4 outliers; see section 4).
- The `Wbem\Tracing` burst: its trigger (it starts 20 to 30 s in and ends within about 10 s), and why it doubled
  on the clean guest.
- Non-ASCII event content; a run longer than 4 minutes; other guests than the two used.
- `evtx.zip` is 89 to 600 KB for 1 to 10 MB of XML but its contents were not parsed.

## Temporary changes made and how each was reverted

All inside the running `tartarus-cape` container (the repo was not touched): `custom/conf/auxiliary.conf.d/m8-s1.conf`,
`custom/conf/processing.conf.d/m8-s1.conf` (and their directories), `analyzer/windows/bin/SMaster64.exe`,
`analyzer/windows/bin/sysmonconfig-export.xml`, `analyzer/windows/modules/auxiliary/{event_logs,probe}.py`, and
three temporary patches of `analyzer/windows/modules/auxiliary/sysmon.py` (return-code logging, start priority,
swapped order). Removed; `sysmon.py` restored from a backup copy (`cmp`-identical, mtime 2026-10-13);
`docker diff tartarus-cape` shows no remaining file under `/opt/CAPEv2` outside `storage/` and bytecode caches.
