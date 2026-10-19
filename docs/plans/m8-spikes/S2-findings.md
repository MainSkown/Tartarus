# S2 findings: ETW events for an analysis (M8)

Spike on the real stack, 2026-10-19. Guest `m8-s2`, a throwaway clone of `lab3` (Windows 11 25H2, build 10.0.26200,
Defender off, Sysmon on, pl-PL); two runs on `lab5` (Defender on) for AMSI. CAPE at the pinned `CAPE_REF`.
No product code was committed and nothing was staged; the repo only gained `docs/plans/m8-spikes/S2-notes.md` and
this file. Every change in the `cape` container was reverted (list at the end), the 15 analyses (ids 337 to 351) and
the guest were deleted, and the stack was stopped as found.

## Verdict

**Drop ETW from v1 and record it.** It can be made to run, but none of the four auxiliaries adds enough over what the
plan already ships:

- **It runs.** `pywintrace` 0.2.0 is one pure-Python wheel (35 KB, no dependencies), imports and traces fine under the
  guest's **32-bit** Python 3.11 on 64-bit Windows, installs offline with `pip install --no-index --no-deps`, and the
  four modules start, stop and upload for a normal run, a CAPE-timeout run and an early `POST /finish`. Enabling them
  changed neither score, signatures nor run length (two runs each).
- **But as shipped only one of the four gives usable data**: `wmi_etw` (with a process id and the operation text).
  `dns_etw` records the DNS Client **service's** pid (svchost), never the asking process, and drops the answers;
  `network_etw` records **nothing** under the INetSim route (INetSim answers on `192.168.150.1`, the same address
  the module filters out as "the host"); `amsi_etw` produced **zero events** on both a Defender-off and a Defender-on
  guest, and so did an independent `logman` trace of the AMSI provider.
- **What the two network modules could give, Sysmon (Wave A) already gives**, with more fields: Sysmon EID 22 (DNS,
  with pid, image, status, answers) and EID 3 (connections). **WMI persistence** (filter, consumer with its command
  line, binding, Created/Deleted) is Sysmon EID 19/20/21, measured here with a one-line config rule. What only
  `wmi_etw` adds is arbitrary WMI operations that capemon does not hook (`PutInstance`, `DeleteInstance`,
  `ExecMethod`) with the client pid. That is real but small; if the user wants it, it is a cheap later addition
  (section 4), not a v1 item.

## Questions

### 1. Installing `pywintrace` in an offline guest

| Question | Answer (evidence) |
|---|---|
| What is it? | PyPI has **only 0.1.1 and 0.2.0**; 0.2.0 is `pywintrace-0.2.0-py3-none-any.whl`, 35,289 bytes, sha256 `f3a8e71794ca23cbdaf8a1b0cfb3461540da8d3812fbd8531ab3edaf0657cc56`, URL `https://files.pythonhosted.org/packages/a4/ea/975a137b05faef08389c41cb51c346697bd9bbf35c51b1e52cda728932ba/pywintrace-0.2.0-py3-none-any.whl`. Pure Python (`ctypes`), `Requires-Dist` empty, nothing else to fetch. Installed it is 221 KB. (The host has no `pip`; I read the PyPI JSON API and `curl`ed the wheel on the host: two host requests. `pip download --platform` is moot for a `none-any` wheel.) |
| 32-bit Python? | **Works.** `import etw` and a live `ETW_DNS` session under `C:\Python311\python.exe` (32-bit, WoW64) delivered correctly parsed events from 64-bit processes (pointer-sized fields such as `QueryBlob 0x172171257E0` decode right). No second, 64-bit Python is needed, so there is nothing to clash with the agent or capemon. |
| Install with nothing downloaded in the guest | `pip install --no-index --no-deps --disable-pip-version-check --no-warn-script-location <wheel>`, wheel pushed with the agent's `/store`. Done on a running clone through the agent (`/store` + `/execute`, S1/S4 driver style). |
| Into an existing clone, then re-snapshot? | **Yes, by hand**: revert to `tartarus-clean`, install, then `virsh snapshot-delete --metadata` and `virsh snapshot-create-as ... --memspec ...,snapshot=external --diskspec sda,...` under the same name. A later analysis (E2) ran from that snapshot with the wheel present and the analyzer overlay removed. There is **no supported path** for this in Tartarus (the `snapshot` step is idempotent and does nothing once the snapshot exists), so for existing guests it is a manual surgery. |
| At build time | One line in `guest/profiles/windows/manifest.sha256` (the `fetch` step downloads it on the host into the cache; `steps/install` copies **every** manifest entry into the media payload) and one step in `provision.ps1` next to "install Pillow from the offline wheel": `python.exe -m pip install --no-index --no-deps <wheel>`. A test in `cape/tests/test_windows_profile.py` would pin the wheel name like the existing `pillow-` one. |
| **Cheaper: no guest change at all** | The `etw/` package from the wheel copied to `/opt/CAPEv2/analyzer/windows/etw/` is imported by the analyzer (it runs from the analyzer folder). Measured on a guest **without** the wheel (E1) and on `lab5` (A1, A2): `HAVE_ETW` true, modules started. It works for every existing and adopted guest, needs no snapshot, and lives in the `cape` image (a `COPY` in `cape/Dockerfile`, like `skip-packaged-apps.py`). This is the route to use if ETW is ever shipped. |
| Guest self-test with the wheel | `selftest/guest-facts.ps1` on the wheel-installed guest: 34 lines, **no `GIVEAWAY` line**, `python.version_bits=3.11.9 32`. The full backend self-test (analysis + facts through the API) was not re-run on the wheel guest. The wheel leaves `site-packages\etw`, `pywintrace-0.2.0.dist-info` and `Scripts\list_providers.py`, `Scripts\parse_cs.py`. |

