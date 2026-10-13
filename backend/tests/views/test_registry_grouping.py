from typing import Any

from app.views.registry import group_registry_changes


def change(
    time: str, key: str, action: str = "reg-value-set", hive: str = "HKCU", **registry: Any
) -> dict[str, Any]:
    return {
        "@timestamp": time,
        "event": {"id": f"{time}-{key}-{action}", "action": action},
        "registry": {"hive": hive, "key": key, **registry},
        "process": {"pid": 4, "name": "x.exe"},
    }


def test_changes_to_one_key_are_grouped_in_time_order() -> None:
    groups = group_registry_changes(
        [
            change("2026-01-01T00:00:02Z", r"Software\A", value="two"),
            change("2026-01-01T00:00:01Z", r"Software\A", "reg-key-created"),
        ]
    )

    [group] = groups
    assert [c.action for c in group.changes] == ["reg-key-created", "reg-value-set"]


def test_groups_are_ordered_by_their_first_change() -> None:
    groups = group_registry_changes(
        [
            change("2026-01-01T00:00:03Z", r"Software\Late"),
            change("2026-01-01T00:00:01Z", r"Software\Early"),
            change("2026-01-01T00:00:04Z", r"Software\Early"),
        ]
    )

    assert [group.key for group in groups] == [r"Software\Early", r"Software\Late"]


def test_the_same_key_in_another_hive_is_another_group() -> None:
    groups = group_registry_changes(
        [
            change("2026-01-01T00:00:01Z", r"Software\A", hive="HKCU"),
            change("2026-01-01T00:00:02Z", r"Software\A", hive="HKLM"),
        ]
    )

    assert [(g.hive, g.key) for g in groups] == [("HKCU", r"Software\A"), ("HKLM", r"Software\A")]


def test_key_spelling_in_another_case_joins_the_same_group() -> None:
    groups = group_registry_changes(
        [
            change("2026-01-01T00:00:01Z", r"Software\Run"),
            change("2026-01-01T00:00:02Z", r"SOFTWARE\RUN"),
        ]
    )

    [group] = groups
    assert (group.key, len(group.changes)) == (r"Software\Run", 2)


def test_value_data_and_type_are_carried_and_default_to_empty() -> None:
    [group] = group_registry_changes(
        [
            change(
                "2026-01-01T00:00:01Z",
                "K",
                value="Updater",
                data={"type": "REG_SZ", "strings": ["a", "b"]},
            ),
            change("2026-01-01T00:00:02Z", "K", "reg-key-created"),
        ]
    )

    value_set, key_created = group.changes
    assert (value_set.value_name, value_set.data_type, value_set.data) == (
        "Updater",
        "REG_SZ",
        ["a", "b"],
    )
    assert (key_created.value_name, key_created.data_type, key_created.data) == (None, None, [])


def test_an_event_without_a_key_is_ignored() -> None:
    event = change("2026-01-01T00:00:01Z", "K")
    del event["registry"]["key"]

    assert group_registry_changes([event]) == []
