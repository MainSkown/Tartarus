# Plan: M5, the analyst's own work and what leaves the app

M1 to M4 show what a run did, let the analyst ask questions and add Sigma to the detections. M5 is the
part that is the analyst's own and the part that leaves Tartarus: **tags and notes** on analyses,
processes and events, **IOC exports** (STIX 2.1, MISP, CSV) and an **HTML and PDF report**. It builds what
the [backend spec](../specs/backend.md#annotations) (annotations, export) and the [GUI
spec](../specs/gui.md) (Notes tab, Export menu, tags on the Dashboard) describe.

## Status

Built 2026-10-14 and 2026-10-15; F13 and F14 approved by the user after their screenshot reviews. M5 is done. Decisions 2, 3 and 6 were taken as accepted on the user's go-ahead (not separately
confirmed); 6's key-events definition is replaced by R0's (see decision 6).

What changed against the plan while building:

- **Tag names may hold one `:`** (`tlp:amber`): decision 1 forbade it while decision 8 needs `tlp:*` tags.
- **There was no job mechanism**, contrary to decision 7. X2 became X2a (report content and renderers),
  X2b (the `job` table, runner, `job` messages on `/ws/system`, `GET /jobs/{id}` and `/download`, the
  `exports` volume) and X2c (the report job and endpoint).
- **A report job writes `job-<id>-tartarus-report-<analysis>.<ext>`**, so an earlier job's download never
  serves a later report; the name the analyst downloads is `tartarus-report-<analysis>.<ext>`.
