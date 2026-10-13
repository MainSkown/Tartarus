from typing import Any

from app.views.processes import loaded_modules


def load(api: str, time: str, **arguments: str) -> dict[str, Any]:
    return {"@timestamp": time, "api": {"name": api, "arguments": arguments}}


def test_a_library_loaded_by_name_has_no_path() -> None:
    [module] = loaded_modules(
        [load("LdrLoadDll", "2026-01-01T00:00:01Z", FileName="SHELL32.dll", BaseAddress="0x10")]
    )

    assert (module.name, module.path, module.base_address) == ("SHELL32.dll", None, "0x10")


def test_a_library_loaded_by_path_keeps_the_path_and_its_base_name() -> None:
    [module] = loaded_modules(
        [
            load(
                "LdrLoadDll",
                "2026-01-01T00:00:01Z",
                FileName=r"C:\Windows\System32\mswsock.dll",
                BaseAddress="0x20",
            )
        ]
    )

    assert (module.name, module.path) == ("mswsock.dll", r"C:\Windows\System32\mswsock.dll")


def test_a_notification_adds_libraries_the_loader_pulled_in() -> None:
    [module] = loaded_modules(
        [
            load(
                "DllLoadNotification",
                "2026-01-01T00:00:01Z",
                NotificationReason="load",
                DllName=r"C:\WINDOWS\System32\wintypes",
                DllBase="0x30",
            )
        ]
    )

    assert (module.name, module.path, module.base_address) == (
        "wintypes",
        r"C:\WINDOWS\System32\wintypes",
        "0x30",
    )


def test_unloads_are_not_modules() -> None:
    assert (
        loaded_modules(
            [
                load(
                    "DllLoadNotification",
                    "2026-01-01T00:00:01Z",
                    NotificationReason="unload",
                    DllName="gone",
                    DllBase="0x40",
                )
            ]
        )
        == []
    )


def test_one_base_address_is_one_module_named_by_the_explicit_load() -> None:
    modules = loaded_modules(
        [
            load(
                "DllLoadNotification",
                "2026-01-01T00:00:01Z",
                NotificationReason="load",
                DllName=r"C:\WINDOWS\System32\SHELL32",
                DllBase="0x50",
            ),
            load("LdrLoadDll", "2026-01-01T00:00:01Z", FileName="SHELL32.dll", BaseAddress="0x50"),
        ]
    )

    assert [(m.name, m.base_address) for m in modules] == [("SHELL32.dll", "0x50")]
    assert modules[0].loaded_at.isoformat() == "2026-01-01T00:00:01+00:00"


def test_without_an_address_the_same_name_is_one_module() -> None:
    modules = loaded_modules(
        [
            load("LdrLoadDll", "2026-01-01T00:00:01Z", FileName="A.dll"),
            load("LdrLoadDll", "2026-01-01T00:00:02Z", FileName="a.DLL"),
        ]
    )

    assert [m.name for m in modules] == ["A.dll"]


def test_a_load_without_a_name_is_skipped() -> None:
    assert loaded_modules([load("LdrLoadDll", "2026-01-01T00:00:01Z", BaseAddress="0x1")]) == []
