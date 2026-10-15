"""Validation of a build or clone request against a profile and the registry (decision 3).

Both entry points collect every problem and raise `InvalidParameters` once; the state-dependent
refusals (the guest cap, a source that is not ready) are a `Conflict`, an unknown source a
`GuestNotFound`. Blank identity values are replaced by the profile's generator, so the returned
spec is fully resolved.
"""

import random
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.giveaways import find_giveaway
from guest_engine.names import generate
from guest_engine.profile import (
    MAX_RAM_MB,
    MAX_VCPUS,
    MIN_RAM_MB,
    MIN_VCPUS,
    SLUG,
    IdentityRule,
    MediaRef,
    Profile,
    option_value_problem,
)
from guest_engine.registry import MAX_GUESTS, Guest, GuestIdentity, GuestResources, GuestSpec

RESERVED_GUEST_NAMES = frozenset({"kvm"})  # the CAPE section that lists the machines
BUILD_FIELDS = ("name", "profile", "media", "options", "identity", "resources")
CLONE_FIELDS = ("name", "options", "identity", "resources")
IDENTITY_ROLES = ("account", "machine", "password")
GENERATION_ATTEMPTS = 20
NAME_RULE = "must be 2 to 32 lower-case letters, digits or hyphens, starting with a letter"

type Problems = dict[str, str]


@dataclass(frozen=True)
class ValidationContext:
    """The state a request is judged against: installed profiles, existing guests, scanned media."""

    profiles: Mapping[str, Profile]
    guests: Sequence[Guest]
    media: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class ValidatedBuild:
    spec: GuestSpec

    @property
    def media_kind(self) -> str:
        return str(self.spec.media_kind)


def variant_id(variant: Mapping[str, Any]) -> str:
    """How a request names one of the variants a scan listed: its index, else its name."""
    return str(variant["index"] if "index" in variant else variant["name"])


def _fail(problems: Problems, path: str, reason: str) -> None:
    problems.setdefault(path, reason)


def _object(params: Mapping[str, Any], key: str, problems: Problems) -> Mapping[str, Any]:
    value = params.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _fail(problems, key, "must be an object")
        return {}
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: Collection[str], problems: Problems) -> None:
    for key in raw:
        if key not in allowed:
            _fail(problems, key, "is not a known field")


def _request(params: object) -> Mapping[str, Any]:
    if not isinstance(params, Mapping):
        raise InvalidParameters({"request": "must be a JSON object"})
    return params


def _refuse_when_full(context: ValidationContext) -> None:
    if len(context.guests) >= MAX_GUESTS:
        raise Conflict(
            f"there are already {MAX_GUESTS} guests, the most there can be; delete one first"
        )


def _check_name(params: Mapping[str, Any], context: ValidationContext, problems: Problems) -> str:
    name = params.get("name")
    if not isinstance(name, str) or not SLUG.fullmatch(name):
        _fail(problems, "name", NAME_RULE)
        return ""
    if name in RESERVED_GUEST_NAMES:
        _fail(problems, "name", "is reserved")
    elif any(guest.name == name for guest in context.guests):
        _fail(problems, "name", "is already used by another guest")
    return name


def _plain_file_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith(".")
        and not re.search(r"[/\\\x00]", value)
    )


def _resolve_variant(entry: Mapping[str, Any], raw: object, problems: Problems) -> str | None:
    listed = [variant_id(variant) for variant in entry.get("variants") or []]
    if not listed:
        if raw is not None:
            _fail(problems, "media.variant", "is not offered: this medium lists no variants")
        return None
    chosen = str(raw) if isinstance(raw, str | int) and not isinstance(raw, bool) else None
    if chosen is None:
        _fail(problems, "media.variant", f"is required: one of {', '.join(listed)}")
    elif chosen not in listed:
        _fail(problems, "media.variant", f"must be one of {', '.join(listed)}")
    return chosen


