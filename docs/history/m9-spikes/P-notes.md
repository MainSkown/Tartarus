# P notes (P1 PCAP import, P2 memory-image import), resume file
Start 2026-10-21 14:50. df / : 395G free (1.4T used, 78%). Stack was DOWN at start. Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/m9
## Big files that exist right now
(none: all deleted at the end, see Cleanup)
## Done
- P1 and P2 run to the end (see Log); findings written
- 14:50 read plan, S3 notes/findings, cape/bin/{volatility,memory_logic}.py, ingest/cape_network.py
- 14:53 docker compose up -d (stack up)
## Running
(nothing)
## Next
(nothing; both spikes done, findings in P1-findings.md and P2-findings.md)
## Temp changes outside m9-spikes (revert at end)
- all reverted, see Cleanup
## Log
- 14:52 analysis 370 submitted (p9sample.exe on lab3, memory_dump+keep) = P1 reference + P2 dump source. BIG FILE will appear: memory.dmp in analysis 370
- 14:54:48 analysis 370 (CAPE task 367) done; BIG FILE storage/analyses/367/memory.dmp (kept)
- 14:56:08 TEMP: container /tmp/p9/ (pcap copies, scripts); revert: rm -rf /tmp/p9 in cape container
- 14:57:34 CAPE pcap task 368 created via apiv2 create/file pcap=1 (to delete at end via tasks/delete)
- 15:00:56 CAPE pcap task 369 (27 MB) created; delete at end
- 15:04:39 analysis 371 (no memory) submitted to test pcap task concurrent with a guest run
- 15:05:44 pcap task 371 created during guest run 370 (reported in <1s: OK). Pcap tasks to delete: 368 369 371. P2 starting: hardlink storage/analyses/900001/memory.dmp -> 367 dump (TEMP, delete at end), fake analysis dir 900001
- 15:09:41 P2 A: control /memory/900001/analyse on hardlinked dump w/o report: pslist+cmdline 2.1s, malfind/hollow skipped (no pids). Unrestricted malfind 63s / hollow 66s in parallel: malfind finds PING.EXE 3888 MZ header. Next: raw + crash-dump format tests, symbols unknown-build test
- 15:09:51 BIG FILE: creating raw copy storage/analyses/900002/memory.dmp (4 GB sparse, TEMP, delete)
- 15:11:40 BIG FILE: creating synthetic PAGEDU64 crash dump storage/analyses/900003/memory.dmp (TEMP, delete)
- 15:13:23 raw (900002) and crash (900003) dumps tested (both OK, same 16 malfind rows incl PING.EXE 3888 MZ header) and DELETED. Next: unknown-build symbols test: move ISF aside (TEMP: /var/lib/libvirt/tartarus/symbols/windows/ntkrnlmp-24DE...xz -> .p9bak, must be restored)
- 15:14:25 ISF restored (original bytes). symbols unknown-build test OK: missing_symbols reported 0.3s, POST /symbols 20.5s, re-analyse 2s
- 15:15:23 TEMP: container /opt/CAPEv2/custom/conf/processing.conf.d/p9.conf ([suricata] enabled=yes) - dir is new; revert: rm -rf it. Reprocessing task 368 with process.py -r
- 15:16:04 reverted processing.conf.d/p9.conf (dir removed). Finding: cape.yaml rule-files scalar => Suricata loads no rules in cli mode (0 alerts)
- 15:16:27 pcap tasks 372 (pcapng) and 373 (garbage text file) created; delete at end
- 15:16:55 TEMP: container custom/conf/web.conf got [general] max_sample_size = 500000000 appended (original saved scratch m9/web.conf.orig, sha256 above); cape-web restarted; MUST restore + restart cape-web
- 15:17:35 web.conf RESTORED (sha checked) and cape-web restarted. pcap task 374 (54 MB) created; delete at end. Tasks to delete: 368 369 371 372 373 374
- 15:18:20 removed 900001, /tmp/p9 in container; deleting CAPE pcap tasks and Tartarus analyses 370,371
- 15:21:06 P1-findings.md written. P2 numbers: ELF core / raw (sparse 6 GiB logical) / synthetic PAGEDU64 crash dump all give the same 16 malfind rows incl PING.EXE 3888 MZ header; unrestricted malfind 62-63 s + hollow 65-66 s in parallel; session>0 pids only 13.6 s
## Cleanup (15:22:03)
- Deleted: Tartarus analyses 370, 371 (CAPE tasks 367, 370; the 4.3 GB dump went with 367), CAPE pcap tasks 368, 369, 371, 372, 373, 374, fake task folders 900001 to 900004 and 900010 (hard link, raw, crash dump, random file), the sample and PCAP copies in storage/binaries, /tmp/cuckoo-tmp/upload_* of my uploads, /tmp/p9 in the container, process-367..374 logs, site-packages/volatility3/symbols/windows (created by the failed symbol lookup), host scratch directory.
- Reverted: custom/conf/web.conf (sha256 checked against the saved original, cape-web restarted), custom/conf/processing.conf.d (removed), ISF file (moved aside and back; the regenerated copy was overwritten by the original, sha256 2c3f0320...). /home/cape/.cache/volatility3/identifier.cache was rewritten by Volatility (a cache).
- docker diff of tartarus-cape shows nothing of mine apart from that cache file.
- Free space on /: 395G at start, 395G at end (lowest about 386G with the raw copy and dump).
