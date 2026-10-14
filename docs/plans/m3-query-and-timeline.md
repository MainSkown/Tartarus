# Plan: M3, search and see the whole run in time

M1 shows what a report contains and M2 shows a run live. M3 lets the analyst *ask questions*: a
query language over the analysis's events, the Events table with facets, a timeline of every lane,
and a detail drawer that opens from anywhere. It builds what the [backend
spec](../specs/backend.md#query-language-kql-like) and the [GUI spec](../specs/gui.md) describe, on
the event index of M1b and the field catalog it was generated from.

## Status

Planned 2026-10-14, after M2 was approved. Nothing built yet.

## Outcome

On a finished analysis:
- **Events tab:** a virtual table of every event (time, lane, process, action, summary), sorted by
  time either way and paged from the server; a column chooser for any catalog field; a collapsible
  facet panel with the top values of the process, lane, action, API, domain and rule fields (click to
  filter on, alt-click to filter out).
- **Query bar** shared by Events and Timeline: field and value autocomplete, errors underlined with
  the message, a syntax cheat sheet, and quick-filter chips. The query and chips live in the URL
  (`?q=...&f=...&pid=...`), so reload, back/forward and a bookmark work.
- **Timeline tab:** a canvas with the six lanes and a detection track, zoom (`fit`, `1m`, `10s`,
  `1s`, wheel and drag), brush selection that becomes a time-range chip, dense ranges drawn as count
  bars that expand when zoomed, a tooltip on hover, and the Events table below restricted to the
  visible range.
- **Event detail drawer** (480 px, right, overlay) from any event row or mark: header, a fields table
  with filter on, filter out and copy on each row, the raw JSON, related events as links, and the
  up and down keys to move through the current list.
- **`filter on` actions** on the Network and Artifacts rows add a chip and take you to Events; the
  process selected on the Processes tab can be shown as events the same way.

Out of scope: tags and notes (M5; the drawer's tag and note section waits), Sigma (M4), cross-analysis
search, saving queries, and the query language on the LIVE stream (see decision 9).

## Decisions

1. **The grammar is the spec's, written with `lark`** (a new pinned backend dependency), into an AST
   and then into an OpenSearch `bool` query. The compiler is a pure function with no I/O:
   `compile_query(text) -> Compiled(query, errors)`. Adjacent terms are ANDed, keywords are
   case-insensitive, `field:(a OR b)`, ranges `> >= < <=` on numeric and date fields, `field:*` for
   exists, quoted strings with `\\` as a literal backslash, `*` and `?` wildcards, `NOT` and
   parentheses.
2. **One field table.** Field names, aliases and types come from `app/search/fields.py` (the catalog the
   index template is generated from); the compiler and the autocomplete endpoint read it and define no
   field list of their own. The spec's aliases that the catalog lacks (`cmd`, `reg`, `sev`, ...) are
   added to the catalog. `domain` stands for two fields (`dns.question.name` OR `destination.domain`),
   so the catalog gains composite aliases in one small table next to it.
3. **Errors carry spans.** A syntax or unknown-field error is `{start, end, message}` in characters of
   the query text, with a "did you mean" suggestion for an unknown field (closest names and aliases).
   A query that does not compile is never run.
4. **Free text** searches `tartarus.summary`, `process.command_line`, `file.path`, `url.full` and the
   values of `api.arguments`; which of those fields support which query type is checked against the real
   mapping (text subfields, `flat_object`), not assumed.
5. **Limits protect the cluster:** query length, nesting depth, number of terms and wildcard clauses are
   capped with a clear error; there is no regular-expression syntax; a leading wildcard is allowed and
   counted against the cap.
6. **Paging is `search_after`** on `(@timestamp, event.sequence)`; the cursor is opaque. During a live
   run new events can slip in between pages; for a finished analysis the order is stable.
7. **Endpoints** as in the backend spec: `POST events/search`, `events/facets`, `events/histogram`,
   `GET events/{id}` (with the raw document and the related events in both directions: the ones this
   event names and the alerts that name it), `POST /query/validate`, `GET /query/fields`,
   `GET analyses/{id}/query/values`. The filter body is `{query, filters[], time_range?, lanes?, pids?,
   sort, size <= 500, search_after?}` and the chips (`filters[]`) are ANDed with the query.
8. **One clock.** Events from the guest (capemon) and from the network capture are on different clocks:
   the guest's runs 5 to 8 seconds behind the host's (measured in M2), so on one timeline a DNS lookup
   from the capture sits seconds away from the call that made it. Before the timeline is built, the
   calibration anchors to something exact (the host's own record of when a process registered with
   CAPE, which `cuckoo.log` has) instead of only rounding to a quarter hour; see task T0.
   **T0 result (measured on eight real analyses):** the skew is a constant per run (not a drift:
   7.143 to 7.147 s over 140 s) that differs between runs (4.4 to 7.1 s), because CAPE sets the guest
   clock to the task's creation time. The exact anchor is the ResultServer's millisecond host time
   for a process registering in the task's `cuckoo.log`, matched with that process's guest
   `first_seen`; the final ingest reads it (`IngestContext.host_registrations`, one helper in
   `clock.py`) and capemon then sits 11 to 51 ms from the pcap's record of the same lookup instead
   of 4.4 to 7.1 s. **Live cannot use it:** CAPE keeps the task `cuckoo.log` in a write buffer until
   the task ends, so a live run stays on the rounded offset (capemon 5 to 7 s early, as in M2) and
   the final index is the exact one; the live stream carries no host-side events to line up with, so
   nothing is misaligned while it runs, and it would take a one-line CAPE patch (flush the task log
   after each write) plus a re-reading collector to change that. Details: data-model, "Time in a
   CAPE report".
9. **The LIVE stream keeps its lane and process filters.** Supporting the query language there needs the
   same semantics evaluated in memory over dict events, which would be a second implementation of the
   grammar; if wanted it is done by evaluating the compiled AST, not by re-implementing, and not in M3.
10. **Shared query state is a Pinia store** (`query-state`): the text, the chips, the selected process
    and the time range, serialised to the URL and read from it. The Events and Timeline tabs, the
    facet panel, the table and the drawer's filter actions all act on it; no component keeps its own
    copy.
11. **The timeline draws on a canvas** (as the design system says), from two sources: the histogram
    (buckets per lane, with detection markers) when the visible range holds more than 2000 events, and
    the individual events when it holds fewer. Hit-testing and the tooltip are pure functions of the
    drawn geometry, unit-tested without a browser; the pixels are checked with screenshots.

## Waves

Tasks marked **care** follow rule 5's extreme-task process on Sonnet: small steps each ending in a
check that can fail, a notes file (done / running / next), and the planner re-runs the checks and reads
the diff before committing. Every task is test-first.

### Wave 1 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **Q1** | Query compiler | Sonnet, **care** | `app/query/` (grammar, AST, compiler, errors with spans, did-you-mean, limits), the catalog's missing and composite aliases | Every example of the spec compiles to the expected query; precedence, `NOT`, grouping, adjacency; each error kind with its span; the limits; against a real OpenSearch index loaded with the fixture report, a table of queries gives the expected event sets (not only the expected JSON) |
| **T0** | One clock | Sonnet, **care** | Find the exact anchor for the guest clock skew on the real stack (`cuckoo.log`, `analysis.log`, `info`, the pcap), make the calibration use it, and keep the report and live paths identical | On the real reports in the scratchpad and one new real run: capemon and network events of the same action agree within 1 s; the clock helper's tests; the live-versus-report equivalence test stays green |

### Wave 2

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **Q2** | Events API | Sonnet | The endpoints of decision 7 on `EventIndex.search`, typed schemas, `search_after` cursors, facets, the adaptive histogram, the event with its related events, the field catalog and the value autocomplete | Container tests over the fixture index: paging reaches every event exactly once in both sorts, filters and query combine, facets match counts, the histogram sums to the total and to the lane counts, unknown ids and analyses give 404, a bad query gives 422 with spans |

The planner regenerates the API client after Q2.

### Wave 3

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F8** | Query foundation | Sonnet | The `query-state` store and its URL sync, `QueryBar` (autocomplete, error underline, cheat sheet), `FilterChips`, the shared `FieldActions` (filter on, filter out, copy) |
| **F9** | Events tab | Sonnet | `EventTable` (virtual scroll, paging, sort, column chooser), the facet panel, `EventDetailDrawer` with up and down navigation and related events |
| **F10** | Timeline tab | Sonnet, **care** | The canvas timeline, zoom, brush, aggregation, hover and click, the table below synced to the range |
| **F11** | Filter-on everywhere | Haiku to Sonnet | The actions on the Network, Artifacts, Processes and Detections rows, taking you to Events with the chip |

F8 first; F9 then F10 (the timeline opens F9's drawer); F11 beside F10. Each screen goes through the rule
4 screenshot review, one Artifact per screen.

### Wave 4

`make e2e` gains a check that a finished analysis answers queries through the real API and that the Events
tab filters it in a real browser.

## Risks

| Risk | Handling |
|---|---|
| The grammar's ambiguities (adjacent terms, free text beside fields, values with spaces and backslashes) | Written down as tests from the spec's examples first; the compiler is checked against real result sets, not only JSON |
| Expensive queries (leading wildcards, free text over many fields) | Limits of decision 5; measured on the largest real report available; a timeout on the search |
| The timeline's canvas is the most custom UI so far | Pure geometry and hit-testing under unit tests; extra-care process; screenshots at several sizes |
| Skewed clocks make the timeline look wrong | T0 before F10, with a real-run check |
| Events are indexed with `dynamic: false`, so an unmapped field cannot be queried | The compiler only accepts catalog fields; the drawer shows everything else from the raw JSON |
| Agents report results optimistically | The planner re-runs every gate and `make e2e` before committing |