def _resolve_media(
    raw: Mapping[str, Any], profile: Profile, context: ValidationContext, problems: Problems
) -> tuple[MediaRef, str]:
    nothing = (MediaRef("", None, None, None, ""), "")
    file = raw.get("file")
    if not _plain_file_name(file):
        _fail(problems, "media.file", "is required and must be a plain file name")
        return nothing
    listed = [entry for entry in context.media if entry.get("file") == file]
    if not listed:
        _fail(problems, "media.file", "is not in the installation media list")
        return nothing
    recognised = [entry for entry in listed if entry.get("profile") == profile.id]
    if not recognised:
        _fail(problems, "media.file", f"is not media for the {profile.id} profile")
        return nothing
    entry = recognised[0]
    kind = entry.get("kind")
    if kind not in profile.pipelines.build:
        buildable = " or ".join(profile.pipelines.build)
        found = f"the scan found '{kind}'" if kind else "the scan did not name one"
        _fail(
            problems,
            "media.file",
            f"has no usable kind: {found}; {profile.id} builds from {buildable}",
        )
        return nothing
    variant = _resolve_variant(entry, raw.get("variant"), problems)
    media = MediaRef(
        str(file), variant, entry.get("version"), entry.get("language"), entry.get("arch")
    )
    return media, str(kind)


def _resolve_options(
    raw: Mapping[str, Any],
    profile: Profile,
    base: Mapping[str, Any],
    locked: Collection[str],
    problems: Problems,
) -> dict[str, Any]:
    """`base` overlaid with the requested values; `locked` options may only repeat their base."""
    resolved = dict(base)
    for key, value in raw.items():
        path = f"options.{key}"
        option = profile.option(key)
        if option is None:
            _fail(problems, path, "is not an option of this profile")
        elif problem := option_value_problem(option, value):
            _fail(problems, path, problem)
        elif key in locked and value != base.get(key):
            _fail(problems, path, "cannot be changed on a clone")
        else:
            resolved[key] = value
    return resolved


def _identity_problem(rule: IdentityRule, value: object) -> str | None:
    if not isinstance(value, str):
        return "must be text"
    if not re.fullmatch(rule.pattern, value):
        return f"is not a valid {rule.label.lower()}: it must match {rule.pattern}"
    if value.lower() in {reserved.lower() for reserved in rule.reserved}:
        return "is a reserved name"
    if word := find_giveaway(value):
        return f"contains '{word}', which tells a sample what the machine is"
    return None


def _is_blank(value: object) -> bool:
    return value is None or value == ""


def _generate_unlike(generator: str, rng: random.Random | None, avoid: str | None) -> str:
    value = generate(generator, rng)
    for _ in range(GENERATION_ATTEMPTS):
        if avoid is None or value.lower() != avoid.lower():
            break
        value = generate(generator, rng)
    return value


@dataclass(frozen=True)
class _Run:
    rng: random.Random | None
    problems: Problems


def _resolve_identity_value(
    role: str, rule: IdentityRule, given: object, run: _Run, avoid: str | None = None
) -> str:
    path = f"identity.{role}"
    if _is_blank(given):
        if not rule.optional:
            _fail(run.problems, path, "is required")
            return ""
        return _generate_unlike(rule.generator, run.rng, avoid)
    if problem := _identity_problem(rule, given):
        _fail(run.problems, path, problem)
    elif avoid is not None and str(given).lower() == avoid.lower():
        _fail(run.problems, path, "must differ from the source guest's")
    return str(given)


def _build_identity(raw: Mapping[str, Any], profile: Profile, run: _Run) -> GuestIdentity:
    rules = profile.identity
    return GuestIdentity(
        account=_resolve_identity_value("account", rules.account, raw.get("account"), run),
        machine=_resolve_identity_value("machine", rules.machine, raw.get("machine"), run),
        password=_resolve_identity_value("password", rules.password, raw.get("password"), run),
    )


def _clone_identity(
    raw: Mapping[str, Any], profile: Profile, source: Guest, run: _Run
) -> GuestIdentity:
    for role in ("account", "password"):
        if not _is_blank(raw.get(role)):
            reason = f"is inherited from {source.name} and cannot be changed"
            _fail(run.problems, f"identity.{role}", reason)
    given_machine = raw.get("machine")
    if not profile.clone.computer_name_editable and not _is_blank(given_machine):
        _fail(run.problems, "identity.machine", "cannot be chosen: a new one is always generated")
        given_machine = None
    machine = _resolve_identity_value(
        "machine", profile.identity.machine, given_machine, run, avoid=source.identity.machine
    )
    return GuestIdentity(source.identity.account, machine, source.identity.password)


