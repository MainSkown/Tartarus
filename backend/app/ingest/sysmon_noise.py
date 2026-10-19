"""Which Sysmon events describe the sample, and which are Windows' or CAPE's own.

Windows background is 85 to 99% of a log (docs/plans/m8-spikes/S1-findings.md, "Noise"), so the
analysis keeps what the sample did. An event is kept when

1. its acting process is in the sample's tree: a process capemon monitored (matched by pid and
   image name) or anything started by one (`ParentProcessGuid`), or
2. it names a sample process as the target (EID 8 and 10) and the actor is not CAPE's tooling, or
3. it names no process at all (the WMI events), or none that can be identified.

Everything else is dropped, with the reason counted: CAPE's tooling (the agent, `inject-*.exe`
and the analyzer-directory executables the injector is renamed to, `PPLinject`, `wevtutil`,
Sysmon's own binaries), or Windows background. The injector acting on the sample is CAPE
injecting its monitor, not an injection by the sample, so tooling never counts as an actor that
reaches the sample (a Sigma `create_remote_thread` rule would fire on every monitored process).
Inside a sample process, the monitor's own files (`CapeOutput.bin`, `capemon.yac`, `<pid>.ini`,
its DLL) are dropped as monitor artefacts.

Dropping a real sample event is worse than keeping some noise, so attribution errs towards
keeping: a process the log never saw start is matched by pid alone and an event without a process
id is kept.

When capemon monitored no process at all (Defender removed the sample before it ran, or the
monitor never attached) there is no tree to start from, so it is found in Sysmon's own process
creations (`sample_tree_of`): the processes whose image file name is the sample's, or whose
command line contains it (a dll opened by rundll32, a document by its viewer, a script by its
interpreter), and what they started. Everything outside it is dropped, as with a monitored tree:
a sample that never ran leaves no Sysmon event, one that ran while capemon was blind is still
seen. Only a report that names no sample keeps everything but the tooling.
"""

import re

from app.ingest.ecs import base_name
from app.ingest.sysmon_processes import (
    EventFields,
    ProcessLedger,
    SampleProcesses,
    SampleTree,
    Subject,
    acting_and_target,
)

TOOLING = "cape-tooling"
BACKGROUND = "windows-background"
MONITOR_ARTEFACT = "monitor-artefact"

TOOLING_IMAGES = frozenset(
    {
        "pythonw.exe",
        "wevtutil.exe",
        "sysmon.exe",
        "sysmon64.exe",
        "smaster.exe",
        "smaster64.exe",
    }
)
TOOLING_IMAGE_PREFIXES = ("pplinject", "inject-")
# The analyzer unpacks into `C:\<8 random characters>\` (letters, digits and underscores, as the
# real runs showed) and keeps its results in `C:\<6 to 10 random letters>\` (CAPE's analyzer
# constants.py); the injector is renamed per task.
ANALYZER_PATH = re.compile(
    r"^[A-Za-z]:\\[A-Za-z0-9_]{6,10}\\(?:bin|dll|data|lib|modules|CAPE)(?:\\|$)", re.I
)
MONITOR_PID_FILE = re.compile(r"^[A-Za-z]:\\\d+\.ini$")
# The event field that names the file an event touches, for the events that have one.
TOUCHED_PATH_FIELDS = {
    7: "ImageLoaded",
    11: "TargetFilename",
    23: "TargetFilename",
    26: "TargetFilename",
}


def is_tooling_image(image: str | None) -> bool:
    if image is None:
        return False
    name = base_name(image).casefold()
    return (
        name in TOOLING_IMAGES
        or name.startswith(TOOLING_IMAGE_PREFIXES)
        or ANALYZER_PATH.match(image) is not None
    )


def is_monitor_artefact(path: str | None) -> bool:
    return path is not None and (
        ANALYZER_PATH.match(path) is not None or MONITOR_PID_FILE.match(path) is not None
    )


def sample_tree_of(
    sample: SampleProcesses, ledger: ProcessLedger, sample_name: str | None
) -> SampleTree:
    """The sample's processes: capemon's, or, when it monitored none, the ones that launched
    `sample_name` according to the log itself."""
    if sample or sample_name is None:
        return SampleTree(sample, ledger)
    return SampleTree(sample, ledger, seeds=_launched_as(sample_name, ledger))


def _launched_as(sample_name: str, ledger: ProcessLedger) -> list[str]:
    wanted = sample_name.casefold()
    return [
        started.guid
        for started in ledger
        if not is_tooling_image(started.image)
        and (
            (started.image is not None and base_name(started.image).casefold() == wanted)
            or wanted in (started.command_line or "").casefold()
        )
    ]


class NoiseFilter:
    def __init__(self, tree: SampleTree, ledger: ProcessLedger) -> None:
        self._tree = tree
        self._ledger = ledger

    def reason_to_drop(self, event_id: int, fields: EventFields) -> str | None:
        """Why the event is not the sample's, or `None` when it is kept."""
        actor, target = acting_and_target(event_id, fields)
        if actor is None or not actor.identifiable:
            return None
        if self._tree.contains(actor):
            return self._artefact_reason(event_id, fields)
        if is_tooling_image(actor.image):
            return TOOLING
        if not self._tree.can_tell_background or self._tree.contains(target):
            return None
        return TOOLING if self._started_by_tooling(actor) else BACKGROUND

    def _artefact_reason(self, event_id: int, fields: EventFields) -> str | None:
        name = TOUCHED_PATH_FIELDS.get(event_id)
        return MONITOR_ARTEFACT if name and is_monitor_artefact(fields.get(name)) else None

    def _started_by_tooling(self, actor: Subject) -> bool:
        started = self._ledger.get(actor.guid)
        return started is not None and is_tooling_image(started.parent_image)
