"""Guest profiles: everything that differs between operating systems, as validated data.

A profile is a directory `<profiles dir>/<id>/` holding `profile.json` and the profile's own
`steps/`. Generic code reads a `Profile` and never branches on what the operating system is.
"""

import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from guest_engine.names import GENERATOR_NAMES

SCHEMA_VERSION = 1
PROFILE_FILE = "profile.json"
OWN_STEPS_DIR = "steps"

SLUG = re.compile(r"[a-z][a-z0-9-]{1,31}")
STEP_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
OPTION_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
TASK_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}")
MODULE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
PACKAGE_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
MEDIA_VERSION = re.compile(r"\d+\.\d+\.(?P<build>\d+)")
CAPE_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
SAMPLE_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
SOURCE_PLACEHOLDER = "{source}"
OUTPUT_PLACEHOLDER = "{output}"

PLATFORMS = ("windows", "linux", "darwin")
ARCHS = ("x64", "x86")
BOOT_MODES = ("uefi", "bios")
DISK_BUSES = ("sata", "scsi", "ide", "virtio")
CLOCKS = ("utc", "localtime")
MEDIA_KINDS = ("installer", "disk_image")
OPTION_TYPES = ("bool", "string", "choice", "secret")
PATH_SEPARATORS = {"windows": "\\", "posix": "/"}
PATH_STYLES = tuple(PATH_SEPARATORS)
SHUTDOWN_MODES = ("acpi", "agent-command")

# What each self-test signal is read from; the verdict function dispatches on the source.
SIGNAL_SOURCES = {
    "events.process": "events",
    "events.file": "events",
    "events.registry": "events",
    "report.present": "report",
    "report.dns_answer": "report",
    "report.child_process": "report",
    "storage.monitor_log": "storage",
}

MIN_VCPUS, MAX_VCPUS = 1, 8
MIN_RAM_MB, MAX_RAM_MB = 2048, 32768
MAX_PORT = 65535
DEFAULT_STEP_TIMEOUT_S = 600
DEFAULT_PERSONA = "default"


@dataclass(frozen=True)
class TagRule:
    """Adds `tag` to the guests whose media has a build of at least `build_min`."""

    build_min: int
    tag: str


@dataclass(frozen=True)
class Cape:
    platform: str
    tags: list[str]
    tag_rules: list[TagRule] = field(default_factory=list)

    def tags_for(self, media_version: str | None) -> list[str]:
        """The CAPE tags of a guest built from media of this version ("major.minor.build").

        The profile's own tags always apply; the first rule the media's build reaches adds its tag.
        A version with no readable build gets the profile's tags alone.
        """
        build = _build_of(media_version)
        rule = next((r for r in self.tag_rules if build is not None and build >= r.build_min), None)
        if rule is None or rule.tag in self.tags:
            return list(self.tags)
        return [*self.tags, rule.tag]


def _build_of(media_version: str | None) -> int | None:
    version = MEDIA_VERSION.fullmatch(media_version or "")
    return int(version["build"]) if version else None


@dataclass(frozen=True)
class Hardware:
    machine: str
    boot: str
    secure_boot: bool
    tpm: bool
    disk_bus: str
    nic_model: str
    clock: str
    persona: str = DEFAULT_PERSONA


@dataclass(frozen=True)
class Resources:
    vcpus: int
    ram_mb: int
    disk_gb: int
    min_disk_gb: int
    scratch_gb: int


@dataclass(frozen=True)
class Media:
    kinds: list[str]
    inspector: str | None


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    type: str
    default: Any
    help: str
    choices: list[str]
    requires_user_step: bool
    changeable_on_clone: bool


@dataclass(frozen=True)
class IdentityRule:
    label: str
    pattern: str
    reserved: list[str]
    generator: str
    optional: bool


@dataclass(frozen=True)
class Identity:
    account: IdentityRule
    machine: IdentityRule
    password: IdentityRule


@dataclass(frozen=True)
class Clone:
    computer_name_editable: bool


