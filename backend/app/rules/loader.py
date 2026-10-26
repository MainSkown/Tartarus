import hashlib
import logging
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml
from sigma.exceptions import SigmaConditionError, SigmaError, SigmaModifierError
from sigma.rule import SigmaRule

from app.rules.categories import SUPPORTED_CATEGORIES, SUPPORTED_PRODUCT
from app.rules.compiler import compile_sigma_rule
from app.rules.explain import explain_sigma_rule
from app.rules.mapping import map_fields
from app.rules.predicate import Explainer, Predicate
from app.rules.regexes import DEFAULT_LIMITS, RegexLimits
from app.rules.rule import Rule, RuleProblem, Validity, invalid, unsupported

RULE_SUFFIXES = (".yml", ".yaml")
UNSUPPORTED_DOCUMENT_KINDS = ("correlation", "filter")
PATH_NAMESPACE = uuid.UUID("2c1f6f0e-6a9e-4d0e-9a53-5a0c6a0c9d11")

logger = logging.getLogger(__name__)


def load_rules(root: Path, limits: RegexLimits = DEFAULT_LIMITS) -> list[Rule]:
    """Loads every rule file below `root`, in path order, as `Rule`s with a validity verdict.

    Never raises: a file that cannot be read, parsed or run becomes an `INVALID` or
    `UNSUPPORTED` rule carrying the reason. The first rule to use an id keeps it; a later file
    with the same id is `INVALID`, so ids are unique in the result.
    """
    paths = sorted(p for p in root.rglob("*") if p.suffix in RULE_SUFFIXES and p.is_file())
    first_path_of_id: dict[str, Path] = {}
    rules: list[Rule] = []
    for path in paths:
        rule = load_rule_file(path, limits)
        if (first := first_path_of_id.setdefault(rule.id, path)) != path:
            rule = replace(
                rule,
                validity=Validity.INVALID,
                error=f"rule id {rule.id} is already used by {first}",
            )
        rules.append(rule)
    return rules


def load_rule_file(path: Path, limits: RegexLimits = DEFAULT_LIMITS) -> Rule:
    """Loads one rule file; see `load_rules` for the guarantee that it does not raise."""
    try:
        content = path.read_bytes()
    except OSError as error:
        return _rule(path, b"", {}, invalid(f"cannot read the file: {error}"))
    document: Mapping[str, Any] = {}
    try:
        document = _single_document(content)
        category = _check_logsource(document)
        sigma_rule = _parse(document)
        map_fields(sigma_rule, category)
        compiled = (compile_sigma_rule(sigma_rule, limits), explain_sigma_rule(sigma_rule, limits))
    except RuleProblem as problem:
        return _rule(path, content, document, problem)
    except Exception as error:  # decision 9: nothing a rule contains may stop the engine
        logger.exception("unexpected failure loading rule %s", path)
        return _rule(
            path, content, document, invalid(f"unexpected {type(error).__name__}: {error}")
        )
    return _rule(path, content, document, None, compiled)


def _single_document(content: bytes) -> Mapping[str, Any]:
    try:
        documents = list(yaml.safe_load_all(content.decode("utf-8")))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise invalid(f"not readable YAML: {error}") from error
    if len(documents) > 1:
        raise unsupported(
            f"the file holds {len(documents)} YAML documents; only one rule per file is supported"
        )
    document = documents[0] if documents else None
    if not isinstance(document, Mapping):
        raise invalid("the file is not a Sigma rule: expected a YAML mapping")
    for kind in UNSUPPORTED_DOCUMENT_KINDS:
        if kind in document:
            raise unsupported(f"{kind} rules are not supported")
    return document


def _check_logsource(document: Mapping[str, Any]) -> str:
    logsource = document.get("logsource")
    if not isinstance(logsource, Mapping):
        raise invalid("logsource is missing")
    product = logsource.get("product")
    if product is not None and str(product).lower() != SUPPORTED_PRODUCT:
        raise unsupported(f"logsource product {product} is not supported, only windows")
    category = logsource.get("category")
    if category is None:
        raise unsupported("logsource has no category; service-based logsources are not supported")
    if category not in SUPPORTED_CATEGORIES:
        raise unsupported(f"logsource category {category} is not supported")
    return str(category)


def _parse(document: Mapping[str, Any]) -> SigmaRule:
    try:
        rule = SigmaRule.from_dict(dict(document))
        # pySigma checks the condition only when it is parsed, so parse it now.
        for condition in rule.detection.parsed_condition:
            condition.parse()
        return rule
    except SigmaError as error:
        raise _problem_of(error) from error


def _problem_of(error: SigmaError) -> RuleProblem:
    # pySigma has one exception class per area, not per construct, so the two constructs
    # this engine cannot run are told apart by the message.
    message = str(error)
    if isinstance(error, SigmaModifierError) and message.startswith("Unknown modifier"):
        return unsupported(f"unsupported modifier: {message}")
    if isinstance(error, SigmaConditionError) and "pipe syntax" in message:
        return unsupported("aggregation conditions (count(), near) are not supported")
    return invalid(message)


def _rule(
    path: Path,
    content: bytes,
    document: Mapping[str, Any],
    problem: RuleProblem | None,
    compiled: tuple[Predicate, Explainer] | None = None,
) -> Rule:
    logsource = document.get("logsource")
    category = logsource.get("category") if isinstance(logsource, Mapping) else None
    return Rule(
        id=_text(document.get("id")) or str(uuid.uuid5(PATH_NAMESPACE, str(path))),
        title=_text(document.get("title")) or path.stem,
        description=_text(document.get("description")),
        level=_text(document.get("level")),
        status=_text(document.get("status")),
        tags=_texts(document.get("tags")),
        logsource_category=_text(category),
        path=path,
        content_sha256=hashlib.sha256(content).hexdigest(),
        validity=problem.validity if problem else Validity.VALID,
        error=problem.reason if problem else None,
        references=_texts(document.get("references")),
        author=_text(document.get("author")),
        condition=_condition_text(document.get("detection")),
        predicate=compiled[0] if compiled else None,
        explain=compiled[1] if compiled else None,
    )


def _text(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None


def _texts(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _condition_text(detection: object) -> str | None:
    condition = detection.get("condition") if isinstance(detection, Mapping) else None
    conditions = _texts(condition) if isinstance(condition, list) else (_text(condition),)
    return "; ".join(text for text in conditions if text) or None
