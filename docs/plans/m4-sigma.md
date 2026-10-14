# Plan: M4, Sigma detections while the run happens

M1 to M3 show what a run did and let the analyst ask questions. M4 adds the third source of
detections, next to CAPE's signatures: **Sigma rules evaluated over the event stream**, live in the
collector and again in the final ingest, with a curated SigmaHQ ruleset shipped and the analyst's own
rules loaded from a directory. It builds what the [backend spec](../specs/backend.md#sigma-engine)
and the [GUI spec](../specs/gui.md#rules-rules) describe.

## Status

Planned 2026-10-14, after M3 was approved. Nothing built yet.

## Outcome

- **Detections appear as events.** A match is an `event.kind: alert` document with
  `rule.ruleset: sigma`, the rule's id, title, description, level (as `event.severity`), ATT&CK ids and
  tactic from its tags, and `related.events` naming the triggering event. The Detections tab, the
  query language (`rule.ruleset:sigma`), the Events and Timeline tabs and the process tree's detection
  counts already read alerts, so Sigma shows up in all of them with no change to them.
- **Live:** a match during the run reaches the LIVE tab's detections panel within the same batch as the
  event that caused it.
- **Final:** the final ingest evaluates the same rules over the whole rebuilt event set; that result is
  the authoritative one (live detections are provisional, as live events already are).
- **Rules page (`/rules`):** every loaded rule with enabled toggle, title, level, logsource category,
  status (valid, invalid, unsupported), path and hits across all analyses; filter by level, status and
  text; the YAML read-only with the error for an invalid rule; a reload button.
- **Shipped ruleset:** a curated SigmaHQ subset at a pinned commit, with its licence and attribution,
  plus a small Tartarus-authored rule the e2e uses. The analyst's rules go in `rules/sigma/custom/`.

Out of scope: Sigma correlation and aggregation rules (listed as unsupported, as the spec says),
`image_load` and `process_access` rules unless the spike shows our events can serve them (decision 6),
editing rules in the GUI, tags and notes (M5), YARA and Suricata rule management.

## Decisions

1. **The default ruleset is a curated subset of SigmaHQ** (the user's choice), at a pinned commit, with
   status `stable` or `test`, logsource categories we can feed (decision 4), and no rule that needs a
   field our events cannot carry. It lives in `rules/sigma/default/` with SigmaHQ's licence (DRL 1.1)
   and an attribution file; user rules go in `rules/sigma/custom/`. Both are read, neither is written,
   by the backend; the directory is bind-mounted read-only into the backend.
2. **pySigma parses and maps; the matcher is ours.** pySigma (core only) parses a rule and applies one
   `ProcessingPipeline` that maps Sigma fields to ECS. The pipeline's field table is built from the
   field catalog and the mapping in data-model, not a second list. The compiled form is a Python
   predicate tree over the event dict, supporting the modifiers the spec lists. The spike decides whether
   pySigma's Elasticsearch ECS pipeline can be reused or a small own pipeline is clearer; no
   Elasticsearch backend dependency either way.
3. **Rules are indexed by logsource category** and each event is only tested against the rules of its
   category (the mapping table in data-model). The matcher is a pure function of `(event, process
   context) -> matches`, with no I/O, so the collector, the ingester and the tests all call it.
4. **Events must carry what rules read.** Sigma rules written for Sysmon read `Image`, `CommandLine`,
   `ParentImage`, `ParentCommandLine`, `SourceImage`, `TargetImage`, `User` and similar. Our process
   events carry the executable, command line, parent pid and parent name but not the parent's
   executable path or command line, and an `inject-*` event carries only the target pid. Task S1 adds
   `process.parent.executable`, `process.parent.command_line` and the injected-into process's name,
   executable and command line, filled from the processes already seen in the run, in the one
   normaliser path both the live and the final ingest use. These are new catalog fields, so the index
   template, the query compiler and the column chooser get them with no other change.
5. **One detection per (rule, process) per 60 s window** (the spec), keyed on the process entity.
   A suppressed repeat only raises a counter on the emitted detection (`tartarus.detection.repeated`,
   new catalog field). Time is the event's own time, not the wall clock, so a live run and the final
   ingest suppress the same events.
6. **Logsource categories in scope** are the ones our events can serve today: `process_creation`,
   `file_event`, `registry_set`, `registry_add`, `registry_delete`, `network_connection`, `dns_query` and
   `create_remote_thread`. `image_load` and `process_access` stay out unless the spike shows a
   derivation from `LdrLoadDll` or the inject events that does not make events lie; an unsupported
   category is shown as unsupported, never silently dropped.
7. **The final ingest is authoritative.** It runs the matcher over the complete ordered event list of the
   rebuilt index, so a live miss (a late field, a clock offset) is corrected and a re-ingest of an
   old analysis gains Sigma detections. Live detections use the same code over the live stream and are
   provisional; the equality check of e2e (live versus final) compares them by rule and triggering
   call identity, as it already does for events.
8. **Rule state.** The `sigma_rule` table (Alembic) holds the rule's id, title, level, status, path,
   content hash, `enabled`, `valid`, `error` and `loaded_at`; the file is the source of truth for
   everything but `enabled`, which the analyst owns. A changed file reloads on its own (watchfiles) and
   `POST /rules/reload` does it on demand. Hit counts are not stored: they are an aggregation over
   `tartarus-events-*` on `rule.id`, so deleting an analysis removes its hits with its index.
9. **A bad rule never stops the engine.** A rule that fails to parse, uses an unsupported modifier or
   condition, or names a field the mapping lacks is stored with its error and skipped; the others run.
   A rule that raises while matching is disabled for the rest of the run with one logged error.
10. **No regular expression runs unbounded.** `re` modifiers compile with a size limit and match with a
    length cap on the input; a rule that cannot comply is invalid with that error. Rules are the
    analyst's input, so this protects the live pipeline from a slow rule.

## Waves

Tasks marked **care** follow rule 5's extreme-task process on Sonnet: small steps that each end in a
check that can fail, a notes file (done / running / next), and the planner re-runs the checks and reads
the diff before committing. Every task is test-first.

### Wave 1

| ID | Task | Model | Deliverables | Check |
|---|---|---|---|---|
| **S0** | Spike: what SigmaHQ can ask of our events | Sonnet, **care** | Fetch SigmaHQ `rules/windows` at a pinned commit; parse every candidate with pySigma; for each, record logsource category, fields used and modifiers used; join with our field catalog and the events of the real analyses (144, 45 and a new run) to report which rules are servable, which need which missing field, and which categories have events at all. A proposed list of 40 to 80 rules; a recommendation on decision 2 and decision 6; the first measured cost of matching all of them over 20 000 events | A written findings section in this plan with numbers; the proposed list as a file; nothing in `backend/app` yet |

### Wave 2 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **S1** | Events carry what rules read (decision 4) | Sonnet | The new catalog fields; the normaliser changes in the shared process-context path used by live and final; docs | Normaliser tests with fixtures: a child has its parent's path and command line, an injection event names its target process, an unknown pid leaves the fields out; live and final give the same documents (the existing equivalence test stays green) |
| **S2** | The engine core (decisions 2, 3, 5, 9, 10) | Sonnet, **care** | `app/rules/`: loader, mapping pipeline, predicate compiler, category index, matcher, suppression, detection emitter. Pure; no database and no collector yet | Every modifier of the spec with positive and negative events; each unsupported construct gives its error; suppression windows by event time; SigmaHQ-style cases for the shipped rules once S0 lists them (synthetic events from each rule's own selection); a rule that raises is isolated; a performance test (all shipped rules over 20 000 events within a stated bound) |

### Wave 3

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **S3** | Wire it in, persist it, serve it | Sonnet | The shipped ruleset and licence; the compose mount; the `sigma_rule` table and Alembic migration; the rule watcher; the collector and ingester call the matcher; live detection messages; `GET /rules`, `PATCH /rules/{id}`, `POST /rules/reload`, `GET /analyses/{id}/rules/hits`; generated client | Container tests: a rule file appears, changes, breaks and disappears while the app runs; the toggle persists across restarts; the final ingest of a fixture report yields the expected Sigma alerts; re-ingest adds them to an old analysis; live and final detections agree on a replayed fixture |

The planner regenerates the API client after S3.

### Wave 4

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F12** | Rules page | Sonnet | `/rules` as the GUI spec describes (table, filters, YAML view, error, reload), the Sigma group in the Detections tab and the LIVE detections panel checked with real alert shapes, screenshots at each state, one Artifact |

### Wave 5

`make e2e` gains: the shipped rules load and the Rules endpoint lists them; the e2e's benign sample
triggers the Tartarus-authored rule, live and in the final index; the live and final detections agree;
disabling the rule through the API and re-ingesting removes the detection.

## Risks

| Risk | Handling |
|---|---|
| Sysmon-shaped rules need fields we cannot derive from capemon's API calls | S0 measures it before any engine code; unsupported rules are listed as such, not faked |
| A curated set that never fires on the benign sample looks inert | The Tartarus-authored rule and synthetic-event tests per rule; the Rules page shows what is loaded and valid |
| Live and final disagree because the live clock is offset (M3 decision 8) | Matching uses event time within one run, so the offset cancels; the final result is authoritative and equality is checked by identity |
| Expensive rules slow the live pipeline | Category index, the regular-expression limits of decision 10, a performance test, a per-rule disable on error |
| SigmaHQ licence and provenance | The licence and attribution ship with the rules; the commit is pinned and recorded; rules are copied, not fetched at runtime |
| Agents report results optimistically | The planner re-runs every gate and `make e2e` before committing |