def _whole_number(
    raw: Mapping[str, Any],
    key: str,
    bounds: tuple[int, int | None],
    default: int,
    problems: Problems,
) -> int:
    value = raw.get(key)
    if value is None:
        return default
    low, high = bounds
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(problems, f"resources.{key}", "must be a whole number")
    elif value < low or (high is not None and value > high):
        bounds_text = f"between {low} and {high}" if high is not None else f"at least {low}"
        _fail(problems, f"resources.{key}", f"must be {bounds_text}")
    else:
        return value
    return default


def _resolve_resources(
    raw: Mapping[str, Any], profile: Profile, base: GuestResources, problems: Problems
) -> GuestResources:
    return GuestResources(
        vcpus=_whole_number(raw, "vcpus", (MIN_VCPUS, MAX_VCPUS), base.vcpus, problems),
        ram_mb=_whole_number(raw, "ram_mb", (MIN_RAM_MB, MAX_RAM_MB), base.ram_mb, problems),
        disk_gb=_whole_number(
            raw, "disk_gb", (profile.resources.min_disk_gb, None), base.disk_gb, problems
        ),
    )


def _profile_defaults(profile: Profile) -> GuestResources:
    resources = profile.resources
    return GuestResources(resources.vcpus, resources.ram_mb, resources.disk_gb)


def validate_build(
    params: object, context: ValidationContext, rng: random.Random | None = None
) -> ValidatedBuild:
    """Resolve a build request into a spec, or raise with every problem found."""
    request = _request(params)
    _refuse_when_full(context)
    problems: Problems = {}
    _reject_unknown(request, BUILD_FIELDS, problems)
    name = _check_name(request, context, problems)
    profile_id = request.get("profile")
    profile = context.profiles.get(profile_id) if isinstance(profile_id, str) else None
    if profile is None:
        _fail(problems, "profile", f"is not an installed profile ({', '.join(context.profiles)})")
        raise InvalidParameters(problems)
    media, media_kind = _resolve_media(
        _object(request, "media", problems), profile, context, problems
    )
    options = _resolve_options(
        _object(request, "options", problems), profile, profile.option_defaults(), (), problems
    )
    identity = _build_identity(_object(request, "identity", problems), profile, _Run(rng, problems))
    resources = _resolve_resources(
        _object(request, "resources", problems), profile, _profile_defaults(profile), problems
    )
    if problems:
        raise InvalidParameters(problems)
    spec = GuestSpec(
        name, profile.id, "build", None, media, options, identity, resources, media_kind=media_kind
    )
    return ValidatedBuild(spec)


def _ready_source(name: str, context: ValidationContext) -> Guest:
    source = next((guest for guest in context.guests if guest.name == name), None)
    if source is None:
        raise GuestNotFound(name)
    if source.state != "ready":
        raise Conflict(f"{name} is {source.state}; only a ready guest can be cloned")
    return source


def validate_clone(
    source_name: str,
    params: object,
    context: ValidationContext,
    rng: random.Random | None = None,
) -> GuestSpec:
    """Resolve a clone request for the ready guest `source_name` into a spec."""
    request = _request(params)
    source = _ready_source(source_name, context)
    profile = context.profiles.get(source.profile)
    if profile is None:
        raise Conflict(f"the profile {source.profile} of {source_name} is not installed")
    _refuse_when_full(context)
    problems: Problems = {}
    _reject_unknown(request, CLONE_FIELDS, problems)
    name = _check_name(request, context, problems)
    inherited = {**profile.option_defaults(), **source.options}
    locked = set(inherited) - profile.clone_changeable_options()
    options = _resolve_options(
        _object(request, "options", problems), profile, inherited, locked, problems
    )
    identity = _clone_identity(
        _object(request, "identity", problems), profile, source, _Run(rng, problems)
    )
    resources = _resolve_resources(
        _object(request, "resources", problems), profile, source.resources, problems
    )
    if resources.disk_gb != source.resources.disk_gb:
        _fail(problems, "resources.disk_gb", "cannot be changed on a clone")
    if problems:
        raise InvalidParameters(problems)
    return GuestSpec(
        name,
        profile.id,
        "clone",
        source.name,
        source.media,
        options,
        identity,
        resources,
        source.work_dir,
        source.media_kind,
    )
