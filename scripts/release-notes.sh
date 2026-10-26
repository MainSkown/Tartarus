#!/usr/bin/env bash
# Prints the CHANGELOG.md section of one version, ready to be the body of a GitHub release:
#   scripts/release-notes.sh [VERSION] [CHANGELOG]   (default: the version in backend/pyproject.toml)
# The section runs from the line after its "## [VERSION]" heading to the next "## [" heading.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version=${1:-}
changelog=${2:-$REPO/CHANGELOG.md}

[[ -n $version ]] || version=$(sed -n 's/^version = "\(.*\)"$/\1/p' "$REPO/backend/pyproject.toml" | head -1)
[[ -f $changelog ]] || { echo "release-notes: no changelog at $changelog" >&2; exit 1; }

notes=$(awk -v heading="## [$version]" '
    index($0, heading) == 1 { inside = 1; next }
    inside && index($0, "## [") == 1 { exit }
    inside { print }
' "$changelog")

[[ -n ${notes//[$'\n' ]/} ]] || { echo "release-notes: no section for version $version in $changelog" >&2; exit 1; }

printf '%s\n' "$notes" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' | sed '/./,$!d'