@dataclass(frozen=True)
class Condition:
    """Holds when the option equals `value`, or, with `negated`, when it does not."""

    option: str
    value: Any
    negated: bool = False

    def holds(self, option_values: Mapping[str, Any]) -> bool:
        return (option_values[self.option] == self.value) != self.negated

    def to_dict(self) -> dict[str, Any]:
        return {"option": self.option, ("not" if self.negated else "value"): self.value}


@dataclass(frozen=True)
class PipelineStep:
    step: str
    desktop: bool
    timeout_s: int
    weight: int
    when: Condition | None = None
    # What the build page tells the person watching while this step runs.
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["when"] = self.when.to_dict() if self.when else None
        return data


@dataclass(frozen=True)
class Pipelines:
    build: dict[str, list[PipelineStep]]
    clone: list[PipelineStep]


@dataclass(frozen=True)
class AgentReady:
    marker: str | None


@dataclass(frozen=True)
class Interactive:
    """How an analysis the analyst can watch is asked for: CAPE options and extra task fields."""

    options: str
    task_fields: dict[str, bool | int | str]


@dataclass(frozen=True)
class Agent:
    port: int
    path_style: str
    ready: AgentReady
    finish_dir: str
    work_root: str
    shutdown: str
    interactive: Interactive
    pre_snapshot: str | None

    @property
    def path_separator(self) -> str:
        return PATH_SEPARATORS[self.path_style]


@dataclass(frozen=True)
class Sample:
    """The benign test sample: built from `source` by the argument list `build`, which says where
    the source and the output go with the `{source}` and `{output}` arguments."""

    source: str
    build: list[str]
    output: str


@dataclass(frozen=True)
class Signal:
    id: str
    source: str
    path: str | None


@dataclass(frozen=True)
class Facts:
    script: str


@dataclass(frozen=True)
class Selftest:
    sample: Sample | None
    signals: list[Signal]
    facts: Facts | None
    extras: list[str]
    check_step: str | None = None


@dataclass(frozen=True)
class Badge:
    option: str
    value: Any
    label: str


@dataclass(frozen=True)
class Timeouts:
    agent_s: int
    idle_s: int
    shutdown_s: int


@dataclass(frozen=True)
class MediaRef:
    file: str
    variant: str | None
    version: str | None
    language: str | None
    arch: str


@dataclass(frozen=True)
class Adoption:
    """How to describe a guest that was built before the wizard existed and cannot be asked."""

    account: str
    machine: str
    password: str
    work_dir: str
    media: MediaRef
    options: dict[str, Any]


@dataclass(frozen=True)
class Profile:
    schema_version: int
    id: str
    display_name: str
    family: str
    cape: Cape
    arch: str
    hardware: Hardware
    resources: Resources
    media: Media
    options: list[Option]
    identity: Identity
    clone: Clone
    pipelines: Pipelines
    agent: Agent
    selftest: Selftest
    packages: list[str]
    badges: list[Badge]
    timeouts: Timeouts
    adoption: Adoption | None = None
    directory: Path | None = field(default=None, compare=False)
    step_search_path: tuple[Path, ...] = field(default=(), compare=False)

    def to_dict(self) -> dict[str, Any]:
        """The JSON form of the profile, which `parse_profile` reads back to an equal profile."""
        data = asdict(self)
        del data["directory"], data["step_search_path"]
        data["pipelines"] = {
            "build": {
                kind: [entry.to_dict() for entry in entries]
                for kind, entries in self.pipelines.build.items()
            },
            "clone": [entry.to_dict() for entry in self.pipelines.clone],
        }
        return data

    def option(self, key: str) -> Option | None:
        return next((option for option in self.options if option.key == key), None)

    def clone_changeable_options(self) -> set[str]:
        return {option.key for option in self.options if option.changeable_on_clone}

    def option_defaults(self) -> dict[str, Any]:
        return {option.key: option.default for option in self.options}

    def build_pipeline(
        self, media_kind: str, option_values: Mapping[str, Any]
    ) -> list[PipelineStep]:
        """The steps of a build of `media_kind` for these options, in order."""
        return self._applicable(self.pipelines.build[media_kind], option_values)

    def clone_pipeline(self, option_values: Mapping[str, Any]) -> list[PipelineStep]:
        """The steps of a clone with these options, in order."""
        return self._applicable(self.pipelines.clone, option_values)

    def _applicable(
        self, entries: list[PipelineStep], option_values: Mapping[str, Any]
    ) -> list[PipelineStep]:
        effective = {**self.option_defaults(), **option_values}
        return [entry for entry in entries if entry.when is None or entry.when.holds(effective)]

    def pipeline_entries(self) -> list[tuple[str, PipelineStep]]:
        """Every pipeline entry with the field path it was read from."""
        entries = [
            (f"pipelines.build.{kind}[{index}]", entry)
            for kind, steps in self.pipelines.build.items()
            for index, entry in enumerate(steps)
        ]
        return entries + [
            (f"pipelines.clone[{index}]", entry) for index, entry in enumerate(self.pipelines.clone)
        ]

    def step_references(self) -> list[tuple[str, str]]:
        """Every (field path, step name) the profile names, for the loader's existence check."""
        references = [(f"{path}.step", entry.step) for path, entry in self.pipeline_entries()]
        if self.agent.pre_snapshot:
            references.append(("agent.pre_snapshot", self.agent.pre_snapshot))
        if self.selftest.check_step:
            references.append(("selftest.check_step", self.selftest.check_step))
        return references

    def own_file_references(self) -> list[tuple[str, str]]:
        """Every (field path, relative path) of a file the profile ships in its own directory."""
        references = []
        if self.selftest.sample:
            references.append(("selftest.sample.source", self.selftest.sample.source))
        if self.selftest.facts:
            references.append(("selftest.facts.script", self.selftest.facts.script))
        return references

    def step_names(self) -> set[str]:
        return {step for _, step in self.step_references()}

    def step_path(self, name: str) -> Path | None:
        return find_step(name, self.step_search_path)


