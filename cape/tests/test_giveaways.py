import pytest

from guest_engine.giveaways import find_giveaway


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("tartarus", "tartarus"),
        ("MyTartarusBox", "tartarus"),
        ("sandbox-01", "sandbox"),
        ("SANDBOX", "sandbox"),
        ("malware-lab", "malware"),
        ("antivirus", "virus"),
        ("cuckoo", "cuckoo"),
        ("cape", "cape"),
        ("CAPE-01", "cape"),
        ("my-cape-vm", "cape"),
        ("MyCapeVM", "cape"),
        ("cape2", "cape"),
        ("/opt/cape/agent", "cape"),
        ("test", "test"),
        ("Test-PC", "test"),
        ("DesktopTest", "test"),
        ("admin", "admin"),
        ("ADMIN1", "admin"),
        ("analyst", "analy"),
        ("Analysis-box", "analy"),
        ("analyzer", "analy"),
        ("analytics", "analy"),
    ],
)
def test_names_that_say_what_the_machine_is_are_found(text, word):
    assert find_giveaway(text) == word


@pytest.mark.parametrize(
    "text",
    [
        "landscape",
        "escape",
        "Capello",
        "capeman",
        "scape",
        "latest",
        "contest",
        "attest",
        "administrator",
        "badminton",
        "Michael",
        "DESKTOP-7A3K2P9",
        "LAPTOP-4Q8R2MZ",
        "analog",
        "canal",
        "",
        "Usługa niejawnego programu testów systemu Windows",
        "Zabezpieczenia urządzenia testowe",
    ],
)
def test_ordinary_names_and_words_that_merely_contain_a_short_giveaway_pass(text):
    assert find_giveaway(text) is None