### 2. What the four modules produced

Sample `etw3.exe` (mingw, harmless, source `etw3.c` in the scratchpad): `getaddrinfo` and `gethostbyname` lookups,
an HTTP GET to the resolved INetSim address, a PowerShell child that runs a WMI query and creates and removes a
permanent event subscription, a PowerShell child with the standard AMSI test string, `Invoke-Expression` and an
`Assembly.Load(byte[])`, then `logman query -ets`. Plus `benign.exe`. Route `inetsim`, package `exe`, 60 s timeout.
Modules enabled by a temporary `custom/conf/auxiliary.conf.d/m8-s2.conf` (`dns_etw`, `network_etw`, `wmi_etw`,
`amsi_etw` under `[auxiliary_modules]`, which is where CAPE copies them into the task's `analysis.conf`) and
`processing.conf.d` (`[amsi_etw]`, `[network_etw]`). There is no `dns` or `wmi` processing module; `network_etw`
reads `aux/dns_etw.json`.

| Module | Starts? | File on the host | Content | Verdict |
|---|---|---|---|---|
| `dns_etw` | yes | `aux/dns_etw.json`, NDJSON | 0.4 to 2 KB per run (stock), keys `QueryType` (`Query`/`Response`), `ProcessId`, `ThreadId`, `QueryName`, `DNS Server` | **Wrong pid**: events 3010/3020 are written by the DNS Client service, so `ProcessId` is always `800` (svchost). The real client pid (`ClientPID`) and the answers (`QueryResults`) are in the raw event but dropped by CAPE's `write_to_log`. Useless as shipped. |
| `network_etw` | yes | `aux/network_etw.json`, NDJSON | **1 record** in every stock run: a UDP/138 broadcast from pid 4 | **Empty under INetSim**: `filter_ips` holds the host IP `192.168.150.1`, and INetSim answers DNS with that same address, so every connection to the simulated internet (and the DNS server) is filtered. Fields come out as strings (`"pid": "4"`, `"dst_port": "138"`). |
| `wmi_etw` | yes | `aux/wmi_etw.json`, NDJSON | 21 KB (benign, 45 s) to 750 KB (etw3, 90 s) | **Works**, shape in section 4. About 80% of the records are Windows' own WMI chatter (events 100, 50, 13). Contains the sample's queries, `PutInstance`/`DeleteInstance` on `root/subscription` and a 5861 for the binding, each with `ClientProcessId`. |
| `amsi_etw` | yes ("Starting AMSI_ETW") | none (the module logs "No AMSI events were collected") | 0 events | **Nothing** on `m8-s2` (E1, E2, ES1, ES2), nothing on `lab5` with Defender on (A1, `amsi.dll` loaded in the PowerShell child). An independent `logman create trace -p {2A576B87-09A7-520E-C21A-4942F0271D67} 0xffffffffffffffff 0xff -ets` on `lab5` while AMSI blocked a script ("contains malicious content") gave an 8 KB `.etl` with only the header. Cause not isolated; I cannot make this build emit them. |

Overlap with capemon and the pcap (same runs, Tartarus API):

| Information | Already in | `etw` adds |
|---|---|---|
| DNS names asked | pcap (`network.dns`), capemon `getaddrinfo` (pid) | Patched DNS ETW (below) attributes `gethostbyname` lookups to the asking pid and gives status and answers; in E1 capemon/pcap left `etw-dns-two.example.org` with no process and no answers |
| TCP/UDP connections | pcap flows (Tartarus attributes them to the capemon pid: `etw.exe` flows had a process), capemon `connect` | Patched Kernel-Network ETW (below): a pid for connections of processes capemon is not in. DNS UDP/53 shows pid 800 (the service sends it), so no gain there |
| WMI query text | capemon `WMI_ExecQueryAsync` (`Query`), `WMI_GetObject(Async)`, `WbemLocator_ConnectServer` for hooked processes | `PutInstance`, `DeleteInstance` (subscription creation and removal), 5861 binding, the provider that served it, the user |
| AMSI scanned content | nothing | nothing arrived |

Two patched copies of the modules (kept in `fixture/`, **not** CAPE's) show what a Tartarus-owned version would give:
- `dns_etw` with event ids 3006 and 3008, which the **client** process writes (so the header `ProcessId` is the
  asking process): `{event_id, pid, tid, timestamp, query_name, query_type, status, results}`; for `etw3.exe`:
  `pid 1136 etw-dns-one.example.com 1 status 0 192.168.150.1;`. (3010/3020 carry `ClientPID` and `QueryResults`
  as well, but the service's header pid.)
- `network_etw` without the host-IP filter (keep the ports 8000 and 2042 filter, which are the agent and the
  resultserver): 16 records in a 90 s run, `tcp_connect_v4` with `pid` 1136 to `192.168.150.1:80`.

Side effect found on the way: with the `network_etw` **processing** module enabled, CAPE's own
`report.json["network"]["dns"][*]["processes"]` gets `{"pid": "800", "source": "dns_etw"}` for every lookup. The
Tartarus normaliser does not read that field, but it is wrong data in the report; leave the processing module off.

### 3. Cost and side effects

Two runs each ("on" = all four stock modules and the two processing modules). Baseline = none of them. Same guest,
same snapshot state. `run` = agent start to finish; `p+i` = processing plus ingest.

| Sample | Config | Events | Score | Signatures | Processes | run | p+i | `report.json` | `aux/*etw*` bytes (wmi / dns / net) |
|---|---|---|---|---|---|---|---|---|---|
| benign.exe | off (B3, B4) | 505, 501 | 6.0, 6.0 | 12, 12 (same set) | 2 | 51, 45 s | 7, 6 s | 566, 562 KB | none |
| benign.exe | on (EB1, EB2) | 504, 501 | 6.0, 6.0 | 12, 12 (same set) | 2 | 43, 45 s | 5, 6 s | 573, 569 KB | 21,312 / 472 / 248 |
| etw3.exe | off (B1, B2) | 15,379, 10,910 | 7.0, 7.0 | 42, 38 | 7, 5 | 92, 90 s | 10, 9 s | 15.7, 11.2 MB | none |
| etw3.exe | on (ES1, ES2) | 10,983, 15,565 | 7.0, 7.0 | 39, 42 | 5, 7 | 92, 92 s | 7, 14 s | 11.3, 15.7 MB | 758,289 / 1,420 / 248 and 753,806 / 1,420 / 248 |

- **No effect on the analysis.** The benign pair is identical in score and signature set. The `etw3` pair is bimodal
  (5 or 7 processes, 38 to 42 signatures) with the modules off as well as on; the differing signatures
  (`encrypted_ioc`, `accesses_public_folder`, `unbacked_mutex_creation`, `unbacked_service_manipulation`,
  `unbacked_delay_execution`) fall on both sides of the split. n = 2 against 2; not a proof.
- **Time:** all four modules start in about 80 ms (E1: 00:46:48.918 to .996). Stop: AMSI, DNS and WMI took 30 ms in
  total; `network_etw` 0.2 to 0.9 s (joins its upload thread). Added run time is not measurable against the spread.
- **Bytes:** `wmi_etw.json` about 8 KB/s on a busy guest (750 KB for 90 s; a 20-minute run would be about 10 MB, not
  measured); `dns_etw.json` 0.4 to 41 KB; `network_etw.json` 248 B stock, 4 to 34 KB patched; `report.json` grows
  by about 7 KB on the benign run (the `network_etw` section; there is no `wmi`/`dns` section).
- **Giveaways visible to a sample:** `logman query -ets` during a run (the sample itself ran it; the output was
  collected as a dropped file, `fixture/logman-ets-during-run.txt`) lists **`ETW_AMSI`, `ETW_DNS`, `ETW_KernelNetwork`,
  `WMI_ETW`** next to Windows' own 30-odd sessions (and Sysmon's `SYSMON TRACE`). They are stopped at the end of the
  run (the list after a stop had none). `dns_etw` and `wmi_etw` each create an empty `C:\<5-10 random letters>`
  folder with their log in it (`network_etw` removes its own); gone with the revert. No driver and no process is
  left. The names are CAPE's defaults; renaming them is a one-line patch per module but they would still be extra
  sessions. The anti-VM surface of `docs/plans/m7-spikes/S2-findings.md` (drives, display adapter) is untouched.
- **Clock:** ETW `EventHeader.TimeStamp` is a FILETIME in the **guest clock**, which is 2 h behind real UTC (the
  analyzer logs "Date set to 20261019T00:54:09" into a UTC+2 guest; the first WMI record of a run CAPE started at
  00:46:44 real UTC reads 22:46:51.996). The calibrated `guest_clock_offset` applies exactly as for Sysmon.

### 4. Normaliser input and mapping (only if `wmi_etw` is ever shipped)

Input: `aux/wmi_etw.json`, one JSON object per line: `{"event_id": 11, "event": {...}}`. `event` always has
`EventHeader` (`ProcessId` and `ThreadId` of the **writer**, normally `wmiprvse`/`svchost`; `TimeStamp` FILETIME;
`ActivityId`), `Task Name`, `Description` (**localised** text with `%n` placeholders: ignore it) and the fields below,
all values **strings**. Key on `event_id` and the field names, never on `Description`. Fixture:
`fixture/wmi_etw.json` (158 of 941 records of run ES2: every id 11, 12, 19, 20, 22 and 5857 to 5861, 15 of each other).

| `event_id` | Fields (besides the header) | Meaning |
|---|---|---|
| 11 | `ClientProcessId`, `ClientProcessCreationTime`, `User`, `NamespaceName`, `Operation` (`Start IWbemServices::ExecQuery - root\cimv2 : SELECT ...`, `...::PutInstance - root\subscription : __EventFilter.Name="..."`, `...::GetObject`, `...::DeleteInstance`, `IWbemServices::Connect`), `OperationId`, `GroupOperationId`, `ClientMachine`, `IsLocal` | A client started a WMI operation. **The only event with a client pid.** |
| 12 | `ProviderName`, `ProviderGuid`, `Path`, `Operation`, `HostId` | A provider served it (`Provider::ExecQuery - CIMWin32 : select __RELPATH, ...`) |
| 19, 20, 22 | `ClientProcessId`, `Operation` / `MethodName`, `ClassName`, `ImplementationClass` | Repository delete / update / method execution |
| 5857, 5858, 5859, 5860, 5861 | provider start (`ProviderName`, `HostProcess`, `ProcessID`); operation error (`ClientProcessId`, `Operation`, `ResultCode`); temporary and permanent subscription activation (`Query`, `ESS`, `CONSUMER`, `Namespace`, `PossibleCause`) | 5861 for `ttspikefilter` / `CommandLineEventConsumer="ttspikeconsumer"` was recorded |
| 13, 16, 17, 50, 100 | operation stop, error, protocol, activity transfer, internal trace | noise, drop |

ECS mapping (data-model ETW row `wmi-*`, lane `process`): `event.module etw`, `event.dataset etw.wmi`,
`event.category [process]` (host), `event.action` `wmi-query` (ExecQuery, ExecQueryAsync), `wmi-write` (PutInstance,
DeleteInstance, PutClass), `wmi-method` (ExecMethod), `wmi-subscription` (5861); `@timestamp` = FILETIME to UTC
plus `guest_clock_offset`; `process.pid` = `ClientProcessId` (disambiguate pid reuse with `ClientProcessCreationTime`;
join to the capemon process by pid and time); `user.name`/`user.domain` from `User` (split on `\`); the operation text
in a `tartarus.wmi.{operation, namespace, query, object_path}` custom group (the data model has no WMI fields yet);
`tartarus.summary` `<image> ran WMI <verb> <target>`; 5861: `tartarus.wmi.consumer`, `tartarus.wmi.filter`. Keep only
events 11 (client pid in the sample's process tree, from the capemon/Sysmon process events), 5861 and 5858; they were
56 + 2 + 4 of 941 records. Sigma: 5861 is the shape of the `wmi_event` category, but Sysmon EID 19 to 21 already
fill that category with more fields (see below).

Not worth shipping, with the reason on record:

| Module | Why not |
|---|---|
| `dns_etw` | Stock data is wrong (service pid, no answers). A patched module duplicates Sysmon EID 22 (pid, image, `QueryStatus`, `QueryResults`, measured in S1 and again here: `QueryName=www.msftconnecttest.com QueryResults=::ffff:192.168.150.1; Image=...svchost.exe`) and capemon/pcap |
| `network_etw` | Stock data is empty on the simulated internet; a patched module duplicates Sysmon EID 3 and the pcap flows that Tartarus already attributes by capemon pid |
| `amsi_etw` | No events on this Windows build, with or without Defender; nothing to normalise |
| `wmi_etw` | Works, adds `PutInstance`/`ExecMethod`/`DeleteInstance` with the client pid, but WMI persistence is covered by Sysmon 19 to 21 and queries by capemon; revisit if analysts miss it |

Sysmon check, same guest (`Sysmon64.exe -c` with a config holding `<WmiEvent onmatch="exclude" />` and
`<DnsQuery onmatch="exclude" />`, then the PowerShell create-and-remove subscription): EID 19 (filter, with its
query), EID 20 (consumer, `Type=Command Line`, `Destination= "cmd.exe /c echo tt-spike"`), EID 21 (binding), each
with `Operation=Created` and `Deleted`, `User`, `UtcTime`; EID 22 for DNS with `ProcessId`, `Image`,
`QueryResults`. The pinned `sysmon-config.xml` and S1's proposed v2 have **no `WmiEvent` rule**; add one to the v2
config (a one-line change to S1's recommendation). EID 19 to 21 carry no pid.

### 5. Where collection lives, and the three ways a run ends

The four modules are **guest-side** auxiliaries that CAPE's resultserver stores under `aux/` (the whitelist in
`lib/cuckoo/core/resultserver.py` has `aux/dns_etw.json`, `aux/network_etw.json`, `aux/wmi_etw.json` and the
`aux/amsi_etw` directory). No host module is needed; the backend reads
`storage/analyses/<task>/aux/wmi_etw.json` from the read-only `cape-storage` mount, streamed line by line.

| Ending | Run | Files |
|---|---|---|
| Sample exits, CAPE ends the run | EB1, EB2 (benign, 45 s) | all three NDJSON files arrived |
| CAPE timeout | E1, E2, A1, A2 ("Analysis timeout hit, terminating analysis") | arrived (E1/E2 because a PowerShell child stalled 60 s) |
| `POST /api/analyses/{id}/finish` 46 s into a 1200 s task | F1 | arrived (`wmi_etw.json` 591 KB, `dns_etw.json` 6.4 KB, `network_etw.json` 4.0 KB); stop took 4 s |

`network_etw` also uploads a snapshot every 15 s, so a killed analyzer still leaves a file. A run where the **analyzer
dies before the auxiliary modules start** (the Defender-on EICAR case of S4) produces no ETW files at all, by the same
mechanism S4 found; not tested here, because the ETW modules would not be shipped.

### 6. Fixtures (real, parseable, small)

`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s2/fixture/`:

| File | Bytes | Records | What |
|---|---|---|---|
| `wmi_etw.json` | 143,463 | 158 | stock `wmi_etw` output, run ES2, trimmed as above |
| `dns_etw.stock.json` | 1,888 | 16 | stock `dns_etw` output, run E2 (service pid 800) |
| `dns_etw.patched-3006-3008.json` | 7,778 | 48 | patched module (client pid, status, answers), run EP1 |
| `network_etw.stock.json` | 248 | 1 | stock, run E1 |
| `network_etw.patched-no-host-filter.json` | 4,021 | 16 | patched, run EP1 |
| `logman-ets-during-run.txt` | 3,263 | 43 lines | the ETW sessions a sample sees during a run |
| `dns_etw.py.patched`, `network_etw.py.patched` | 5,359, 8,572 | | the two patched modules, for reference |

No `amsi_etw` fixture: it produced no events. The guest's generated account `Alice` and machine `LAPTOP-WPRE2DZ`
appear in them; both are throwaway.

## Method

Throwaway clone of `lab3` through `POST /api/guests/lab3/clone` (ready on the first try, no `reconfigure` failure).
`run.py` (copied from S4: public API only, collect the CAPE task folder with `docker cp`). Direct guest work
through the agent's `/store` and `/execute` with a small client (`ga.py`, run with the CAPE venv inside the
container; `snapshot-revert --running` first, `virsh destroy` after). Temporary modules and conf in the running
container, `supervisorctl restart cape cape-processor`, never a rebuild. Samples built in the container with
`x86_64-w64-mingw32-gcc` and copied out. First attempt at WMI from a VBScript (`cscript`) and from `Get-WmiObject`
stalled for 60 s under capemon (the analyzer restarts the WMI service at analysis start: "Restarting WMI Service"
in `analysis.log`); the working sample uses `Get-CimInstance` and `New-CimInstance`, which run in 3 s natively.

## Not verified

- AMSI on any other build, or with a different consumer; why no events arrive (Defender-on `lab5` and Defender-off
  clone both gave zero; the independent `logman` trace is the strongest evidence). The `.NET` assembly path
  (`amsi_etw_assemblies`) is untested for the same reason.
- `network_etw` stock on a route that is not INetSim (a real or VPN route, where the host IP is not the answer).
- IPv6 Kernel-Network events (28, 31, 58), `tcp_accept`, `connid`.
- A run where the analyzer dies before its auxiliary modules start; a run longer than 3 minutes (WMI file growth
  extrapolated); a sample that stops or tampers with ETW sessions (`logman stop`, `EtwEventWrite` patching).
- The full backend self-test on a wheel-installed guest (only the facts script and one analysis); a clean build with
  the manifest line and the `provision.ps1` step (not written); other guests than `lab3`'s clone and `lab5`.
- Sysmon EID 19 to 21 on the proposed v2 config as a whole (only a minimal config with `-c`); on a guest without Sysmon.
- Whether WMI work by an unhooked process other than PowerShell shows the same fields; `ExecMethod` was not exercised.
- Non-ASCII content in WMI or DNS records (the host-side JSON was `utf-8`; the `User` field carried `ZARZĄDZANIE NT`
  correctly).

## Commands to re-run the checks

```
docker compose up -d                                        # no --build
S=/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s2
# the wheel, on the HOST only
curl -s https://pypi.org/pypi/pywintrace/json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['releases'].keys(),[f['filename'] for f in d['releases']['0.2.0']])"
# a throwaway clone
curl -s -X POST localhost:8080/api/guests/lab3/clone -H 'content-type: application/json' -d '{"name":"m8-s2"}'
# route 1: the etw package inside the analyzer (no guest change); unpack the wheel on the host first
docker cp <unpacked>/etw tartarus-cape:/opt/CAPEv2/analyzer/windows/etw && docker exec tartarus-cape chown -R cape:cape /opt/CAPEv2/analyzer/windows/etw
docker exec tartarus-cape sh -c 'mkdir -p /opt/CAPEv2/custom/conf/auxiliary.conf.d /opt/CAPEv2/custom/conf/processing.conf.d
  printf "[auxiliary_modules]\ndns_etw = yes\nnetwork_etw = yes\nwmi_etw = yes\namsi_etw = yes\n" > /opt/CAPEv2/custom/conf/auxiliary.conf.d/m8-s2.conf
  printf "[amsi_etw]\nenabled = yes\n\n[network_etw]\nenabled = yes\n" > /opt/CAPEv2/custom/conf/processing.conf.d/m8-s2.conf
  supervisorctl restart cape cape-processor'
# samples: etw3.c, benign.exe in $S; build with  x86_64-w64-mingw32-gcc -O2 -s etw3.c -o etw3.exe -lws2_32  inside the cape container
python3 $S/run.py ES1 $S/etw3.exe m8-s2 --package exe --timeout 60
python3 -I $S/summ.py ES1                                  # events/score/signatures/aux sizes (needs runs/ES1)
# route 2: the wheel in the guest (revert, /store the wheel, then via /execute)
#   C:/Python311/python.exe -m pip install --no-index --no-deps --disable-pip-version-check <wheel>
#   re-snapshot: virsh snapshot-delete m8-s2 tartarus-clean --metadata ; virsh snapshot-create-as m8-s2 tartarus-clean ... (see section 1)
# early finish
python3 $S/run.py F1 $S/etw3.exe m8-s2 --package exe --timeout 1200 &   # then, ~45 s after "running":
curl -s -X POST localhost:8080/api/analyses/<id>/finish
# the sessions a sample sees: logman query -ets inside the run (etw3.exe does it, file C:\Users\Public\ttsessions.txt in files/)
# AMSI independent check, inside a guest:  logman create trace amsi -p '{2A576B87-09A7-520E-C21A-4942F0271D67}' 0xffffffffffffffff 0xff -o x.etl -ets
#   run a PowerShell Invoke-Expression, logman stop amsi -ets, tracerpt x.etl -of CSV  -> header only
# Sysmon WMI/DNS: Sysmon64.exe -accepteula -c <config with <WmiEvent onmatch="exclude" /> and <DnsQuery onmatch="exclude" />>, then
#   Get-WinEvent -LogName Microsoft-Windows-Sysmon/Operational | ? Id -in 19,20,21,22
```

Scratch drivers and sources (`run.py`, `summ.py`, `ga.py`, `ga.sh`, `etw*.c`, `amsiprobe.c`, `wmisub.ps1`,
`cleanup-cape.sh`, `facts-with-wheel.txt`, per-run `keep-small/<label>/analysis.json`) are in `$S`; the raw per-run
folders and `report.json` files were pruned for disk space.

## Temporary changes made and how each was reverted

Inside the running `tartarus-cape` container only (the repo was not touched): `analyzer/windows/etw/` (the wheel's
package), `custom/conf/auxiliary.conf.d/m8-s2.conf` and `custom/conf/processing.conf.d/m8-s2.conf` (both directories
did not exist before), patched `analyzer/windows/modules/auxiliary/{dns_etw,network_etw}.py`, `/tmp` helper files,
the four sample binaries in `storage/binaries`, libvirt and swtpm logs of `m8-s2` and `lab5`, `log/process-334..351`.
All removed; the two patched modules were restored by reversing the edit and **checked by sha256 against the list
taken at the start** (`sha256sum analyzer/windows/modules/auxiliary/*.py lib/common/etw_utils.py` identical);
`docker diff tartarus-cape` before and after differs only by the mtime of those two files and `/tmp/cuckoo-tmp/upload_*`
run artefacts (I also removed the `upload_*/benign.exe` copies that earlier spikes had left there). `cape` and
`cape-processor` were restarted after the revert, then the stack was stopped. 15 analyses (337 to 351) and the guest
`m8-s2` were deleted through the API; the libvirt images folder holds `lab1, lab3, lab5, win, win2` again;
`find / -iname '*m8-s2*'` (host and inside the container) finds only this spike's scratch folder. The downloaded
wheel and its unpacked copy were deleted.

Two slips to record: (1) a `pip list` run in the guest through the agent, without `--disable-pip-version-check`,
tried to reach `pypi.org` and got "self-signed certificate" from the guest's simulated network; nothing was fetched,
but it was a connection attempt from the guest. (2) `lab5` was reverted and started by hand with `virsh` for the AMSI
probe (and used by two CAPE analyses), then destroyed; it is `shut off` with its snapshot, like before.

Disk: `df -h /` 398G free (78% used) at the start and at the end; `docker system df`: images 104.8 GB, volumes
142.7 GB at both ends, containers 146.8 MB then 147 MB; the scratchpad is about 1 MB.
