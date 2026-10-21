# P1 findings: PCAP import (M9)

Spike on the real stack, 2026-10-21, CAPE at the pinned `CAPE_REF`, Suricata 7.0.17. No product code was changed.
Everything touched inside the `cape` container was reverted (list in `P-notes.md`); the analyses, CAPE tasks and
uploaded files were deleted.

## Verdict

**Go, on CAPE's own `pcap` task category.** `POST /apiv2/tasks/create/file/` with `pcap=1` runs no guest and no
machine, goes `pending` to `reported` on its own, and its `report.json` carries a `network` section **identical** to the
one of the run the PCAP came from. The existing `CapeNetworkNormalizer` then yields the same events. Nothing new is
needed inside the `cape` container. The reduced pipeline (call dpkt `Pcap()` ourselves) also matches and is the fallback
if the 30 MB limit below matters.

## The check (could fail, did not)

Reference run: Tartarus analysis 370 (CAPE task 367), `p9sample.exe` (fixtures/p9sample.c: 3 DNS names, 2 HTTP GETs, a
TLS ClientHello, then an injection into `ping.exe`) on `lab3`, INetSim route. Its `dump.pcap`: 316,427 bytes, 1,877
packets (fixtures/p9-run-370-dump.pcap). The run's index holds **196 `cape.network` events**: 187 `network-connection`,
5 `dns-query`, 4 `http-request`.

| Input | Network events | Same as the run |
|---|---|---|
| The run's own report re-normalised (sanity) | 196 | yes, every field and timestamp |
| CAPE `pcap` task report, same `started_at` | 196 | yes, every field and timestamp |
| CAPE `pcap` task report through the real `ReportIngester` (in-memory store) | 196 (187 / 5 / 4) | yes |
| Direct `Pcap()` call (dpkt), same `started_at` | 196 | yes |
| Same PCAP as pcapng (task route and direct call) | 183 tcp, 4 udp, 5 dns, 4 http | same counts (events not compared) |
| **Negative control**: PCAP cut to 150 KB | 95 | no (101 flows missing), so the comparison can fail |

`report["network"]` of the run and of the `pcap` task are equal key by key (`dns`, `tcp`, `udp`, `icmp`, `http`,
`smtp`, `irc`, `hosts`), except `domains[].ip` (below). Scripts: `scripts/compare_events.py`, `scripts/lib_pcap.py`.

## Routes tried

| Route | Result | Time |
|---|---|---|
| **A. CAPE `pcap` task** | works | picked up in under 1 s, `NetworkAnalysis` 0.26 s; 316 KB submit to `reported` about 5 s (`cape-processor` polls); 27 MB: 5.5 s; 54 MB: upload 1.35 s, processing 4.6 s |
| B. `modules.processing.network.Pcap(path, {}, {"sorted": False}).run()` in the CAPE venv | works, equal dicts | 0.25 s plus 0.5 s import for 316 KB; 4.0 s for 54 MB / 319,090 packets (about 13 MB/s) |
| C. `utils/process.py <id>` on a folder with no CAPE task | **fails**: `AttributeError: 'dict' object has no attribute 'to_dict'` (the "task not in database" branch builds a dict, `process()` calls `task.to_dict()`) | n/a |
| D. CAPE's Suricata module on the `pcap` task (`[suricata] enabled = yes`) | runs, 0.19 s, `dns` 18 and `http` 8 parsed, **0 alerts**: no rules load (below) | 0.19 s |

Route A, exact call (token from `CAPE_API_TOKEN`):

```sh
curl -H "Authorization: Token $TOKEN" -F pcap=1 -F file=@x.pcap http://cape:8000/apiv2/tasks/create/file/
# {"data":{"task_ids":[368],...}}  then GET /apiv2/tasks/view/368/ until status "reported"
# result: storage/analyses/368/reports/report.json   (dump.pcap there is a symlink into storage/binaries/<sha256>)
```

A `pcap` task started while a guest analysis was running was `reported` within the same second (`max_machines_count`
is 10, the task needs no machine). Delete: `GET /apiv2/tasks/delete/<id>/`; the PCAP copy in `storage/binaries/<sha256>`
and CAPE's `/tmp/cuckoo-tmp/upload_*` directories stay behind and had to be removed by hand.

## Limits and gaps

