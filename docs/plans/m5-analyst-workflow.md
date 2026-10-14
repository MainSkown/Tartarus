# Plan: M5, the analyst's own work and what leaves the app

M1 to M4 show what a run did, let the analyst ask questions and add Sigma to the detections. M5 is the
part that is the analyst's own and the part that leaves Tartarus: **tags and notes** on analyses,
processes and events, **IOC exports** (STIX 2.1, MISP, CSV) and an **HTML and PDF report**. It builds what
the [backend spec](../specs/backend.md#annotations) (annotations, export) and the [GUI
spec](../specs/gui.md) (Notes tab, Export menu, tags on the Dashboard) describe.

## Status

Draft, 2026-10-14, after M4 was approved. Nothing built yet. Decisions marked **confirm** need the user's
answer before the wave that depends on them.

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
   process or event target with a `target_ref`) and `note`. Tag names are lowercase `[a-z0-9._-]{1,40}`;
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
   static SVG built on the server; screenshots are embedded as data URIs so the HTML is a single file.
   "Key events" means: every alert, then the process, file, registry and network events that detections
   cite, at most 200, in time order. **Confirm the definition and the cap.**
7. **Exports run on the existing job mechanism** (`job` table, `export_report` type, progress over the
   system WebSocket's `job` messages). The finished file is written to a new `exports` volume and
   removed with its analysis. IOC exports are small and are built in the request.
8. **MISP defaults:** `tlp:amber` unless the analyst has put a `tlp:*` tag on the analysis; the analyst's
   tags are added as MISP tags; ATT&CK techniques become `misp-galaxy:mitre-attack-pattern` tags only for
   ids the bundled ATT&CK table knows.
9. **Validation.** STIX bundles are validated in tests with the `stix2` library; MISP events against a
   JSON schema kept in the test fixtures; the PDF test checks it opens and has the expected page count
   and text, not its pixels.
10. **No new heavy dependency without the spike's numbers.** WeasyPrint needs Pango and fonts in the
    backend image. S0 measures the image growth and the render time of a realistic report before
    anything is built on it; if it is too large the PDF moves to the browser (print stylesheet) and the
    plan changes before Wave 3.

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
| **X2** | Report | Sonnet, **care** | The report model (summary, score, families, ATT&CK, process tree SVG, key events, network, IOCs, detections, screenshots, tags and notes), the Jinja2 template and print stylesheet, HTML and PDF renderers, the `export_report` job, `POST /analyses/{id}/export/report`, `GET /jobs/{id}/download`, the `exports` volume and its cleanup on analysis delete | The model builder against a fixture analysis; the template renders every section and honours the include options; the HTML is one file with no external reference; the PDF opens and has the text; the job reports progress and failure; delete removes the file |

The planner regenerates the API client after N1, X1 and X2.

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
