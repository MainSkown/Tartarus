# Reading a report

Once an analysis is `DONE`, its tabs show the full report. This page explains what each tab is for, how the query bar works, and how to export results. All times in the app are UTC.

For the exact layout of every tab, see [the GUI spec](../specs/gui.md#analysis-workspace-analysesid).

## Summary

The **SUMMARY** tab answers "is this bad?" in one screen.

- Stat tiles: score, highest severity, process count, duration, files written, registry keys written, DNS, hosts and TCP.
- Events per lane, and detections by severity.
- Detected families and extracted configs.
- Top detections, a short ATT&CK view and a strip of screenshots. Click a screenshot to enlarge it.
- Sample information: type, size, hashes, imphash, signer, sections and strings.
- **WINDOWS DEFENDER**: what Defender did with the sample and any file it dropped. If Defender removed the sample before it ran, the run is empty on purpose and there are no processes to read.

## Processes

The graph shows each process and how it started. A switch changes to a tree with the same data, which is easier to read for large runs.

- Click a process to select it. Its details appear on the right: command line, path, PID and PPID, integrity, start and end time, events per lane, detections, network hosts, injections and modules.
- Toolbar: fit, zoom, reset the layout, show or hide network hosts, show or hide injection edges, and export the graph as PNG.
- A selected process filters every other tab with a `pid` chip.

## Events

**EVENTS** is the full table of every event.

- Columns: time, lane, process, action, summary and, for detections, severity. Add more columns from the column chooser.
- The left panel has facets for `process.name`, lane, `event.action`, `api.name`, domain and rule, with the top 10 values each. Click a value to filter on it. Alt-click to filter it out.
- Sort by time, ascending or descending.

Click any row to open the **event detail drawer**. It shows the fields, each with a `filter on` and `filter out` button, the raw JSON, related events, and the tags and note for that event. Use `↑` and `↓` to move through the list.

## Timeline

**TIMELINE** draws events on six lanes (process, file, registry, network, memory and API), with a detection track on top.

- Zoom with `fit`, `1m`, `10s` or `1s`, or with the scroll wheel. Drag to pan.
- Drag across the timeline to select a time range. It becomes a chip you can remove.
- A busy part of the timeline shows a count instead of single events. Zoom in to see the events.
- Hover for a tooltip. Click an event to open the detail drawer.

The EVENTS table under the timeline shows the same time range.

## Network

**NETWORK** has sub-tabs:

- **DNS**: query, type, answers and process.
- **HTTP**: method, URL, status, user agent and process.
- **TLS**: server name, JA3 and JA3S, and process.
- **Flows**: the five-tuple, bytes, packets and process.
- **Alerts**: Suricata alerts.

A row answered by INetSim is marked `inetsim`. `⇩ PCAP` downloads the capture of the whole run.

## Artifacts

**ARTIFACTS** has sub-tabs:

- **Dropped files**: name, path, size, type, SHA-256, YARA hits, the process that wrote it, and a download.
- **Payloads & configs**: CAPE payloads with their family, and the extracted config.
- **Process dumps**.
- **Memory**: the dump size and download, if the dump was kept, and Volatility 3 findings grouped by plugin. See [the memory dump](first-analysis.md#full-memory-dump).
- **Registry**: changes grouped by key, with the old and new value.
- **IOCs**: a list of deduplicated indicators with type, value, context and source. Use the copy button, or `filter events on this`.

Downloaded artifacts are zip archives with the password `infected`, so a browser never runs a sample by accident.

## Detections

**DETECTIONS** lists every match, grouped by ruleset: Sigma, CAPE, YARA and Suricata. Select one to see its description, what matched, the events that triggered it, and its ATT&CK techniques. The `ATT&CK` toggle switches to a matrix of tactics and techniques, with hits coloured by severity.

Sigma rules are in `rules/sigma/`. Put your own in `rules/sigma/custom/`. The **Rules** page lists them and reloads them with `[RELOAD]`.

## Notes and tags

- **Tags**: the header has `[+]` to add a tag to the analysis. The same tags can be set on processes and events from their drawers.
- **Analysis notes**: type in the **NOTES** tab. A note saves when you leave the field, and a toast says `saved`.
- **Notes on processes and events**: added from the process details or the event drawer.

The **NOTES** tab lists every tag and note in the analysis, grouped by where it belongs.

## The query bar

The query bar sits above the TIMELINE and EVENTS tabs of a finished analysis, and on the **Search** page. Press `?` next to it for a cheat sheet.

A query is one or more terms joined with `AND`, `OR` and `NOT`. Field names are written with a dot and the value follows the colon:

- `field:value`: `process.name:cmd.exe`
- `field:(a OR b)`: one field, several values
- `field > value`, `>=`, `<`, `<=`: numbers, such as `destination.port >= 1024`
- `field:*`: the field exists
- `*` and `?` are wildcards, and quotes keep spaces: `process.name:"explorer.exe"`
- bare words are free-text search, for example `powershell -enc`

Common field aliases include `proc` (process name), `cmd` (command line), `api`, `path`, `reg`, `ip`, `port`, `domain`, `url`, `lane`, `rule` and `sev` (severity). The full list, with the exact grammar and limits, is in [the backend spec](../specs/backend.md#query-language-kql-like).

Here are five queries from the spec:

```text
process.name:cmd.exe AND lane:network
api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"
destination.port >= 1024 AND dns.question.name:*.onion
rule.ruleset:sigma AND event.severity >= 3
powershell -enc
```

A query with an error is underlined in red, and the error appears on hover. The query does not run until it is valid. Chips under the bar are quick filters: click a chip to switch it between "is" and "is not", and `×` removes it.

## Exports

The **[EXPORT]** button in the header has two groups.

**IOCS** downloads at once, in one of three formats:

- **STIX 2.1**: a bundle with the file, domain, IP and URL indicators, the families, the ATT&CK techniques, and your notes.
- **MISP**: an event with attributes for hashes, domains, IPs, URLs, files, registry keys and mutexes, and their tags.
- **CSV**: one row per indicator, with type, value, context, first seen and source process.

**REPORT** opens a dialog. Choose **HTML** or **PDF**, pick what to include, and press `[GENERATE]`:

- **NOTES**: your notes on the analysis, its processes and its events. Tags always stay.
- **SCREENSHOTS**: the guest screenshots. Off makes the file much smaller.
- **RAW IOCS**: every indicator of each type. Off keeps the first five of each type.

The report builds in the background and a toast tells you when it is ready. `[DOWNLOAD HTML]` or `[DOWNLOAD PDF]` saves it. The HTML report is one self-contained file. The PDF uses the same content on a white background.
