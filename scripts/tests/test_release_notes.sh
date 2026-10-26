#!/usr/bin/env bash
# Tests scripts/release-notes.sh against throwaway changelogs: the section of one version, the last
# section, a version that is not there, and the version read from backend/pyproject.toml.
set -uo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/release-notes.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0

pass() { printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failures=$((failures + 1)); }

CHANGELOG="$WORK/CHANGELOG.md"
cat >"$CHANGELOG" <<'MD'
# Changelog

## [Unreleased]

Nothing yet.

## [1.1.0] - 2026-12-01

### Added

- A newer thing.

## [1.0.0] - 2026-11-01

### Added

- The first thing.

### Security

- The first fix.
MD

test_the_section_of_one_version_is_printed_without_its_heading_or_the_next_section() {
    local out
    out=$("$SCRIPT" 1.1.0 "$CHANGELOG")
    [[ $out == *"A newer thing."* && $out != *"The first thing."* && $out != *"## [1.1.0]"* ]]
}

test_the_last_section_runs_to_the_end_of_the_file() {
    local out
    out=$("$SCRIPT" 1.0.0 "$CHANGELOG")
    [[ $out == *"The first thing."* && $out == *"The first fix."* && $out != *"A newer thing."* ]]
}

test_surrounding_blank_lines_are_trimmed() {
    local out
    out=$("$SCRIPT" 1.0.0 "$CHANGELOG")
    [[ ${out:0:1} == "#" && ${out: -1} != $'\n' ]]
}

test_a_version_that_is_not_in_the_changelog_fails_and_names_it() {
    local out status
    out=$("$SCRIPT" 9.9.9 "$CHANGELOG" 2>&1)
    status=$?
    [[ $status -ne 0 && $out == *"9.9.9"* ]]
}

test_a_missing_changelog_fails() {
    "$SCRIPT" 1.0.0 "$WORK/none.md" >/dev/null 2>&1
    [[ $? -ne 0 ]]
}

test_the_version_defaults_to_the_one_in_backend_pyproject() {
    local version out
    version=$(sed -n 's/^version = "\(.*\)"$/\1/p' "$(dirname "$SCRIPT")/../backend/pyproject.toml" | head -1)
    printf '## [%s] - x\n\n- the default version\n' "$version" >"$WORK/real.md"
    out=$("$SCRIPT" "" "$WORK/real.md")
    [[ $out == *"the default version"* ]]
}

for t in $(declare -F | awk '{print $3}' | grep '^test_'); do
    if "$t"; then pass "$t"; else fail "$t"; fi
done

((failures == 0)) && echo "all tests passed"
exit $((failures > 0))