class ProfileError(ValueError):
    """A profile is unusable; `problems` maps each field path to why, `source` is the file."""

    def __init__(self, source: str, problems: dict[str, str]) -> None:
        details = "; ".join(
            f"{path}: {reason}" if path else reason for path, reason in problems.items()
        )
        super().__init__(f"{source}: {details}")
        self.source = source
        self.problems = problems


def _violation(value: str, rule: re.Pattern[str] | Sequence[str] | None) -> str | None:
    if isinstance(rule, re.Pattern):
        return None if rule.fullmatch(value) else f"must match {rule.pattern}"
    if rule is not None and value not in rule:
        return f"must be one of {', '.join(rule)}"
    return None


class _Reader:
    def __init__(self, data: object, path: str, problems: dict[str, str]) -> None:
        self._path = path
        self._problems = problems
        self._seen: set[str] = set()
        if isinstance(data, dict):
            self._data: dict[str, Any] = data
        else:
            self._data = {}
            problems.setdefault(path, "must be an object")

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._data))

    def fail(self, key: str, reason: str) -> None:
        self._problems.setdefault(self._child(key), reason)

    def value(self, key: str) -> Any:
        self._seen.add(key)
        return self._data.get(key)

    def _required_value(self, key: str) -> Any:
        value = self.value(key)
        if value is None:
            self.fail(key, "is required")
        return value

    def done(self) -> None:
        for key in self._data.keys() - self._seen:
            self.fail(key, "is not a known field")

    def string(
        self,
        key: str,
        *,
        rule: re.Pattern[str] | Sequence[str] | None = None,
        default: str | None = None,
        empty: bool = False,
    ) -> str:
        value = self.value(key) if default is not None else self._required_value(key)
        if value is None:
            return default or ""
        if not isinstance(value, str) or (not value and not empty):
            self.fail(key, "must be a non-empty string")
            return ""
        problem = _violation(value, rule)
        if problem:
            self.fail(key, problem)
        return value

    def choice(self, key: str, allowed: Sequence[str]) -> str:
        return self.string(key, rule=allowed)

    def optional_string(
        self, key: str, *, rule: re.Pattern[str] | Sequence[str] | None = None
    ) -> str | None:
        if self.value(key) is None:
            return None
        return self.string(key, rule=rule)

    def integer(
        self, key: str, *, minimum: int, maximum: int | None = None, default: int | None = None
    ) -> int:
        value = self.value(key) if default is not None else self._required_value(key)
        if value is None:
            return default or 0
        if isinstance(value, bool) or not isinstance(value, int):
            self.fail(key, "must be an integer")
        elif value < minimum or (maximum is not None and value > maximum):
            bounds = (
                f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
            )
            self.fail(key, f"must be {bounds}")
        else:
            return value
        return default or 0

    def boolean(self, key: str, *, default: bool | None = None) -> bool:
        value = self.value(key) if default is not None else self._required_value(key)
        if value is None:
            return bool(default)
        if not isinstance(value, bool):
            self.fail(key, "must be true or false")
            return False
        return value

    def string_list(
        self,
        key: str,
        *,
        rule: re.Pattern[str] | Sequence[str] | None = None,
        default: list[str] | None = None,
        non_empty: bool = False,
    ) -> list[str]:
        value = self.value(key) if default is not None else self._required_value(key)
        if value is None:
            return list(default or [])
        if not isinstance(value, list) or (non_empty and not value):
            self.fail(key, "must be a non-empty list" if non_empty else "must be a list")
            return []
        items = [self._list_item(key, index, item, rule) for index, item in enumerate(value)]
        for index, item in enumerate(items):
            if item in items[:index]:
                self.fail(f"{key}[{index}]", f"'{item}' is listed twice")
        return items

    def _list_item(
        self, key: str, index: int, item: object, rule: re.Pattern[str] | Sequence[str] | None
    ) -> str:
        if not isinstance(item, str) or not item:
            self.fail(f"{key}[{index}]", "must be a non-empty string")
            return ""
        problem = _violation(item, rule)
        if problem:
            self.fail(f"{key}[{index}]", problem)
        return item

    def object(self, key: str) -> "_Reader":
        return _Reader(self._required_value(key), self._child(key), self._problems)

    def optional_object(self, key: str) -> "_Reader | None":
        value = self.value(key)
        return None if value is None else _Reader(value, self._child(key), self._problems)

    def objects(self, key: str, *, non_empty: bool = False) -> "list[_Reader]":
        value = self._required_value(key)
        if value is None:
            return []
        if not isinstance(value, list) or (non_empty and not value):
            self.fail(key, "must be a non-empty list" if non_empty else "must be a list")
            return []
        return [
            _Reader(item, f"{self._child(key)}[{index}]", self._problems)
            for index, item in enumerate(value)
        ]

    def optional_objects(self, key: str) -> "list[_Reader]":
        return self.objects(key) if self.value(key) is not None else []

    def _child(self, key: str) -> str:
        return ".".join(part for part in (self._path, key) if part)


