# Your first analysis

You need a `READY` guest first. See [building a guest](building-a-guest.md).

## Submit a sample

1. Press `+ SUBMIT` in the header. On an empty Dashboard, press `[+ SUBMIT SAMPLE]`.
2. On the **Sample** tab, drop one file on the box or click it to browse. Tartarus shows the SHA-256 and the file type. If the same hash was analysed before, it warns you and links to that analysis.
3. Set the fields:

| Field | What it does |
|---|---|
| **GUEST** | The guest to run on. A guest that is not ready is listed but cannot be chosen. A guest that is busy can be chosen; your analysis then queues. |
| **NETWORK** | `INETSIM` (default), `NONE`, `DROP` or `INTERNET`. See [safety](safety.md) before you pick `INTERNET`. |
| **TIMEOUT** | The longest the run lasts, in seconds: 60 to 1200. Default 180. |
| **PACKAGE** | `auto` by default. Or a package the guest accepts, for example `exe`, `dll`, `doc`, `ps1` or `msi`. |
| **INTERACTIVE DESKTOP** | Off: the run ends when the sample exits, or at the timeout. On: you drive the guest yourself, and the run lasts the full timeout unless you end it. |
| **FULL MEMORY DUMP + VOLATILITY** | Off by default. See the next section. |

The default network route and timeout come from **Settings**.

4. Press `▶ DETONATE`.

The app opens the analysis. If the guest is busy, the page says `Queued, position N`.

## Submit a password-protected zip

Malware is often shared as a zip with a password, usually `infected`. Tartarus unpacks it inside the guest, so you never unpack it on your machine.

1. On the **Sample** tab, drop the `.zip` file. Tartarus reads the list of files in the archive. It does not unpack anything.
2. Check **ARCHIVE PASSWORD**. It is prefilled with `infected`. Change it if the archive uses another password.
3. Under **FILE TO RUN**, pick the file to run. An archive with one file selects it for you. With several files, you must pick one. A file marked **UNSAFE** (its name points outside the guest folder) or **NOT SUPPORTED** (its name has a comma, or starts or ends with a space) cannot be picked. Hover over the mark to see why.

The **PACKAGE** field then shows `zip` and is locked, because a zip is unpacked in the guest and always runs as a zip. Set the other fields as usual and press `▶ DETONATE`. The zip is limited to 512 MiB, like any sample.

If the password does not open the archive, the dialog says so under the password field and does not let you detonate. The API refuses the same submission too, so no analysis is queued. See [safety](safety.md#password-protected-zips).

## Full memory dump

Turn on **FULL MEMORY DUMP + VOLATILITY** to save the guest's RAM after the run and have Volatility 3 read it. The findings appear under **ARTIFACTS > Memory**.

- It adds about the guest's RAM in disk space. For a 4 GB guest the dialog says `Adds about 4.3 GB of disk`.
- The dump is deleted once the findings are read, unless you also turn on **KEEP THE DUMP AFTER THE FINDINGS ARE EXTRACTED**. A kept dump stays until you delete the analysis.
- CAPE needs free space to write a dump. At the default settings Tartarus wants about 48.8 GB free on the CAPE storage. If there is less, the dialog refuses the dump and says how much is free. When free space is above the refusal line but below the warning line, the submission goes through and the app warns you.

## Watch a live run

While the sample runs, the analysis page opens on the **LIVE** tab. The header shows a `● LIVE` badge. The status bar shows the phase and, for an interactive run, a countdown.

- **Desktop** (interactive runs): click the desktop panel to type into the guest. Keyboard input goes to the guest only while the panel has focus. Press `Esc` twice to leave it. There is no clipboard sync between the host and the guest.
- **Process tree**: the processes as they start. A warning count shows the detections on a process.
- **Detections**: Sigma matches appear as they fire.
- **Event stream**: `PAUSE` freezes the list, `FOLLOW` keeps it at the newest event. `SHOW API CALLS` brings back the very noisy API lane.

### Ending or extending an interactive run

For an interactive run, the status bar has two buttons:

- `[+60S]` adds 60 seconds to the deadline. It is disabled at the 20-minute limit.
- `[END RUN]` stops the guest now. A confirmation asks first. CAPE then processes what was collected. The run cannot be resumed.

The countdown turns amber for the last 30 seconds and then shows `ending`.

### Phases

- `● LIVE`: the sample runs in the guest.
- `PROCESSING`: the guest has stopped and CAPE is building the report.
- `FINAL`: the report is read and the analysis is complete.

While the analysis is not final, a note says `live data, final report pending`. When the run ends, the LIVE tab shows the last screenshot and a `[SUMMARY]` button.

If the analysis fails, a red banner shows the error in the header. The live data stays viewable.

## The analysis tabs

Once the analysis is done, the tabs show the full report. Before that, most tabs say `available once the analysis is done`. **NOTES** works at any time, and **LIVE** works while the run is going.

| Tab | What you find there |
|---|---|
| **LIVE** | The live feed, while the run is going. |
| **SUMMARY** | Score, highest severity, process count, events per lane, detections and screenshots. The specs call this tab "Overview". |
| **PROCESSES** | The process graph, or a tree with the same data, and the details of the selected process. |
| **TIMELINE** | Events on six lanes over time, with a detection track on top. |
| **EVENTS** | Every event in a table, with facets for filtering. |
| **NETWORK** | DNS, HTTP, TLS, flows and Suricata alerts. `⇩ PCAP` downloads the capture. |
| **ARTIFACTS** | Dropped files, payloads and configs, process dumps, memory, registry changes and IOCs. |
| **DETECTIONS** | Sigma, CAPE, YARA and Suricata matches, with an ATT&CK matrix view. |
| **NOTES** | Every tag and note in the analysis. |

The header also has `[DELETE]`, which is available once the analysis is no longer active, and `[EXPORT]` for IOCs and reports. `[CANCEL]` appears only while the analysis is queued. Use `END RUN` to stop a run that has started.

For what each tab shows in detail, see [reading a report](reading-a-report.md).

## Import a PCAP or a memory image

You can analyse a capture or a memory image that you already have, without running a sample.

1. Press `+ SUBMIT` and open the **Import** tab.
2. Drop or browse for the file:
   - a PCAP or PCAPNG capture, up to 512 MiB; or
   - a memory image of a Windows 10 or Windows 11 machine, up to 5 GiB.

Tartarus checks the file's first bytes to tell them apart. There are no options and no guest. The analysis is marked `imported` and queues apart from the runs.

For a memory image of a build Tartarus does not know, the Volatility symbols are fetched from Microsoft. That needs the `cape` container to reach the internet.

## Search across analyses

The **Search** page runs the same query bar over every analysis. Each result links to its analysis. Press `/` to focus the query bar.

Indicators are linked too. On the **ARTIFACTS > IOCS** list, an indicator held by other analyses shows `Seen in N analyses`. Click it to list those analyses. Mutex values are not linked.

For the query bar syntax, see [reading a report](reading-a-report.md#the-query-bar).
