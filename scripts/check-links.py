"""Fail when a relative markdown link points at a file or heading that does not exist.

Scans every *.md under the repo root (or the root given as the first argument) for inline links
`[text](target)`. Targets are checked against the file system relative to the linking file. For a
target that is a markdown file with `#anchor`, the anchor must match a heading slugged by GitHub's
rules (lowercase, punctuation dropped, spaces to hyphens, repeats suffixed -1, -2). Anchors that are
not headings (HTML `id=`/`name=`) are not checked, so they are reported as broken. External
`scheme:` links are skipped. Fenced and inline code is ignored. Skipped folders: node_modules,
.git, frontend/dist and data.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

SKIPPED_NAMES = {"node_modules", ".git"}
SKIPPED_PATHS = {"frontend/dist", "data"}
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
INLINE_CODE = re.compile(r"`[^`]*`")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
MARKDOWN_LINK_IN_HEADING = re.compile(r"\[([^\]]*)\]\([^)]*\)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def markdown_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in SKIPPED_NAMES for part in relative.parts):
            continue
        if any(relative.as_posix().startswith(skipped + "/") for skipped in SKIPPED_PATHS):
            continue
        yield path


def outside_fences(text: str) -> Iterator[tuple[int, str]]:
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def slugify(heading: str) -> str:
    text = MARKDOWN_LINK_IN_HEADING.sub(r"\1", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for _, line in outside_fences(text):
        match = HEADING.match(line)
        if not match:
            continue
        slug = slugify(match.group(1))
        count = seen.get(slug, 0)
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return anchors


def link_targets(text: str) -> Iterator[tuple[int, str]]:
    for number, line in outside_fences(text):
        for match in LINK.finditer(INLINE_CODE.sub("", line)):
            yield number, match.group(1)


def problem_with(source: Path, target: str, root: Path, anchor_cache: dict[Path, set[str]]) -> str | None:
    if not target or SCHEME.match(target):
        return None
    path_part, _, anchor = unquote(target).partition("#")
    destination = (source.parent / path_part).resolve() if path_part else source.resolve()
    if not destination.exists():
        return "no such file"
    if not anchor or destination.is_dir() or destination.suffix != ".md":
        return None
    if destination not in anchor_cache:
        anchor_cache[destination] = anchors_of(destination.read_text(encoding="utf-8"))
    if anchor not in anchor_cache[destination]:
        return f"no heading #{anchor} in {destination.relative_to(root.resolve()).as_posix()}"
    return None


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    anchor_cache: dict[Path, set[str]] = {}
    problems: list[str] = []
    checked = 0
    files = list(markdown_files(root))
    for source in files:
        text = source.read_text(encoding="utf-8")
        for number, target in link_targets(text):
            checked += 1
            reason = problem_with(source, target, root, anchor_cache)
            if reason:
                problems.append(f"{source.relative_to(root).as_posix()}:{number}: {target} ({reason})")
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} broken link(s) in {len(files)} markdown file(s)")
        return 1
    print(f"{checked} relative link(s) in {len(files)} markdown file(s) resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