def option_value_problem(option: Option, value: Any) -> str | None:
    """Why `value` is not acceptable for `option`, or None."""
    if option.type == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if not isinstance(value, str):
        return "must be a string"
    if option.type == "choice" and value not in option.choices:
        return f"must be one of {', '.join(option.choices)}"
    return None


def _tag_rule(reader: _Reader) -> TagRule:
    rule = TagRule(reader.integer("build_min", minimum=1), reader.string("tag", rule=CAPE_TAG))
    reader.done()
    return rule


def _tag_rules(readers: list[_Reader]) -> list[TagRule]:
    rules = [_tag_rule(reader) for reader in readers]
    for index in range(1, len(rules)):
        if rules[index].build_min >= rules[index - 1].build_min:
            readers[index].fail("build_min", "is never reached: list the highest build_min first")
    return rules


def _cape(reader: _Reader) -> Cape:
    cape = Cape(
        reader.choice("platform", PLATFORMS),
        reader.string_list("tags", rule=CAPE_TAG),
        _tag_rules(reader.optional_objects("tag_rules")),
    )
    reader.done()
    return cape


def _hardware(reader: _Reader) -> Hardware:
    hardware = Hardware(
        machine=reader.string("machine"),
        boot=reader.choice("boot", BOOT_MODES),
        secure_boot=reader.boolean("secure_boot"),
        tpm=reader.boolean("tpm"),
        disk_bus=reader.choice("disk_bus", DISK_BUSES),
        nic_model=reader.string("nic_model"),
        clock=reader.choice("clock", CLOCKS),
        persona=reader.string("persona", rule=SLUG, default=DEFAULT_PERSONA),
    )
    if hardware.secure_boot and hardware.boot != "uefi":
        reader.fail("secure_boot", "needs boot to be uefi")
    reader.done()
    return hardware


