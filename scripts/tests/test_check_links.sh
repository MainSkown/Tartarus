#!/usr/bin/env bash
# Tests scripts/check-links.py against throwaway fixture trees: a good link, a broken file link,
# a broken anchor, links the checker must skip (external, inside code, in excluded folders).
set -uo pipefail

CHECK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/check-links.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
OUTPUT=""
STATUS=0
ROOT=""

new_tree() {
    ROOT="$(mktemp -d -p "$WORK")"
    mkdir -p "$ROOT/docs/specs" "$ROOT/node_modules/pkg" "$ROOT/data" "$ROOT/frontend/dist"
    cat >"$ROOT/README.md" <<'MD'
# Readme

See [the spec](docs/specs/backend.md) and [its section](docs/specs/backend.md#query-language).
MD
    cat >"$ROOT/docs/specs/backend.md" <<'MD'
# Backend

## Query language

Back to [readme](../../README.md#readme).
MD
}

run_checker() {
    OUTPUT=$(python3 -I "$CHECK" "$ROOT" 2>&1)
    STATUS=$?
}

run_test() {
    local name=$1
    new_tree
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_good_links_pass() {
    run_checker
    [[ $STATUS -eq 0 ]]
}

test_broken_file_link_is_reported_with_file_and_line() {
    printf 'Broken: [gone](docs/specs/missing.md)\n' >>"$ROOT/README.md"
    run_checker
    [[ $STATUS -ne 0 ]] || return 1
    [[ $OUTPUT == *"README.md:4"* && $OUTPUT == *"docs/specs/missing.md"* ]] || { echo "$OUTPUT"; return 1; }
}

test_broken_anchor_is_reported() {
    printf 'Lost: [section](docs/specs/backend.md#no-such-heading)\n' >>"$ROOT/README.md"
    run_checker
    [[ $STATUS -ne 0 ]] || return 1
    [[ $OUTPUT == *"no-such-heading"* ]] || { echo "$OUTPUT"; return 1; }
}

test_anchor_matches_github_slug_of_heading() {
    printf '## Hello, World! `code`\n' >>"$ROOT/docs/specs/backend.md"
    printf 'Slug: [x](#hello-world-code)\n' >>"$ROOT/docs/specs/backend.md"
    run_checker
    [[ $STATUS -eq 0 ]] || { echo "$OUTPUT"; return 1; }
}

test_external_and_mailto_links_are_skipped() {
    printf 'Web: [a](https://example.invalid/page) [b](http://example.invalid) [c](mailto:x@example.invalid)\n' >>"$ROOT/README.md"
    run_checker
    [[ $STATUS -eq 0 ]]
}

test_links_inside_code_are_skipped() {
    printf '```\n[fenced](nowhere.md)\n```\n\nInline `[code](nowhere.md)` text.\n' >>"$ROOT/README.md"
    run_checker
    [[ $STATUS -eq 0 ]] || { echo "$OUTPUT"; return 1; }
}

test_excluded_folders_are_not_scanned() {
    printf '[dead](nowhere.md)\n' >"$ROOT/node_modules/pkg/README.md"
    printf '[dead](nowhere.md)\n' >"$ROOT/data/notes.md"
    printf '[dead](nowhere.md)\n' >"$ROOT/frontend/dist/index.md"
    run_checker
    [[ $STATUS -eq 0 ]] || { echo "$OUTPUT"; return 1; }
}

run_test test_good_links_pass
run_test test_broken_file_link_is_reported_with_file_and_line
run_test test_broken_anchor_is_reported
run_test test_anchor_matches_github_slug_of_heading
run_test test_external_and_mailto_links_are_skipped
run_test test_links_inside_code_are_skipped
run_test test_excluded_folders_are_not_scanned

exit "$failures"