- **An IOC carries `first_seen`** (its first event's time) so the CSV column is filled; it is empty for
  the sample hash and mutexes, which have no event.
- **Key events** on analysis 193 come to 92, not R0's 146: gather caps citations at 5 per detection and
  leaves out the sandbox network.
- **The Dashboard row gained a menu** (Open, Re-ingest, Export, Delete) beside the existing delete and cancel
  icons, which stay.

What passed on a real run: `make e2e` against the rebuilt stack, 127 checks, 0 failed (annotations on the
analysis, a process and an event; survival of the re-ingest with ids unchanged; the three IOC exports
validated, STIX with `stix2`; an HTML and a PDF report as jobs, with and without notes; delete removing
annotations, job rows and the exports directory; the browser flow of tag, note, STIX download, report
download and Dashboard tag filter). The self-test Sigma rule must be enabled when the run starts.

Open:

- Event annotations are only for finished analyses (decision 3); the API refuses them on a live one.
- A report that finishes within about 300 ms after its dialog is closed gets no toast.
- The Dashboard table scrolls sideways between 700 and about 1250 px, with TAGS and the row actions off
  screen at 800 px; it did before M5 and the TAGS column widens it a little.
- The submit dialog's tags field from the GUI spec is not built (not in this plan); neither is a note on
  more than one note per target in the UI (the API allows several).
- Not tested: two report jobs on one analysis at once, a real browser print of a PDF, the guest wizard (M6).

## Outcome

- **Tags:** an analyst tags an analysis, a process or an event (`phishing`, `emotet`, `needs-review`). Tags
  show on the Dashboard (a column, and a tag filter next to the status filter), in the analysis header, in
  the event drawer and the process panel. Autocomplete offers existing tags with their usage counts.
- **Notes:** plain-text notes on the same three targets. The analysis note is edited inline and saved on
  blur with a "saved" toast; process and event notes live in the drawer and panel.
- **Notes tab:** every tag and note of the analysis grouped by target, each linking to its target.
- **IOC exports:** STIX 2.1, MISP event JSON and CSV, downloaded at once from the Export menu, built from
  the same IOC list the IOCs view shows, with the analyst's notes and tags carried where each format
  has a place for them.
- **Report:** HTML (one self-contained file) and PDF (the same template, print variant), from a dialog with
  include options (notes, screenshots, raw IOCs), run as a job with progress and a download when done.
- **Survives re-ingest:** annotations live in PostgreSQL, apart from the event index, so a re-ingest
  keeps them. Deleting the analysis removes them (the foreign keys cascade).

Out of scope: cross-analysis tag search beyond the Dashboard filter, editing or deleting another
analyst's notes (single user), rich-text notes, report templates the user can edit, scheduled or
automatic exports, YARA and Suricata rule management, the guest wizard (M6).

## Decisions

1. **Annotations are PostgreSQL rows** exactly as the data model has them: `tag`, `tag_link` (analysis,
   process or event target with a `target_ref`) and `note`. Tag names are lowercase `[a-z0-9._-]{1,40}` with at most one `:` between two parts, so `tlp:amber` is a tag (decision 8 reads it);
   a note is plain text up to 20 000 characters. One tag name, many links; one link per (tag, analysis,
   target).
2. **A process target is its pid** (the spec's choice), not `process.entity_id`. The entity id embeds the
   process start time, which the live collector and the final ingest calibrate differently, so a tag made
   during a run would lose its process. The cost: a guest that reuses a pid within one run shows the tag
   on both processes. **Confirm.**
3. **An event target is its `event.id`**, which is a hash of the source record and stays the same across a
   re-ingest. Events are only taggable and noteable on a finished analysis: a live event's id can change
   when the final ingest merges repeated calls (the e2e already allows this), so a live note could
   orphan. Analysis and process annotations work at any time. **Confirm.**
4. **An annotation whose target is gone is kept and shown as orphaned** in the Notes tab (the event is no
   longer in the index), never silently deleted. It is left out of exports.
5. **One source of truth for IOCs.** The exporters read the model behind `GET /analyses/{id}/iocs`
   (`app/views/iocs.py`), not a second extraction. STIX, MISP and CSV are pure functions of that model
   plus the analysis record and the annotations, so each is a unit test with no containers.
6. **Reports are rendered from one Jinja2 template**, HTML straight, PDF through WeasyPrint with a print
   stylesheet (white background, ice-blue accents, the same severity colours). The process tree is a
   static SVG built on the server (at most 120 rows including its `+N more` rows, depth 12, cut into
   30-row windows for the PDF so the text stays readable); screenshots are embedded as data URIs at their
   original bytes so the HTML is a single file; fonts are named explicitly (Liberation Sans and Mono, DejaVu
   as the glyph fallback). **Decided by R0:** "key events" means, in time order and at most 200: every
   alert, then process-lane events, then file and registry events, then the events a detection cites (any
   lane, at most 5 per detection with an "N more" note), then the first network event per destination.
   The definition first written (the events detections cite) gave 20 events on both real analyses, because
   detections cite almost only API-lane events; this one gives 146 and 149.
7. **Exports run as a job.** There is no job mechanism yet (found when X2 was planned: the `job` table,
   a runner and the `job` message of `/ws/system` are all unbuilt), so X2b builds the generic one:
   `job` table, `export_report` type, progress over the system WebSocket's `job` messages. The finished file is written to a new `exports` volume and
   removed with its analysis. IOC exports are small and are built in the request.
8. **MISP defaults:** `tlp:amber` unless the analyst has put a `tlp:*` tag on the analysis; the analyst's
   tags are added as MISP tags; ATT&CK techniques become `misp-galaxy:mitre-attack-pattern` tags only for
   ids the bundled ATT&CK table knows.
9. **Validation.** STIX bundles are validated in tests with the `stix2` library; MISP events against a
   JSON schema kept in the test fixtures; the PDF test checks it opens and has the expected page count
   and text, not its pixels.
10. **WeasyPrint stays in the backend image. Decided by R0** ([findings](#r0-findings-2026-10-14)): +47 MB
    content, and the image ends smaller than today's once the existing `uv sync` gets `--no-cache`; a report
    renders in 2.7 to 3.6 s at 120 to 160 MB peak. The job runner renders in a thread, never inline in the
    event loop. Packages: `libpango-1.0-0`, `libpangoft2-1.0-0`, `fonts-liberation`, `fonts-dejavu-core`.

## Waves

Tasks marked **care** follow rule 5's extreme-task process on Sonnet: small steps that each end in a
check that can fail, a notes file (done / running / next), and the planner re-runs the checks and reads
the diff before committing. Every task is test-first; every visual one ends in screenshots and one
Artifact per screen (rule 4).

### Wave 1

| ID | Task | Model | Deliverables | Check |
|---|---|---|---|---|
| **R0** | Spike: PDF and the static process tree | Sonnet, **care** | WeasyPrint in the backend image (size delta, build time, render time of a 5 000-event analysis' report), fonts that match the design system, a static SVG of the real process tree of analyses 193 and 144, `stix2` and a MISP schema usable in tests | Findings section in this plan with numbers; a recommendation on decisions 6 and 10; nothing in `backend/app` yet |

### Wave 2 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **N1** | Annotations backend | Sonnet | Migration, models and repository for `tag`, `tag_link`, `note`; the endpoints in the spec (`GET /tags`, annotations of a target, add and remove a tag, create, patch and delete a note); `tag` filter on `GET /analyses`; annotations in the event detail and the process view; the rules of decisions 1 to 4 | Repository tests (aiosqlite) for uniqueness, case and length limits, cascade on analysis delete; API tests for every endpoint and error; an integration test that a re-ingest keeps annotations and the event detail shows them |
| **X1** | IOC exporters | Sonnet | `app/export/`: STIX 2.1, MISP and CSV as pure functions of the IOC model, the analysis record and the annotations; `GET /analyses/{id}/export/iocs?format=` | Per-format unit tests against fixture IOC sets, `stix2` validation, MISP schema, CSV columns and quoting, empty IOC set, notes and tags carried |

### Wave 3

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **X2a** | Report content, **care** | Sonnet, **care** | `weasyprint` as a prod dependency and the backend image (apt packages, `--no-cache`); `app/export/report/`: the report model (summary, score, families, ATT&CK, process tree SVG, key events by decision 6, network, IOCs, detections, screenshots, tags and notes) and the function that gathers it from the existing views, the Jinja2 template and print stylesheet, the HTML and PDF renderers (PDF in a thread). Pure rendering: no job, no endpoint | The model builder against a fixture analysis; the template renders every section and honours the include options; the HTML is one file with no external reference; the PDF opens and has the text; the tree SVG caps and escapes; the key-events order and cap |
| **X2b** | Job mechanism and delivery | Sonnet | `job` migration, model and repository; a runner that executes registered handlers off the event loop with progress and a log tail, marks interrupted jobs on restart; the `job` message on `/ws/system`; `GET /jobs/{id}` and `GET /jobs/{id}/download`; the `exports` volume (compose, backend mount); cleanup of an analysis's export files on delete | Repository and runner tests with fake handlers: progress, failure, interruption on restart; the WebSocket message; download of a finished file, 404 and 409 cases; delete removes the files |
| **X2c** | Report job and endpoint | Sonnet | `export_report` handler (X2a's renderers on X2b's runner) and `POST /analyses/{id}/export/report` | Endpoint validation, progress steps, failure, the file under `exports`, delete removes it |

X2a and X2b run in parallel (disjoint files); X2c follows both. The planner regenerates the API client after N1, X1 and X2c.

### Wave 4 (frontend, parallel where the files are disjoint)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F13** | Tags and notes | Sonnet | Tag chips and the tag input with autocomplete (one shared component), the Dashboard tags column and tag filter, the header, the event drawer and the process panel sections, the analysis note edited inline, the NOTES tab with orphaned annotations, all states, screenshots, one Artifact |
| **F14** | Export menu and report dialog | Sonnet | The Export menu on the analysis page and the Dashboard row menu, the report dialog with include options, progress and a download link, error and cancel states, screenshots, one Artifact |

### Wave 5

`make e2e` gains: add and remove a tag and a note on an analysis, a process and an event of a finished run;
the tag filter on the Dashboard; a re-ingest keeps them; the three IOC exports download and validate; an HTML
and a PDF report run as a job, download, and contain the analyst's note; deleting the analysis removes
its annotations and its report file.

## Risks

| Risk | Handling |
|---|---|
| WeasyPrint bloats the backend image or renders slowly | R0 measures both first; the fallback is a print stylesheet printed by the browser |
| A pid reused in a run shows a tag on two processes | Documented in decision 2; revisit if it bites, with a start-time key that both phases agree on |
| Live event ids change on the final ingest | Event annotations only on a finished analysis (decision 3) |
| Report with thousands of events is slow or huge | The key-events cap of decision 6, screenshots optional, the job reports progress |
| STIX or MISP output rejected by a real consumer | Validation in tests against the library and the schema; the spec's mapping is followed as written |
| Agents report results optimistically | The planner re-runs every gate and `make e2e` before committing |

## R0 findings (2026-10-14)

Spike run on the real stack, in throwaway images and scripts outside the repo. The repo gained only this
section and [m5-r0-spike/](m5-r0-spike/): the package and font list, the spike's SVG builder
(`proctree_svg.py`), its Jinja2 print template (`report.html.j2`) and the two real tree SVGs. Nothing
under `backend/app`, `backend/tests`, `frontend/`, `pyproject.toml` or `uv.lock` was written by R0. Real
data: analyses 193 (13 178 events, 15 processes) and 144 (19 273 events, 16 processes), both `done`, read
through the API. All numbers are from one machine (Arch host, Docker, no other load beyond the running
stack), single runs of the builds, the median of 5 for renders.

### Recommendation

- **Decision 10: keep WeasyPrint in the backend image.** The image grows by 16.9 MB of apt packages and
  about 69 MB of Python packages, and a typical report renders in 2.7 to 3.6 s with 120 to 160 MB peak
  RSS. The same image is **smaller** than today's if the existing `uv sync` also gets `--no-cache`
  (140.6 MB content against 146.3 MB now, see below). Nothing here justifies moving PDF to the browser,
  and the browser route cannot be a job with progress and a download (decision 7), so it is also the
  worse fit. Not measured: a browser-printed PDF (no browser was driven), so that alternative has no
  numbers of its own.
- **Decision 6: three changes** (the key-events definition is wrong as written, the tree needs a row
  cap and pagination, fonts must be named). Details in the last sub-section. Screenshots as data URIs
  and the 200 cap are fine.
- **Decision 9: keep it, with one correction.** The MISP schema file requires nothing, so "missing
  `info` fails" is not a schema check (see step 5).

### 1. WeasyPrint footprint

Base: the repo's `prod` stage built as is (`r0-backend-prod:base`). "Weasy" images add the apt line
and `weasyprint` through `uv` in a copy of `pyproject.toml` and `uv.lock` in the scratchpad, same
Dockerfile otherwise (apt step run as root before `uv sync`, then back to `tartarus`).

| Image | apt packages (`--no-install-recommends`) | Content size | `docker images` disk usage | `du -sx /` |
|---|---|---|---|---|
| base (today's prod stage) | none | 146.27 MB | 621 MB | 449 MB |
| weasy-min | libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core | 191.21 MB | 816 MB | 590 MB |
| weasy-lib | libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation | 191.73 MB | 817 MB | not measured |
| **weasy-libdejavu** (recommended) | libpango-1.0-0 libpangoft2-1.0-0 fonts-liberation fonts-dejavu-core | 193.62 MB | 823 MB | 594 MB |
| weasy-libdejavu, `uv sync --frozen --no-dev --no-cache` | same | **140.56 MB** | 580 MB | 413 MB |

- Delta of the recommended image over base: +47.4 MB content (+32 %), +202 MB `docker images` disk usage.
  Where it goes (`du`): `/opt/venv` 158 to 227 MB (+69 MB: fontTools 29 MB, pillow libs 14 MB, rest),
  apt +16 MB, and the uv cache left in the image grows 122 to 182 MB.
- **The uv cache is already in today's image (122 MB under `/home/tartarus/.cache/uv`)** because
  `UV_LINK_MODE=copy` keeps it. `--no-cache` on the `uv sync` line removes it; the last row is that build,
  and `weasyprint.HTML(string='<p>hi</p>').write_pdf()` still ran in it. That fixes the growth and then
  some. It is a one-flag change to the existing Dockerfile line, to be made when the dependency is added.
- Build time (`--no-cache`, base images already pulled, apt and PyPI over the network): base 33.4 s,
  weasy-min 47.3 s. Cached rebuilds of the apt layer: about 21 s.
- apt: 19 new packages for weasy-min (6.3 MB download, +16.1 MB unpacked), 18 for weasy-lib (6.5 MB,
  +16.9 MB): `fontconfig`, `libfontconfig1`, `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`,
  `libfreetype6`, `libglib2.0-0t64`, `libfribidi0`, `libthai0`, `libdatrie1`, `libgraphite2-3`,
  `libpng16-16t64`, `libbrotli1`, `libexpat1`, `libatomic1` and the font packages. Debian 13 (trixie), pango
  1.56.3, harfbuzz 10.2.0.
- Python (resolved by uv against the repo's lockfile, 14 new packages, `jinja2` 3.1.6 is already locked as
  a `pysigma` dependency): `weasyprint==70.0`, `pydyf 0.13.0`, `tinycss2 1.5.1`, `cssselect2 0.10.1`,
  `pyphen 0.18.1`, `tinyhtml5 2.1.0`, `fonttools 4.67.0`, `brotli 1.2.0`, `zopfli 0.4.3`, `pillow 12.3.0`,
  `cffi 2.1.1`, `webencodings 0.6.1`, `pycparser`, `brotlicffi`.
- Runs as the non-root `tartarus` user (uid 1000): the check `python -c "import weasyprint;
  weasyprint.HTML(string='<p>hi</p>').write_pdf('/tmp/x.pdf')"` wrote a valid PDF as `tartarus`
  (`id -un` printed `tartarus`), and every benchmark below ran in the same way, writing to a bind mount.
- Event loop: rendering inline in a coroutine blocked the loop for the whole render (max lag 2 900 ms on a
  2.9 s render). `asyncio.to_thread` kept the max lag at 23 ms (p99 6 ms). The job runner must run the
  render in a thread (or process), never inline. Not tested: two renders at once.

### 2. Fonts

- The design system loads **no web font**: `--font-mono: "Courier New", Courier, monospace` and
  `--font-sans: system-ui, -apple-system, sans-serif` (`frontend/src/css/app.css` lines 67 and 68); icons are
  the Material Icons font, which the PDF must not depend on (severity is a text label plus a coloured
  border in the template instead, which is the design system's "colour is never the only signal").
- Closest Debian packages: **`fonts-liberation`** (SIL OFL 1.1, 4.3 MB installed): Liberation Mono is
  metric-compatible with Courier New, Liberation Sans with Arial. **`fonts-dejavu-core`** (Bitstream Vera
  licence, 2.3 MB) as the per-glyph fallback. Alternatives not chosen: `fonts-noto-core` 42.6 MB,
  `fonts-inter` 21.3 MB, `fonts-jetbrains-mono` 7.5 MB. Bundling a webfont is not needed.
- Check, `pdffonts` on a test page:
  - weasy-min (DejaVu only): DejaVu Sans, Sans Bold, Sans Mono, Sans Mono Bold, Oblique embedded; Courier New falls to
    DejaVu Sans Mono, a different face from the app's.
  - weasy-lib (Liberation only): Liberation Sans and Mono embedded, **but the symbols check, warning, play and cross
    render as empty boxes** (seen in the page image).
  - weasy-libdejavu: Liberation Sans, Liberation Mono and DejaVu Sans (fallback for those glyphs) embedded as
    subsets; the symbols render. The real reports use no symbol glyphs, and `pdffonts` on them lists only
    Liberation Sans, Sans Bold, Mono and Mono Bold.
- **Name the fonts in the print stylesheet.** With only `fonts-liberation` installed, `fc-match
  sans-serif` and `fc-match system-ui` answer *Liberation Mono*, so the design system's sans stack printed
  in monospace. The spike's stacks, which worked: `'Liberation Sans', Arial, Helvetica, sans-serif` and
  `'Liberation Mono', 'Courier New', Courier, monospace`. Both are in
  [m5-r0-spike/fonts-and-packages.txt](m5-r0-spike/fonts-and-packages.txt).

### 3. Render time

Fixture: the real summary, process tree, signatures, ATT&CK, network, IOCs, detections, artifacts and
**all** events of analysis 193 (13 178) and 144 (19 273) read from the API (500 per page, 13 178 events in
1.2 s over localhost), so no replication was needed for the 5 000-event target. Template
([m5-r0-spike/report.html.j2](m5-r0-spike/report.html.j2)): summary tiles, notes, ATT&CK, process tree SVG,
detections, key events table (cap 200), network (DNS, HTTP, hosts, first 50 flows), IOCs, screenshots as
data URIs, tags; A4, white page, ice-blue accents, severity colours, page numbers. The analyst notes and
tags are synthetic text (the annotation feature does not exist yet). "20 screenshots" are the analysis'
own 1280x800 JPEGs, about 85 KB each, embedded byte for byte.

Time is the median of 5 renders after the first in the same process; HTML is Jinja2 only, PDF is WeasyPrint
from the HTML string. Peak RSS is `ru_maxrss` of the process, which read 89 to 104 MB after the imports
and loading the events JSON, so it includes that baseline.

| Case (image weasy-libdejavu) | Key events | Pages | HTML | PDF | HTML render | PDF render (median; first) | Peak RSS |
|---|---|---|---|---|---|---|---|
| 193, no screenshots | 146 | 13 | 65 KB | 69 KB | 2.1 ms | 2.75 s; 2.69 s | 121 MB |
| 193, 20 screenshots | 146 | 17 | 2 228 KB | 1 697 KB | 5.6 ms | 2.92 s; 2.91 s | 149 MB |
| 193, key events padded to the 200 cap | 200 | 15 | 76 KB | 76 KB | 2.3 ms | 3.15 s; 3.18 s | 127 MB |
| 193, 200 key events + 20 screenshots | 200 | 19 | 2 239 KB | 1 704 KB | 6.1 ms | 3.55 s; 3.44 s | 160 MB |
| 144, no screenshots | 149 | 14 | 67 KB | 70 KB | 2.0 ms | 2.95 s; 2.95 s | 134 MB |
| 144, 20 screenshots | 149 | 18 | 2 068 KB | 1 576 KB | 5.1 ms | 3.03 s; 3.07 s | 166 MB |
| Stress: 193 x5 (730 key rows, 95 detections, 185 IOCs) + 20 screenshots | 730 | 49 | 2 389 KB | 1 812 KB | 11.2 ms | 13.3 s; 12.5 s | 237 MB |

- The padded and stress rows repeat the real events (their text gets a suffix), so they measure the
  template's cost, not different data. The real analyses give 146 and 149 key events, under the cap.
- The first render in a fresh container is not slower than the later ones (no visible font-cache cost).
- PDF cost grows faster than the page count (the stress row against the 193 row with screenshots: 4.6x the
  time for 2.9x the pages), so the cap in decision 6 matters; at the 200 cap it is 3.2 to 3.6 s.
- The cost is in the template and layout, not in the event count: building the model from 13 178 events
  took 0.04 s here (JSON already on disk), reading them from OpenSearch is the 1.2 s above.
- Screenshots are not recompressed: 20 of them add about 1.6 MB to the PDF and 2.1 MB to the HTML (base64).
  Cost beyond 23 screenshots was not measured.
- Check: `pdfinfo` opens every PDF (Producer WeasyPrint 70.0, A4); `pdftotext` finds `benign.exe`, the
  sample name, 28 times in the 193 report; page images viewed.

### 4. Static process tree SVG

Built in pure Python with `xml.etree.ElementTree` (no new dependency),
[m5-r0-spike/proctree_svg.py](m5-r0-spike/proctree_svg.py): one row per process, indent per level,
elbow connectors, `name (pid)` in mono with the name cut at 34 characters plus an ellipsis, a `SAMPLE`
tag, a severity tag (`HIGH 5`, text plus border colour), `INJECTS <pids>` and a dashed `INJECTION TARGET`
box, a `+N more` row for what a cap hides, and the `viewBox` sized to the content. Text is escaped by
`ElementTree` (a process name `<script>...</text><circle/>` stayed inert text and the SVG stayed
well-formed). Mono advance is 0.6 em in both Courier New and Liberation Mono, so the boxes fit the text.

| Tree | Processes | Roots, depth | SVG | Build time | Notes |
|---|---|---|---|---|---|
| Analysis 193 | 15 | 8, 3 | 296 x 438 px, 5.7 KB | not timed (ms) | explorer, benign.exe (SAMPLE, HIGH 5), cmd, svchost children all labelled |
| Analysis 144 | 16 | 7, 3 | 303 x 466 px, 6.3 KB | not timed (ms) | same shape, two Notepad children |
| Synthetic: 30-deep chain, 270-char path, injector and target | 36 | 2, 31 | 640 x 550 px after the depth cap | n/a | before the cap 1082 x 1026 px |
| Synthetic random, 100 / 400 / 2 000 nodes | 100 / 400 / 2 000 | 1 | 2 818 / 4 722 / 5 058 px tall | 2.0 / 4.2 / 8.3 ms | capped at 120 nodes |

Both real SVGs were converted with `rsvg-convert` and viewed (also at 2.5x): no clipped text, no overlap,
every label inside its box, tags clear of the next row. **Neither real tree has an injection target**
(`injected_into` is empty in both), so the injection markers were only checked on the synthetic tree,
where they rendered correctly (dashed orange box, `INJECTS 3,99999` for a pid not in the tree, nothing
drawn for the missing pid).

Defects found and fixed in the spike:

1. A 30-deep chain made the SVG 1 082 px wide: fixed by a depth cap of 12, the rest folded into `+N more`.
2. **A capped big tree is unreadable in the PDF.** 400 processes capped at 120 nodes is still 168 rows
   (the `+N more` rows are extra, 48 to 60 of them) and 4 722 px tall; one `<svg>` cannot break across
   pages, so `max-height` shrank it to about a fifth of its size (text about 2 px, seen in the page image).
   Fixed by cutting the tree into 30-row windows (the same SVG with a different `viewBox` per window, one
   window per `div`, `break-inside: avoid`): readable across 4 pages (18 in total), PDF 2.9 to 4.3 s, HTML
   113 to 383 KB, because the spike repeats the whole SVG in each window. The real implementation should
   emit only the rows of each window.
3. The first window cut a node box in half at the page boundary: fixed by cutting in the gap between rows
   (offset of 9 px); the page image shows no cut box.

Not fixed: the `+N more` rows are not counted in the cap, so a 120-node cap gave 168 rows. Count rows, not
nodes. Layout is a plain indented tree, not the spec's dagre graph with injection and network edges; the
spike drew none of those edges.

### 5. Test tooling

Checked in a fresh uv venv in the scratchpad (not the repo's), then the repo's own
`backend/tests/export/validation.py` was imported read-only (X1 added `stix2 3.0.2`, `jsonschema 4.26.0`
and `tests/fixtures/misp/event-2.5.schema.json` while R0 ran; the repo's test suite was not run by R0).

| Check | Result |
|---|---|
| `stix2.parse(bundle, allow_custom=False)` on a bundle with identity, malware, indicator, file / domain-name / ipv4-addr / url SCOs, attack-pattern, two relationships and a note | parsed, 11 objects |
| identity with `id: identity--not-a-uuid` | rejected, `InvalidValueError: ... must match <object-type>--<UUID>` |
| indicator with an unparseable pattern (`[domain-name:value = ]`) | rejected (stix2-patterns parses it) |
| a custom property `x_custom` on the malware | rejected with `allow_custom=False` |
| relationship with `source_ref: indicator--zzz` | rejected |
| Valid minimal MISP event against `event-2.5.schema.json` (jsonschema Draft4Validator) | 0 errors |
| The same event **without `info`** against the schema alone | **0 errors**: the schema requires nothing |
| Wrong type (`to_ids: "yes-please"`) and an unknown key | 2 errors from the schema |
| Same two events through the repo's `misp_problems` | valid: `[]`; without `info`: `['event lacks info']` |
| `pymisp` 2.5.34.4: `MISPEvent().from_dict(...)` | valid loads; without `info` raises `NewEventError`; unknown attribute type raises `NewAttributeError`; a sha256 attribute holding `xyz` loads without complaint |

- Verdict: **`stix2` for STIX (BSD), and for MISP the MISP project's `format/2.5/schema.json` with the
  required keys and the (type, category) pairs checked in the test helper, as X1 did.** `pymisp` (BSD-2-Clause)
  also works as a second opinion and rejects more (missing `info`, unknown type) but checks no values and
  brings `requests` and `deprecated`; not needed.
- Packages: `stix2` and `jsonschema` are test-only dev dependencies (already added by X1 in the working
  tree); neither goes in the image.
- Licence of the schema file: the file is the MISP project's; the repository is AGPL-3.0 as far as known,
  but the file's own licence was **not verified** by R0. It is a test fixture and is not shipped in the
  image.

### 6. What to change in decision 6

**Key events.** Detections cite events almost only in the API lane, so the definition as written ("every
alert, then the process, file, registry and network events that detections cite") yields almost nothing
beyond the alerts:

| | Analysis 193 | Analysis 144 |
|---|---|---|
| Alert events | 19 | 20 |
| Events cited by detections, as listed | 83 | 83 |
| of which in the API lane | 82 | 83 |
| of which process, file, registry or network | 1 | 0 |
| **Decision 6 as written** | **20 events** (19 alerts + 1) | **20 events** (20 alerts + 0) |
| Events cited, total (`related_event_total`) | 136 | 163 |

`related_events` in the detections view is capped at 50 per detection (one detection in each analysis is
over it), so the report builder cannot rebuild the full citation list from that view alone. Of 13 178 and
19 273 events, 450 and 413 are outside the API lane.

Proposal, in priority order, de-duplicated, at most 200, shown in time order, the lowest priority dropped
first when over the cap:

1. every alert event;
2. every process-lane event (starts, exits, injections);
3. file and registry events (writes, creates, deletes);
4. events cited by a detection, any lane, API included (what a reader needs to see why it fired);
5. the first network event per destination.

Measured on the two analyses: 146 events for 193 (19 alerts, 14 other process events, 8 file, 20 registry, 82 cited
API, 3 network) and 149 for 144, both under the cap. Keep the cap at 200: the report renders in 3.2 s (3.6 s with 20
screenshots). Cited API events count in tier 4, so a detection with 50 or more cited events can fill the cap;
cap the cited events per detection (suggested 5) and say "N more" in the detection block. Open for the
builder: fetch the cited events by id, because the view stops at 50 per detection.

**Process tree.** Cap at 120 nodes counting the `+N more` rows, depth 12, and split into 30-row windows
emitted separately; real trees of 15 and 16 processes fit on one page without any of that. Reuse the
design-system severity tokens; the spike's colours matched them. Draw the tree in a plain indented layout
(not dagre) for the report.

**Screenshots.** Embed as data URIs, original bytes, as decision 6 says; 20 cost about 1.6 MB of PDF and
2.1 MB of HTML. The include option stays. No resize needed at the 22 to 23 screenshots seen; larger counts
were not measured.

**Fonts and stylesheet.** `fonts-liberation` + `fonts-dejavu-core` in the image, named font stacks in the
print stylesheet, no icon font in the report.

**Dockerfile.** Add `--no-cache` to `uv sync`, add the apt line as root before it, add `weasyprint==70.0`
and a direct `jinja2` dependency; the exact list is in
[m5-r0-spike/fonts-and-packages.txt](m5-r0-spike/fonts-and-packages.txt).

### Could not verify

- A browser-printed PDF (the decision-10 fallback) was not built or measured.
- Two simultaneous renders, memory beyond the 237 MB stress case, and screenshot counts above 23.
- The notes and tags in the fixture are synthetic; the injection markers were never exercised by a real
  analysis (neither has an injection target).
- Build time of the weasy image is one run each (47.3 s against 33.4 s); the machine was not otherwise idle.
- The licence of the individual MISP schema file.
- R0 did not run the repo's backend test suite or lint; X1's files appeared in the working tree during the
  spike and were only read.