def _resources(reader: _Reader) -> Resources:
    resources = Resources(
        vcpus=reader.integer("vcpus", minimum=MIN_VCPUS, maximum=MAX_VCPUS),
        ram_mb=reader.integer("ram_mb", minimum=MIN_RAM_MB, maximum=MAX_RAM_MB),
        disk_gb=reader.integer("disk_gb", minimum=1),
        min_disk_gb=reader.integer("min_disk_gb", minimum=1),
        scratch_gb=reader.integer("scratch_gb", minimum=0, default=0),
    )
    if resources.disk_gb < resources.min_disk_gb:
        reader.fail("disk_gb", f"is below min_disk_gb ({resources.min_disk_gb})")
    reader.done()
    return resources


def _media(reader: _Reader) -> Media:
    media = Media(
        kinds=reader.string_list("kinds", rule=MEDIA_KINDS, non_empty=True),
        inspector=reader.optional_string("inspector", rule=MODULE_NAME),
    )
    reader.done()
    return media


def _option(reader: _Reader) -> Option:
    type_ = reader.choice("type", OPTION_TYPES)
    choices = reader.string_list("choices", default=[])
    if type_ == "choice" and not choices:
        reader.fail("choices", "is required for a choice option")
    if type_ != "choice" and choices:
        reader.fail("choices", "is only allowed for a choice option")
    option = Option(
        key=reader.string("key", rule=OPTION_KEY),
        label=reader.string("label"),
        type=type_,
        default=reader.value("default"),
        help=reader.string("help"),
        choices=choices,
        requires_user_step=reader.boolean("requires_user_step", default=False),
        changeable_on_clone=reader.boolean("changeable_on_clone", default=False),
    )
    if option.default is None:
        reader.fail("default", "is required")
    elif problem := option_value_problem(option, option.default):
        reader.fail("default", problem)
    reader.done()
    return option


def _identity_rule(reader: _Reader, default_label: str) -> IdentityRule:
    pattern = reader.string("pattern")
    try:
        re.compile(pattern)
    except re.error as error:
        reader.fail("pattern", f"is not a valid regular expression ({error})")
    rule = IdentityRule(
        label=reader.string("label", default=default_label),
        pattern=pattern,
        reserved=reader.string_list("reserved", default=[]),
        generator=reader.choice("generator", sorted(GENERATOR_NAMES)),
        optional=reader.boolean("optional", default=True),
    )
    reader.done()
    return rule


def _identity(reader: _Reader) -> Identity:
    identity = Identity(
        account=_identity_rule(reader.object("account"), "Username"),
        machine=_identity_rule(reader.object("machine"), "Computer name"),
        password=_identity_rule(reader.object("password"), "Password"),
    )
    reader.done()
    return identity


def _clone(reader: _Reader) -> Clone:
    if reader.value("changeable_options") is not None:
        reader.fail("changeable_options", "is gone: set changeable_on_clone on the option instead")
    clone = Clone(computer_name_editable=reader.boolean("computer_name_editable"))
    reader.done()
    return clone


def _condition(reader: _Reader | None) -> Condition | None:
    if reader is None:
        return None
    option = reader.string("option", rule=OPTION_KEY)
    equals, differs = reader.value("value"), reader.value("not")
    if (equals is None) == (differs is None):
        reader.fail("", "needs exactly one of value or not")
    reader.done()
    return Condition(option, equals if differs is None else differs, negated=differs is not None)


def _pipeline_step(reader: _Reader) -> PipelineStep:
    entry = PipelineStep(
        step=reader.string("step", rule=STEP_NAME),
        desktop=reader.boolean("desktop", default=False),
        timeout_s=reader.integer("timeout_s", minimum=1, default=DEFAULT_STEP_TIMEOUT_S),
        weight=reader.integer("weight", minimum=1, default=1),
        when=_condition(reader.optional_object("when")),
        description=reader.optional_string("description"),
    )
    reader.done()
    return entry


