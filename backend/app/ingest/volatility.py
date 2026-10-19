"""Turns the Volatility3 output the memory step leaves in `memory/` into `memory-finding` events.

Findings come from `windows.malware.malfind` and `windows.malware.hollowprocesses`. Each is an
event in lane `memory` and also raises a detection (`rule.ruleset: volatility`, severities in
`app.ingest.volatility_mapping`) that points at it. `windows.pslist` and `windows.cmdline` are
context for `process.name` and `process.command_line` and never become events: the process
events come from capemon and Sysmon.

Time: a finding has no time of its own (the dump is taken when the run is over), so every event
sits at `info.ended`, or at the analysis start when the report has no end.

Process: `process.entity_id` is built by capemon's own `process_fields` from the report's
`behavior.processes`, so a finding and the process's capemon events share an entity id. A pid the
report has no process for keeps a start-less id and takes its name from the plugin output.

Noise: the monitor's own pages (`app.ingest.volatility_noise`) are dropped and counted in
`VolatilityNormalizer.dropped`; rows of processes outside the run are not seen here, the producer
runs the plugins on the run's pids only. Event ids follow the row's position in its plugin file,
so a noise rule changing does not renumber the other findings.

No `memory/run.json` is no memory step: no events, no error. A plugin that failed or left no
usable file is skipped and the others are used.
"""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from app.ingest import volatility_mapping as mapping
from app.ingest.capemon_calls import read_processes
from app.ingest.clock import analysis_ended, guest_clock_offset
from app.ingest.ecs import (
    EventFactory,
    ProcessIdentity,
    SourceRecord,
    process_fields,
    related_events,
)
from app.ingest.protocol import IngestContext
from app.ingest.volatility_noise import MONITOR_PAGE, is_monitor_page
from app.ingest.volatility_output import ProcessTable, memory_folder, read_rows, read_run

SOURCE = "volatility"
SOURCE_FILE = "memory"
ROW_CAP = 5000
MALFORMED_ROW = "malformed-row"
ROW_CAP_EXCEEDED = "row-cap"


class VolatilityNormalizer:
    """The memory findings of one analysis.

    `dropped` counts what the last `normalise` call left out, by reason (`monitor-page`,
    `malformed-row`, `row-cap`); it is complete once the iterator is exhausted, and belongs to
    one ingest at a time.
    """

    source = SOURCE

    def __init__(self) -> None:
        self.dropped: Counter[str] = Counter()

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        dropped: Counter[str] = Counter()
        self.dropped = dropped
        folder = memory_folder(context.analysis_dir)
        run = None if folder is None else read_run(folder)
        if folder is None or run is None:
            return
        processes = _ProcessLabels(report, context, ProcessTable.read(folder, run))
        when = analysis_ended(report) or context.started_at
        factory = EventFactory(context, source=SOURCE, source_file=SOURCE_FILE, module=SOURCE)
        for plugin in mapping.RULES:
            rows = read_rows(folder, run, plugin)
            dropped[ROW_CAP_EXCEEDED] += max(0, len(rows) - ROW_CAP)
            for finding in _findings(plugin, rows[:ROW_CAP], dropped):
                yield from _events(factory, finding, processes.section(finding), when)
        _forget_zero_counts(dropped)


def _findings(plugin: str, rows: list[Any], dropped: Counter[str]) -> Iterator[mapping.Finding]:
    for index, row in enumerate(rows):
        finding = mapping.read_finding(plugin, index, row)
        if finding is None:
            dropped[MALFORMED_ROW] += 1
        elif is_monitor_page(finding.row):
            dropped[MONITOR_PAGE] += 1
        else:
            yield finding


def _forget_zero_counts(counts: Counter[str]) -> None:
    for reason in [reason for reason, count in counts.items() if count == 0]:
        del counts[reason]


def _events(
    factory: EventFactory, finding: mapping.Finding, process: dict[str, Any], when: datetime
) -> Iterator[dict[str, Any]]:
    label = mapping.process_label(finding, process.get("name"))
    source_file = f"{SOURCE_FILE}/{finding.plugin}"
    memory = {"memory": mapping.memory_section(finding)}
    observed = factory.build(
        mapping.finding_shape(finding),
        SourceRecord(finding.index, when, finding.row, source_file=source_file),
        mapping.finding_summary(finding, label),
        tartarus=memory,
        process=process,
    )
    yield observed
    detected = {**memory, "detection": _detection_match(finding)}
    yield factory.build(
        mapping.detection_shape(finding),
        SourceRecord(finding.index, when, finding.row, source_file=f"{source_file}#detection"),
        mapping.detection_summary(finding, label),
        severity=finding.severity,
        tartarus=detected,
        process=process,
        rule=mapping.rule_section(finding),
        threat=mapping.threat_section(finding),
        related=related_events(observed["event"]["id"]),
    )


def _detection_match(finding: mapping.Finding) -> dict[str, str]:
    match = mapping.match_text(finding)
    return {} if match is None else {"match": match}


class _ProcessLabels:
    """`process.*` of a finding: capemon's identity of the pid, completed from the plugin tables."""

    def __init__(
        self, report: Mapping[str, Any], context: IngestContext, table: ProcessTable
    ) -> None:
        offset = guest_clock_offset(report, context.host_registrations)
        # The dump shows the last process to hold a pid, so a reused pid resolves to the last.
        self._monitored = {
            process.identity.pid: process.identity for process in read_processes(report, offset)
        }
        self._table = table
        self._analysis_id = context.analysis_id

    def section(self, finding: mapping.Finding) -> dict[str, Any]:
        known = self._monitored.get(finding.pid) or ProcessIdentity(pid=finding.pid)
        identity = replace(
            known,
            name=known.name or self._table.names.get(finding.pid) or finding.process_name,
            command_line=known.command_line or self._table.command_lines.get(finding.pid),
        )
        return process_fields(identity, self._analysis_id)