1. **Size.** `web.conf [general] max_sample_size` is 30,000,000 bytes: a 54 MB PCAP is refused ("Uploaded file exceeds
   the maximum allowed size in conf/web.conf. Sample size is: 51 Allowed size is: 29"). With `max_sample_size =
   500000000` in `custom/conf/web.conf` and `cape-web` restarted, the 54 MB PCAP was accepted and processed in 4.6 s
   (reverted). The processing timeout is 900 s (`CAPE_PROCESSING_TIMEOUT`).
2. **No process attribution.** In the run, 186 of 196 network events carry `process.*` (from capemon, by endpoint); an
   import has no capemon, so 0 do. Inherent to a PCAP. (The run's attribution is also coarse: all 183 flows to
   192.168.150.1:80 and :443 were credited to the sample, which made 2 HTTP GETs.)
3. **Time base.** Flow events are `info.started + (packet time - first packet)`; DNS and HTTP use the packet time. For a
   `pcap` task `info.started` is the import moment, so the import must set `started_at` to the first packet's time.
   With that, only flow timestamps differ from the run, by a constant 7.872 s: the run's flows sit 7.9 s early because
   `started` precedes the first packet, so the import is the more accurate one. First packet time: bytes 24 to 31 of a
   classic PCAP; pcapng needs its first Enhanced Packet Block read.
4. **Garbage in is not an error.** A text file submitted as `pcap` is `reported` with an empty `network`
   (`{"pcap_sha256"}` only), no error. The import endpoint must sniff the magic (`d4c3b2a1`, `a1b2c3d4`, `0a0d0d0a`)
   itself.
5. **CAPE resolves the PCAP's domains live.** `cuckoo.conf [processing] resolve_dns = on` (default, not overridden by
   Tartarus) makes `Pcap` look every domain up from the cape container: `domains[0].ip` was `23.47.124.79` in the run
   and `2.23.231.252` in my later re-processing, the only field that differed. Tartarus ignores `domains`, but the
   lookups still leave the host, for live runs today and for every imported PCAP of real malware traffic. Set
   `resolve_dns = off` (and keep `reverse_dns = off`, the default) in `cape/conf/cuckoo.conf`.
6. **TLS is not extracted by either side.** `httpreplay` is not installed ("OPTIONAL! Missed dependency"), so there is no
   `tls` section; the normaliser reads only `dns`, `tcp`, `udp`, `http`. Suricata's `eve.json` on the same PCAP has 47
   `tls` events (SNI, JA3) and 135 `http`. Same for run and import, so not an import gap.
7. **Suricata raises nothing today, in either path.** `[suricata] enabled = no` (no `suricata` key in any report), and
   in `cli` mode it loads **no rules**: `cape.yaml` sets `rule-files: suricata.rules` as a scalar over the list in
   `suricata.yaml`, and the log says `No signatures supplied`. With `-S /etc/suricata/rules/suricata.rules` the 44 MB
   ruleset loads and the same PCAP takes **10.9 s** and raises 140 alerts (mostly "InetSim Response from External
   Source Possible SinkHole"). Out of scope for import unless alerts become a feature for runs too.
8. **DNS answers.** CAPE's `dns[].answers` is empty for 4 of the 5 names although the PCAP holds the answers; same in
   run and import, not investigated.

## Recommendation for wave 1

- Backend: sniff the magic, cap the size (the limit in 1 is CAPE's, set it with the same number), store the file in the
  sample store, `create_file_task` variant with `pcap=1` (no machine, route, package or timeout), wait for `reported`
  like a normal task, ingest, override `started_at`. No guest, no queue slot, no Volatility.
- Config: raise `max_sample_size` to the product limit (cape config, with `cape-web` restarted); `resolve_dns = off`.
- Test-first fixtures: `fixtures/p9-run-370-dump.pcap` (316 KB) and `fixtures/p9-dpkt-network-section.json` (the expected
  `network` section).
- If PCAPs beyond what CAPE's upload accepts are wanted, route B (a control-service call that runs `Pcap()`) needs about
  30 lines in the cape container and builds the `report.json` itself; it removes the size limit, the CAPE task row and
  the copy in `storage/binaries`.

## Not verified

SMTP, IRC and ICMP extraction (none in the sample); IPv6; very large PCAPs (the 54 MB one repeats the same flows, so it
tests packet throughput, not flow-table size); HTTPS bodies; a PCAP from a different capture tool (all inputs here came
from CAPE's tcpdump); the `cape-processor` pickup delay under load; the HTTP upload path through the frontend (nginx
`client_max_body_size 512m`).