def _pipeline(reader: _Reader, key: str, *, non_empty: bool) -> list[PipelineStep]:
    entries = [_pipeline_step(entry) for entry in reader.objects(key, non_empty=non_empty)]
    for index, entry in enumerate(entries):
        if entry.step in [earlier.step for earlier in entries[:index]]:
            reader.fail(f"{key}[{index}].step", f"'{entry.step}' appears twice in this pipeline")
    return entries


def _pipelines(reader: _Reader, media_kinds: list[str]) -> Pipelines:
    build_reader = reader.object("build")
    build = {kind: _pipeline(build_reader, kind, non_empty=True) for kind in build_reader}
    for kind in build:
        if kind not in media_kinds:
            build_reader.fail(kind, "is not one of the profile's media kinds")
    for kind in media_kinds:
        if kind not in build:
            build_reader.fail(kind, "is required: the profile accepts this media kind")
    pipelines = Pipelines(build=build, clone=_pipeline(reader, "clone", non_empty=False))
    reader.done()
    return pipelines


def _task_fields(reader: _Reader) -> dict[str, bool | int | str]:
    fields = reader.optional_object("task_fields")
    if fields is None:
        return {}
    task_fields: dict[str, bool | int | str] = {}
    for name in fields:
        value = fields.value(name)
        if not TASK_FIELD.fullmatch(name):
            fields.fail(name, f"must be a lower-case identifier ({TASK_FIELD.pattern})")
        elif not isinstance(value, bool | int | str):
            fields.fail(name, "must be true or false, a whole number or text")
        else:
            task_fields[name] = value
    return task_fields


def _interactive(reader: _Reader) -> Interactive:
    interactive = Interactive(
        options=reader.string("options", empty=True), task_fields=_task_fields(reader)
    )
    reader.done()
    return interactive


def _agent(reader: _Reader) -> Agent:
    ready_reader = reader.object("ready")
    ready = AgentReady(ready_reader.optional_string("marker"))
    ready_reader.done()
    agent = Agent(
        port=reader.integer("port", minimum=1, maximum=MAX_PORT),
        path_style=reader.choice("path_style", PATH_STYLES),
        ready=ready,
        finish_dir=reader.string("finish_dir"),
        work_root=reader.string("work_root"),
        shutdown=reader.choice("shutdown", SHUTDOWN_MODES),
        interactive=_interactive(reader.object("interactive")),
        pre_snapshot=reader.optional_string("pre_snapshot", rule=STEP_NAME),
    )
    reader.done()
    return agent


def _signal(reader: _Reader) -> Signal:
    signal_id = reader.string("id")
    expected_source = SIGNAL_SOURCES.get(signal_id, "")
    if signal_id and not expected_source:
        reader.fail("id", f"is not a known signal ({', '.join(SIGNAL_SOURCES)})")
    declared_source = reader.optional_string("source")
    if declared_source is not None and declared_source != expected_source:
        reader.fail("source", f"must be '{expected_source}' for {signal_id}")
    path = reader.optional_string("path")
    if expected_source == "storage" and path is None:
        reader.fail("path", "is required for a storage signal")
    if expected_source and expected_source != "storage" and path is not None:
        reader.fail("path", "is only for storage signals")
    reader.done()
    return Signal(signal_id, expected_source, path)


def _sample(reader: _Reader) -> Sample:
    sample = Sample(
        reader.string("source"),
        reader.string_list("build", non_empty=True),
        reader.string("output", rule=SAMPLE_FILE_NAME),
    )
    for placeholder in (SOURCE_PLACEHOLDER, OUTPUT_PLACEHOLDER):
        if sample.build.count(placeholder) != 1:
            reader.fail("build", f"must hold the argument {placeholder} exactly once")
    reader.done()
    return sample


def _selftest(reader: _Reader) -> Selftest:
    sample_reader = reader.optional_object("sample")
    sample = _sample(sample_reader) if sample_reader else None
    signal_readers = reader.objects("signals", non_empty=True)
    signals = [_signal(signal) for signal in signal_readers]
    for index, signal in enumerate(signals):
        if signal.id in [earlier.id for earlier in signals[:index]]:
            reader.fail(f"signals[{index}].id", f"'{signal.id}' is listed twice")
    facts_reader = reader.optional_object("facts")
    facts = Facts(facts_reader.string("script")) if facts_reader else None
    if facts_reader:
        facts_reader.done()
    selftest = Selftest(
        sample,
        signals,
        facts,
        reader.string_list("extras", default=[]),
        reader.optional_string("check_step", rule=STEP_NAME),
    )
    reader.done()
    return selftest


