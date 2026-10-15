"""The seam of decision 17: generic engine code never names an operating system."""

import re
from pathlib import Path

ENGINE = Path(__file__).parents[1] / "guest_engine"
OPERATING_SYSTEM_WORDS = re.compile(r"windows|defender|powershell", re.IGNORECASE)
# profile.py's schema vocabulary (the platform and path-style values a profile may name) and the
# protocol module's docstring example are the only places the words may appear.
VOCABULARY = {
    ("profile.py", 'PLATFORMS = ("windows", "linux", "darwin")'),
    ("profile.py", 'PATH_SEPARATORS = {"windows": "\\\\", "posix": "/"}'),
}


def mentions(directory=ENGINE):
    found = set()
    for path in sorted(directory.rglob("*.py")):
        if path.name == "protocol.py":
            continue
        for line in path.read_text().splitlines():
            if OPERATING_SYSTEM_WORDS.search(line):
                found.add((path.name, line.strip()))
    return found


def test_only_the_two_vocabulary_lines_of_the_profile_schema_name_an_operating_system():
    assert mentions() == VOCABULARY


def test_the_check_would_notice_a_new_mention(tmp_path):
    (tmp_path / "sample.py").write_text("# runs Defender\nprint('fine')\n")

    assert mentions(tmp_path) == {("sample.py", "# runs Defender")}
