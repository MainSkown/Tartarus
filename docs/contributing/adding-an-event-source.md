# Adding an event source

An event source is an input whose records become events in the event index: CAPE's API calls, its
network and signature output, Sysmon, Defender, Volatility and so on. Each one has a normaliser that
maps its records to ECS event documents. The event document, the field list and the mapping from
sources are in the [data model](../specs/data-model.md). This page is the working order for adding one.

## The normaliser interface

The interface is `Normalizer` in `backend/app/ingest/protocol.py`, a `typing.Protocol`:

- `source: str` names the normaliser (`capemon`, `sysmon`, ...). It is part of every event id.
- `normalise(report, context)` takes the CAPE `report.json` as a mapping and an `IngestContext`, and
  yields event dicts.

`IngestContext` (same file) carries the analysis id, the start time (timezone-aware UTC, refused if
naive), the host's process registrations, and `analysis_dir`. The last is where sources that are not
in `report.json` leave their files, such as `sysmon/sysmon.xml` and `aux/defender.xml`.

Three rules come with the protocol, and the contract test checks them:

- It must not raise on an unknown or malformed record. Skip the part it cannot map and keep the rest.
- It must not change `report`.
- The same input must give the same output, with unique ids and increasing sequence numbers.

The built-in normalisers are, with their modules:

| Class | Module |
|---|---|
| `CapemonNormalizer` | `backend/app/ingest/capemon.py` |
| `CapeNetworkNormalizer` | `backend/app/ingest/cape_network.py` |
| `CapeSignaturesNormalizer` | `backend/app/ingest/cape_signatures.py` |
| `SysmonNormalizer` | `backend/app/ingest/sysmon.py` |
| `DefenderNormalizer` | `backend/app/ingest/defender.py` |
| `VolatilityNormalizer` | `backend/app/ingest/volatility.py` |

## Build events with the shared helpers

Do not write the event dict by hand. Use `EventFactory` in `backend/app/ingest/ecs.py`:

- `EventFactory(context, source=..., source_file=..., module=..., phase=...)` numbers the events in
  build order and builds their ids.
- `EventFactory.build(shape, record, summary, *, severity=0, tartarus=None, **sections)` returns one
  event. `shape` is an `EventShape` (action, categories, types, lane, dataset, kind, outcome), and
  `record` is a `SourceRecord` (index, timestamp, raw record, optional `source_file`).
- `lane` must be one of `LANES`: `process`, `file`, `registry`, `network`, `memory`, `api`.

Shared helpers in the same module are `process_fields`, `file_fields`, `registry_fields`,
`severity_level`, `related_events`, `truncate` and `format_timestamp`. Reading the report, use
`backend/app/ingest/reading.py` (`to_int`, `text_or_none`, `mapping_list`, `section`) rather than new
parsing code. A helper that appears in a third normaliser is the signal to move it there.

## Register it

Add the normaliser to `default_normalizers()` in `backend/app/ingest/ingester.py`. The final report
runs that list. The normalisers have no required order. If one needs another's derived events, it
calls that normaliser's public `normalise`, as `cape_network.py` does with `CapemonNormalizer`.

Only `capemon` runs live, through `LiveCapemon` (`backend/app/ingest/live_capemon.py`, wired in
`backend/app/live/collector.py`). A source that appears only in the final report needs the normaliser
and its registration, and nothing live.

## Fields come from one table

Every field a normaliser writes must exist in the field catalogue, `FIELDS` in
`backend/app/search/fields.py`, a tuple of `FieldDefinition`. Add the field there and nowhere else:

- the index template (`backend/app/search/template.py`, `build_index_template`) builds its mappings from `FIELDS`;
- the query compiler (`backend/app/query/compiler.py`) and the autocomplete (`backend/app/query/fields_api.py`) read it too;
- `backend/tests/query/test_catalog_agreement.py` keeps the catalogue and the template in step;
- `assert_fields_catalogued` in `backend/tests/ingest/contract.py` fails a normaliser that writes an unknown field.

## Map it to Sigma

Sigma rules are converted with pySigma's ECS Windows pipeline in `backend/app/rules/mapping.py`. A
Sigma field such as `Image` or `CommandLine` maps to its ECS field through the tables there. Each
event's `event.action` also decides its Sigma `logsource` category, through `ACTION_CATEGORIES` and
`category_of` in `backend/app/rules/categories.py`. Add an action there if Sigma rules should match
it. The mapping table is in the [data model, Sigma field mapping](../specs/data-model.md#sigma-field-mapping).

## Test it, test first

1. Write the test first: `backend/tests/ingest/test_<source>.py`. The contract tests are parametrised
   over `NORMALIZERS` in `backend/tests/ingest/test_contract.py`, so add your normaliser there too.
2. Recorded data goes in `backend/tests/fixtures/cape/`: `report_full_trimmed.json`,
   `report_trimmed.json`, and the live logs under `live_logs_45/`. Each source has case modules beside
   its tests, such as `sysmon_cases.py`, `defender_cases.py` and `volatility_cases.py`.
3. `backend/tests/ingest/conftest.py` provides the `full_report` and `context` fixtures.
   `contract.py` provides `check_normalizer_contract` and `check_tolerates_junk`.
4. A live source is tested against a collector that gets its log in slices, as a live run writes it.
   `backend/tests/live/collector_support.py` has the fakes (`FakeSink`, `FakeStore`), `append`,
   `write_in_slices` and `wait_until`. `test_collector.py` shows the pattern.
5. Run `cd backend && uv run pytest tests/ingest -q`. If you changed the index or the catalogue, also
   run `make test-integration`, which starts OpenSearch.

The test layers are in [running the tests](running-the-tests.md).