def _badges(reader: _Reader) -> list[Badge]:
    badges = []
    for badge_reader in reader.objects("badges"):
        badges.append(
            Badge(
                option=badge_reader.string("option", rule=OPTION_KEY),
                value=badge_reader.value("value"),
                label=badge_reader.string("label"),
            )
        )
        badge_reader.done()
    return badges


def _timeouts(reader: _Reader) -> Timeouts:
    timeouts = Timeouts(
        agent_s=reader.integer("agent_s", minimum=1),
        idle_s=reader.integer("idle_s", minimum=1),
        shutdown_s=reader.integer("shutdown_s", minimum=1),
    )
    reader.done()
    return timeouts


def _media_ref(reader: _Reader) -> MediaRef:
    media = MediaRef(
        file=reader.string("file"),
        variant=reader.optional_string("variant"),
        version=reader.optional_string("version"),
        language=reader.optional_string("language"),
        arch=reader.string("arch"),
    )
    reader.done()
    return media


def _adoption_options(reader: _Reader) -> dict[str, Any]:
    options = reader.value("options")
    if not isinstance(options, dict):
        reader.fail("options", "must be an object")
        return {}
    return options


def _adoption(reader: _Reader | None) -> Adoption | None:
    if reader is None:
        return None
    adoption = Adoption(
        account=reader.string("account"),
        machine=reader.string("machine"),
        password=reader.string("password"),
        work_dir=reader.string("work_dir"),
        media=_media_ref(reader.object("media")),
        options=_adoption_options(reader),
    )
    reader.done()
    return adoption


def _check_options(profile: Profile, problems: dict[str, str]) -> None:
    keys = [option.key for option in profile.options]
    for index, option in enumerate(profile.options):
        if option.key in keys[:index]:
            problems.setdefault(f"options[{index}].key", f"'{option.key}' is defined twice")


def _check_adoption(profile: Profile, problems: dict[str, str]) -> None:
    if profile.adoption is None:
        return
    for key, value in profile.adoption.options.items():
        option = profile.option(key)
        path = f"adoption.options.{key}"
        if option is None:
            problems.setdefault(path, f"'{key}' is not an option")
        elif problem := option_value_problem(option, value):
            problems.setdefault(path, problem)


def _check_option_value(
    profile: Profile, key: str, value: Any, paths: tuple[str, str], problems: dict[str, str]
) -> None:
    """`value` must be one the option `key` accepts; `paths` locate the key and the value."""
    key_path, value_path = paths
    option = profile.option(key)
    if option is None:
        problems.setdefault(key_path, f"'{key}' is not an option")
    elif value is None:
        problems.setdefault(value_path, "is required")
    elif problem := option_value_problem(option, value):
        problems.setdefault(value_path, problem)


def _check_badges(profile: Profile, problems: dict[str, str]) -> None:
    for index, badge in enumerate(profile.badges):
        paths = (f"badges[{index}].option", f"badges[{index}].value")
        _check_option_value(profile, badge.option, badge.value, paths, problems)


def _check_conditions(profile: Profile, problems: dict[str, str]) -> None:
    for path, entry in profile.pipeline_entries():
        if entry.when is not None:
            value_key = "not" if entry.when.negated else "value"
            paths = (f"{path}.when.option", f"{path}.when.{value_key}")
            _check_option_value(profile, entry.when.option, entry.when.value, paths, problems)


