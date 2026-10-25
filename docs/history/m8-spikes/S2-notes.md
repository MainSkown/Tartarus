# S2 notes (ETW spike), resume file
Start: df / 398G free (1.4T used, 78%). docker system df: images 104.8GB, containers 146.8MB, volumes 142.7GB, build cache 0B.
Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s2
## Done
- read plan, S1/S3/S4 findings, drivers; stack up (docker compose up -d); docker diff + sha baseline in scratch (diff-start.txt, sha-start.txt)
- host: pywintrace on PyPI = 0.2.0 only, py3-none-any, pure ctypes, no deps, 35,289 B, sha256 f3a8e717...cc56 (curl from host; pip not installed on host; wheel in scratch/wheels, delete at end)
## Running
- clone lab3 -> m8-s2
## Next
- install wheel in guest via agent, test 32-bit import / ETW session
## Temp changes in cape container (revert at end)
(none yet)
- 02:5x clone m8-s2 READY (first try, no reconfigure failure). Self-test analysis to delete. Analyses by me: (list later)
- NOTE for report: a 'pip list' in the guest (run via agent) tried to reach pypi.org (version check) and got an SSL self-signed-cert error = answered by the isolated sim network, not the real internet; use --disable-pip-version-check from now
- 02:5x wheel installed in running guest (pip --no-index --no-deps from C:\Windows\Temp, via agent /store+/execute), import OK under 32-bit py3.11; ETW_DNS session works (3010/3020 with ClientPID != header ProcessId=svchost 800). Guest running from revert, NOT re-snapshotted yet. cape container has /tmp/ga.py /tmp/pw.whl /tmp/etwtest.py (remove at end)
## Temp changes in cape container (revert at end)
- analyzer/windows/etw/ (pywintrace package copied from wheel; approach 2: ship in analyzer, no guest install)
- custom/conf/auxiliary.conf.d/m8-s2.conf, custom/conf/processing.conf.d/m8-s2.conf (dirs did not exist before)
- /tmp/ga.py /tmp/pw.whl /tmp/etwtest.py
- E1 (analysis 338/task 335, etw.exe, approach 2 = etw/ in analyzer, all 4 enabled): modules import+start OK under 32-bit py. dns_etw.json 2108 B (ProcessId = svchost 800, NOT client; ClientPID dropped by CAPE; no answers), network_etw.json 248 B (1 UDP138 broadcast; sample TCP to INetSim filtered out because INetSim IP 192.168.150.1 == resultserver/host IP in filter_ips), wmi_etw.json 391 KB/496 events (mostly background; has ClientProcessId + Operation text; capemon already logs WMI_ExecQueryAsync Query text), amsi_etw: no file (Defender-off guest has no AMSI provider? to test on lab5). PowerShell child doing Get-WmiObject stalled ~60 s (spawn timeout) -> run hit 120 s timeout. Next: VBS-based WMI sample, facts self-test with wheel installed, patched dns/network modules to see raw shape, AMSI on lab5, baselines.
- m8-s2 domain currently shut off with wheel installed on its disk overlay (pip), snapshot still the original.
- 03:0x re-snapshotted m8-s2 WITH wheel in site-packages (snapshot-delete --metadata + snapshot-create-as external, new files m8-s2-clean2.mem/.qcow2). Old files m8-s2-clean.mem etc still on disk (cleanup by find *m8-s2*).
- E2 (analysis 339/task 336, etw2.exe): wheel in snapshot works w/o analyzer overlay (overlay held at cape:/tmp/etw-overlay-held; must be removed/restored at end). cscript WMI hung (WMI service restarted by analyzer at +5 s), switched to PS New-CimInstance (works natively 3.4 s). DNS ETW: events 3006/3008 (in client process: header pid = client, QueryResults, QueryStatus) are NOT taken by CAPE; CAPE takes 3010/3020 whose header pid = DNS svchost (800), ClientPID dropped. AMSI file absent on Defender-off guest.
- facts-with-wheel.txt: guest-facts.ps1 with wheel installed: no GIVEAWAY lines, python 3.11.9 32-bit.
## Run plan: baseline (conf removed) benign x2, etw3 x2 -> stock on benign x2, etw3 x2 -> patched dns/network on etw3 -> lab5 AMSI (overlay needed) -> finish-call + timeout cases
## Analyses made by me: 337(selftest) 338(E1) 339(E2) ...
- baselines done: B1,B2 (etw3.exe, analyses 340,341), B3,B4 (benign.exe, 342,343), all modules off. summ.py summarises runs. Next: stock on (confs in cape:/tmp/m8s2-held -> back to custom/conf/*.d/m8-s2.conf)
- stock-on runs ES1,ES2 (etw3), EB1,EB2 (benign): no change in score/sigs (variance same as baseline). TEMP: patched dns_etw.py/network_etw.py in analyzer/windows/modules/auxiliary (originals sha in sha-start.txt; restore by checksum) 
- EP1 (patched dns 3006/3008 + network w/o host-ip filter, analysis 348): works, pid per event. Next: lab5 AMSI (overlay etw back into analyzer/windows/etw)
- A1 (lab5, Defender on, stock amsi): amsi.dll loaded in PS but 0 AMSI ETW events; also 0 on m8-s2 via independent logman trace (etl 8 KB header only). Investigating with amsiprobe on lab5 (ps1 must be put on lab5 via the sample...)
- DONE experiments: F1 (finish call, analysis 351) files arrive; A1/A2 lab5 (349/350) AMSI 0 events even with independent logman trace on Defender-on lab5 (etl 8 KB header only; script blocked by AMSI itself) ; Sysmon EID 19/20/21/22 verified on m8-s2 with a config containing WmiEvent/DnsQuery excludes-nothing: gives WMI filter/consumer/binding Created/Deleted incl. command line, and DNS with pid/image/results. Fixtures in scratch fixture/. Analyses: 337..351 all mine (delete).
- NEXT: cleanup: delete analyses 337-351, guest m8-s2, samples from storage/binaries (etw*.exe amsiprobe.exe), revert container (etw overlay, patched dns/network, conf.d dirs, /tmp files, /tmp/m8s2-held), restart cape+processor, docker diff compare, compose stop, find *m8-s2*, df. Then write S2-findings.md
- DONE. Cleanup finished (analyses 337-351 and guest m8-s2 deleted, container reverted and sha-checked, wheel deleted, stack stopped). df / 398G free at start and end. Findings in S2-findings.md.
