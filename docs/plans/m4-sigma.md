# Plan: M4, Sigma detections while the run happens

M1 to M3 show what a run did and let the analyst ask questions. M4 adds the third source of
detections, next to CAPE's signatures: **Sigma rules evaluated over the event stream**, live in the
collector and again in the final ingest, with a curated SigmaHQ ruleset shipped and the analyst's own
rules loaded from a directory. It builds what the [backend spec](../specs/backend.md#sigma-engine)
and the [GUI spec](../specs/gui.md#rules-rules) describe.

## Status

Planned 2026-10-14, after M3 was approved. Built the same day: S0 to S3 and Wave 5 are committed and
`make e2e` passes with the Sigma checks (85 checks, on a real run). F12 (the Rules page, the LIVE
detections panel) is built. M4 was closed by the user on 2026-10-17, without a recorded round of comments on
the two Artifacts.

Added to M4 afterwards: a Sigma alert's `tartarus.detection.match` names the matching values of the
triggering event instead of the rule's condition text (an explainer compiled beside the predicate, run
only for matched events; [data-model](../specs/data-model.md#sigma-field-mapping)).

Open after M4: the API carries no repeat count or tactic for a detection; a Rules-page check in the browser e2e.

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
  plus a small Tartarus-authored rule the e2e uses (`rules/sigma/tartarus/`). The analyst's rules go in `rules/sigma/custom/`.

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
   predicate tree over the event dict, supporting the modifiers the spec lists. **Decided by S0: a small
   own pipeline** with no fallback for unmapped fields, not pySigma's Elasticsearch ECS pipeline (see
   [S0 findings](#s0-findings-2026-10-14)); no Elasticsearch backend dependency.
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
   `create_remote_thread`. **Decided by S0:** `image_load` and `process_access` stay out (no derivation
   that does not make events lie); an unsupported category is shown as unsupported, never silently
   dropped. `network_connection` is in scope for the engine, but every network flow today is a pcap flow
   without a process, so the shipped set holds no network rule and M4 promises no network detections.
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

## S0 findings (2026-10-14)

The spike scripts and raw results are throwaway and live outside the repo. The proposed list is
[m4-sigma-spike/proposed-rules.txt](m4-sigma-spike/proposed-rules.txt). Nothing in `backend/app` changed.

### Source and tooling

| Item | Value |
|---|---|
| SigmaHQ pinned commit | `7d8b152a5fc062ebd309f62ae4d8276aca2786af` (2026-10-14); `rules/windows` has 2420 rules |
| Licence | The repo-root `LICENSE` only links to DRL 1.1; the text is not in the repo. Fetch `LICENSE.Detection.Rules.md` from `github.com/SigmaHQ/Detection-Rule-License` into the shipped ruleset. DRL requires keeping each rule's `author` and a link to the rule set, so ship rule files unmodified |
| pySigma | 1.5.1 core parses all 2420 rules in 2.7 s: 0 parse failures, 0 correlation or aggregation rules (every rule has one plain condition) |
| Status / level | test 2193, experimental 173, stable 54. high 1172, medium 1026, low 154, critical 58, informational 10 |
| Modifiers used | contains 2017, endswith 1935, all 618, startswith 269, windash 82, re 77, cidr 17, base64offset 7, fieldref 3, re flag `i` 2. `exists`, `gt`/`lt` are unused in `rules/windows` |
| Tree shape | `rule.detection.parsed_condition[0].parse()` already gives AND/OR/NOT over `field = value` leaves with `contains`, `all` and `windash` expanded (windash arrives as a `SigmaExpansion` value). S2 can compile that tree instead of walking selections |
| ATT&CK tags | This commit tags `attack.stealth` (809 files) and `attack.defense-impairment` (307) and has no `attack.defense-evasion`. The tag to `threat.tactic.name` table must know both |

### What the rules ask for, against our fields

Buckets: **a** servable today; **b** servable once S1 adds the parent and target fields; **c-partial** a field is
missing but the rule can still fire through its other branches (a missing leaf counts as false); **c-blocked**
cannot fire without the missing field; **d** category out of scope or unsupported construct. "Fields we carry" is
my reading of the catalog plus the populated fields below, not S2's mapping.

| Category (decision 6) | Rules | a | b | c-partial | c-blocked | d |
|---|---|---|---|---|---|---|
| process_creation | 1190 | 345 | 160 | 605 | 79 | 1 (`fieldref`) |
| file_event | 167 | 164 | 3 | | | |
| registry_set | 207 | 205 | | 2 | | |
| registry_add | 1 | 1 | | | | |
| registry_delete | 10 | 10 | | | | |
| network_connection | 51 | | | | 51 | |
| dns_query | 22 | 22 | | | | |
| create_remote_thread | 11 | 1 | 5 | 2 | 3 | |
| **In scope** | **1659** | **748** | **168** | **609** | **133** | **1** |

- Shippable (a or b, status stable or test): **842** rules (692 a, 150 b). The b rules need `ParentImage` (154 of
  168), `ParentCommandLine` (34) and `TargetImage` (5). The 842 use 12 Sigma field names in all: Image,
  CommandLine, TargetObject, TargetFilename, Details, ParentImage, ParentCommandLine, QueryName, EventType,
  TargetImage, SourceImage, SourceFilename.
- Outside decision 6 but servable by events we have or specify: `registry_event` 32 rules (27 a), `file_delete`
  12 (10 a), `file_rename` 1 (a). The other 716 are out: image_load 100, process_access 23, 593 in other
  categories (ps_script, Security and System channels, pipe_created, driver_load, ...).
- c-partial rules degrade quietly. 586 rules use `OriginalFileName`, usually OR-ed with `Image|endswith`, so they
  still catch the binary under its own name and miss a renamed one. 22 c-partial rules have the missing field
  under a `not` filter and would over-match; keep those out of the shipped set.

Top 15 missing fields among the 742 c rules. "Using" counts a rule for every missing field it uses; "unblocks
alone" counts c-blocked rules that become satisfiable if only that field were added.

| Missing field (Sigma name) | c rules using | c-blocked using | Unblocks alone |
|---|---|---|---|
| `process.pe.original_file_name` (OriginalFileName) | 586 | 41 | 33 |
| `process.pe.description` | 70 | 17 | 15 |
| `process.pe.product` | 47 | 16 | 14 |
| `network.direction` (Initiated) | 41 | 41 | 6 |
| `process.*` on `network-connection` (Image) | 41 | 41 | 3 |
| file or process hashes (Hashes) | 39 | 4 | 4 |
| `process.integrity_level` (IntegrityLevel; in the catalog, never populated) | 26 | 24 | 21 |
| `destination.domain` on `network-connection` flows | 20 | 20 | 6 |
| `process.pe.company` | 19 | 11 | 9 |
| `user.name` (User) | 16 | 11 | 6 |
| `process.working_directory` | 8 | 2 | 1 |
| `process.*` on `network-connection` (CommandLine, ParentImage) | 4 | 4 | 0 |
| `tartarus.inject.start_module` (StartModule) | 2 | 2 | 2 |
| `process.pe.file_version` | 2 | 2 | 1 |
| `process.parent.user` | 2 | 2 | 0 |

PE version info (`pe.*`) and hashes need the image file, which the report does not carry per process.

### What the real analyses contain (OpenSearch, analyses 144 / 45 / 193)

| Sigma category | `event.action` | 144 | 45 | 193 | Populated on every event of the action |
|---|---|---|---|---|---|
| process_creation | process-created | 10 | 1 | 11 | `process.{pid,name,executable,command_line,entity_id}`, `process.parent.{pid,name}`; no parent path or command line; `process.start` on 13 of 22 |
| file_event | file-created | 8 | 1 | 7 | `file.{path,name}`, full `process.*`; `file.extension` on half. `file-written` (1 each) has no category |
| registry_set | reg-value-set | 14 | 1 | 14 | `registry.{path,hive,key,value,data.type,data.strings}`, `process.*` |
| registry_add | reg-key-created | 1 | 1 | 1 | `registry.{path,hive,key}`, `process.*` |
| registry_delete | reg-value-deleted | 5 | 0 | 5 | `registry.{path,hive,key,value}`, `process.*` |
| network_connection | network-connection | 343 | 210 | 381 | `source.{ip,port}`, `destination.{ip,port}`, `network.transport` only. All 934 are `cape.network` pcap flows: no `process.*`, no `destination.domain` |
| dns_query | dns-query | 6 | 6 | 6 | `dns.question.name`; `process.*` on 2 of 6 per analysis |
| create_remote_thread | none | 0 | 0 | 0 | |
| image_load | none | 0 | 0 | 0 | |
| process_access | none | 0 | 0 | 0 | |
| no category | api-call 18860 / 473 / 12728; signature-matched 20 / 12 / 18; http-request 2 each; process-terminated 3 / 2 / 3 | | | | |

- Parent resolution for S1 is feasible: for all 22 `process-created` events the parent pid maps to a process
  whose executable and command line appear in the same analysis's calls (22 of 22; a pid lookup that ignores
  pid reuse).
- No `connect` or `WSAConnect` call appears in any of the three analyses, so no network event is attributed to a
  process; every one is a pcap flow.
- All 113 `NtCreateThreadEx` and `CreateRemoteThreadEx` calls target the calling process (`ProcessHandle`
  `0xffffffff`, `ProcessId` = own pid), so no `inject-*` event is emitted, which is correct. They carry
  `StartAddress` and `Module` (Nt) or `StartRoutine` (Ex).
- **None of the 1658 in-scope rules that the naive matcher compiles fires on any real event** (all three analyses
  are the benign sample). The Tartarus-authored rule of decision 1 is what the e2e needs; the shipped set cannot
  be shown to work on these runs.

### Decision 6: image_load and process_access

| Category | Rules | Evidence | Verdict |
|---|---|---|---|
| image_load | 100 (95 use `ImageLoaded`) | 810 of 818 `ImageLoaded` patterns contain a backslash, so they need a full path. `LdrLoadDll` `FileName` is a bare name for most calls: full path on 140 of 472 (144), 4 of 9 (45), 97 of 281 (193). A full path would have to be guessed from the DLL search order. `LdrLoadDll` sees explicit loads only, not the import mappings Sysmon event 7 reports. 25 rules also need signature, hash or PE info | **Out.** A derived event would name a path nobody observed or miss most loads, and rules that filter on a load path would then misfire |
| process_access | 23 | 22 need `GrantedAccess` or `CallTrace`. No `NtOpenProcess` call exists in any analysis (`NtOpenProcessToken` and `NtOpenThread` only) | **Out.** Nothing to derive from |
| create_remote_thread | 11 | 6 servable after S1 (5 b, 1 a); no events in the real runs, and a call on the own process must not derive one (the existing rule is right) | **Keep**, with no hits expected until a real injector runs |

Both stay listed on the Rules page as an unsupported category. Re-open image_load only if capemon reports the
module path of every load, which is a capemon change and not a derivation.

### Decision 2: reuse the ECS pipeline or write an own one

pySigma's ECS Windows pipeline is `sigma.pipelines.elasticsearch.windows.ecs_windows`, shipped in
`pysigma-backend-elasticsearch` 2.1.1. It imports only core pySigma and runs without the backend, but its main
field table is a dict inside the function (it can be applied, not read as a table), and the package brings the
Elasticsearch backend, which decision 2 rules out. `pysigma-pipeline-sysmon` handles Sysmon event ids, not ECS
fields.

Output of the ECS pipeline on the 1659 in-scope rules (3893 field uses):

| Output | Uses | Share | Problem for us |
|---|---|---|---|
| a field in our catalog as is | 1395 | 36% | none |
| `process.executable.caseless` | 1137 | 29% | `.caseless` is a Winlogbeat sub-field; our index has none |
| an ECS name our catalog lacks | 1102 | 28% | `process.pe.*` 724, `process.parent.executable.caseless` 251 (S1 field, wrong suffix), `network.direction`, `user.name`, ... |
| `winlog.event_data.<Field>` fallback | 259 | 7% | silent: `Details` 160 (ours is `registry.data.strings`), `Hashes` 39, `IntegrityLevel` 26, `TargetImage` 9, `CommandLine` outside process_creation 8, `EventType` 4 |

**Recommendation: a small own pipeline** in `app/rules/`, built from the field catalog, using pySigma core
(`ProcessingPipeline` with `FieldMappingTransformation`) and nothing else.
- Reusing the ECS pipeline still needs five fix-ups (strip `.caseless`, remap `Details`, map `CommandLine` for the
  other categories, map `TargetImage`, derive `EventType`), which is more code than the table: the shippable
  rules use 12 Sigma field names.
- The ECS fallback prefixes every unknown field with `winlog.event_data.`, so a rule on a field we lack looks
  valid and never fires. Decision 9 needs the opposite: an unmapped field makes the rule invalid, with the field
  named. An own pipeline with no fallback does that by construction.
- One source of truth (rule 3): the table reads the catalog, and there is no dependency on a backend package.
- Keep ECS names as the targets, so names agree with the ECS pipeline wherever it is right. A dev-only test can
  compare the 12 mapped names against `ecs_windows` and list the deliberate differences.

### Cost of matching (naive matcher, one Python 3.12 process, AMD Ryzen 7 7700X, 20 000 events)

Median of 3 runs. "Full" is analysis 144 repeated to 20 000 events (393 carry a Sigma category, the rest are
`api-call`). "Dense" is only the Sigma-category events of the three analyses, repeated to 20 000. Parse and
compile of 60 rules took 0.06 s; of 842 rules 0.92 s.

| Strategy | 60 rules, full | 60 rules, dense | 842 rules, full | 842 rules, dense |
|---|---|---|---|---|
| Category index (action to category to rules) | 0.004 s, 0.22 us/event | 0.062 s, 3.1 us | 0.042 s, 2.1 us | 1.22 s, 61 us |
| No index, category checked per rule | 0.017 s, 0.83 us | 0.077 s, 3.8 us | 0.225 s, 11 us | 1.44 s, 72 us |
| No category at all (every rule on every event) | 2.63 s, 131 us | 1.77 s, 89 us | 53.3 s, 2667 us | 35.6 s, 1780 us |

- The full-stream gain of the index is a factor of 4 to 5 over a per-rule category check, and 600 to 1300 over
  testing every rule on every event. On a stream where every event has a category the index gains little (1.2x),
  because process-created events still meet 472 process_creation rules.
- Limits: the matcher is crude (no suppression, no regex length cap, no alert construction, `ParentImage` by pid
  lookup) and no rule fires, so the cost of building an alert is not measured; non-matching rules mostly fail on
  their first leaf, and a hit-heavy stream costs more. Real runs are mostly `api-call` events, which the index
  skips.

### Consequences for the plan

- S1: besides the fields of decision 4, `network.direction` is cheap (capemon `connect` is outbound by
  definition) and unblocks 6 network rules, but the 41 `Image`-based network rules stay blocked while flows are
  pcap-only. M4 should not promise network_connection detections.
- S2: compile the tree from `parse()`. List `fieldref` (3 rules, 1 in scope) as unsupported, or support it. Add
  `windash` expansion and the regex `i` flag to the modifier list of the spec.
- S3: ship the DRL 1.1 text, and map the `stealth` and `defense-impairment` tags.
- Candidate amendment to decision 6, not applied here: add `registry_event`, `file_delete` and `file_rename`
  (38 more a rules), since `reg-*` and `file-deleted`/`file-moved` events exist or are specified.