def parse_profile(data: object, source: str = PROFILE_FILE) -> Profile:
    """Validate `data` (the parsed `profile.json`); raise `ProfileError` naming every bad field."""
    problems: dict[str, str] = {}
    root = _Reader(data, "", problems)
    version = root.value("schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        root.fail("schema_version", f"must be {SCHEMA_VERSION}")
    media = _media(root.object("media"))
    profile = Profile(
        schema_version=SCHEMA_VERSION,
        id=root.string("id", rule=SLUG),
        display_name=root.string("display_name"),
        family=root.string("family"),
        cape=_cape(root.object("cape")),
        arch=root.choice("arch", ARCHS),
        hardware=_hardware(root.object("hardware")),
        resources=_resources(root.object("resources")),
        media=media,
        options=[_option(option) for option in root.objects("options")],
        identity=_identity(root.object("identity")),
        clone=_clone(root.object("clone")),
        pipelines=_pipelines(root.object("pipelines"), media.kinds),
        agent=_agent(root.object("agent")),
        selftest=_selftest(root.object("selftest")),
        packages=root.string_list("packages", rule=PACKAGE_NAME, non_empty=True),
        badges=_badges(root),
        timeouts=_timeouts(root.object("timeouts")),
        adoption=_adoption(root.optional_object("adoption")),
    )
    root.done()
    _check_options(profile, problems)
    _check_adoption(profile, problems)
    _check_badges(profile, problems)
    _check_conditions(profile, problems)
    if problems:
        raise ProfileError(source, problems)
    return profile


def derive_badges(profile: Profile, option_values: dict[str, Any]) -> list[str]:
    """The labels the profile's badge rules give to a guest with these option values."""
    return [
        badge.label
        for badge in profile.badges
        if badge.option in option_values and option_values[badge.option] == badge.value
    ]


def find_step(name: str, search_path: Sequence[Path]) -> Path | None:
    """The first executable file called `name` in the directories of `search_path`, in order."""
    for directory in search_path:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _missing_step_reason(name: str, search_path: Sequence[Path]) -> str:
    for directory in search_path:
        if (directory / name).is_file():
            return f"step '{name}' at {directory / name} is not executable"
    searched = ", ".join(str(directory) for directory in search_path)
    return f"no executable step '{name}' in {searched}"


def _own_file_problem(directory: Path, relative: str) -> str | None:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        return f"'{relative}' must be a relative path inside the profile directory"
    if not (directory / relative).is_file():
        return f"no such file {directory / relative}"
    return None


def _read_profile_json(file: Path) -> object:
    try:
        text = file.read_text()
    except FileNotFoundError:
        raise ProfileError(str(file), {"": "no such file"}) from None
    except OSError as error:
        raise ProfileError(str(file), {"": f"cannot be read ({error.strerror})"}) from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ProfileError(str(file), {"": f"not valid JSON ({error})"}) from None


def load_profile(directory: Path, generic_steps_dir: Path) -> Profile:
    """Load `directory/profile.json` and check that every step and self-test file it names exists.

    Steps are looked up in the profile's own `steps/` directory first, then in `generic_steps_dir`.
    """
    file = directory / PROFILE_FILE
    profile = parse_profile(_read_profile_json(file), source=str(file))
    search_path = (directory / OWN_STEPS_DIR, generic_steps_dir)
    problems: dict[str, str] = {}
    if profile.id != directory.name:
        problems["id"] = f"'{profile.id}' does not match its directory name '{directory.name}'"
    for path, step in profile.step_references():
        if find_step(step, search_path) is None:
            problems.setdefault(path, _missing_step_reason(step, search_path))
    for path, relative in profile.own_file_references():
        if problem := _own_file_problem(directory, relative):
            problems.setdefault(path, problem)
    if problems:
        raise ProfileError(str(file), problems)
    return replace(profile, directory=directory, step_search_path=search_path)


@dataclass(frozen=True)
class BrokenProfile:
    directory: Path
    message: str


@dataclass
class ProfileCatalog:
    profiles: dict[str, Profile] = field(default_factory=dict)
    broken: list[BrokenProfile] = field(default_factory=list)


def load_profiles(profiles_dir: Path, generic_steps_dir: Path) -> ProfileCatalog:
    """Load every profile directory; a bad one is listed as broken and does not stop the others."""
    catalog = ProfileCatalog()
    if not profiles_dir.is_dir():
        return catalog
    for directory in sorted(profiles_dir.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            profile = load_profile(directory, generic_steps_dir)
        except ProfileError as error:
            catalog.broken.append(BrokenProfile(directory, str(error)))
        else:
            catalog.profiles[profile.id] = profile
    return catalog
