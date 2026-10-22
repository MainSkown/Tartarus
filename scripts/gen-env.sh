#!/usr/bin/env bash
# Creates .env from .env.example with a random value for every secret the example leaves empty.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE_FILE="${GEN_ENV_EXAMPLE:-$REPO_DIR/.env.example}"
ENV_FILE="${GEN_ENV_FILE:-$REPO_DIR/.env}"

source "$REPO_DIR/scripts/lib/secrets.sh"

die() {
    echo "gen-env: $*" >&2
    exit 1
}

random_secret() { openssl rand -hex 32; }

with_generated_secrets() {
    local line name
    while IFS= read -r line || [ -n "$line" ]; do
        name=${line%%=*}
        if [ "$line" = "$name=" ] && in_list "$name" "${SECRET_NAMES[@]}"; then
            printf '%s=%s\n' "$name" "$(random_secret)"
        else
            printf '%s\n' "$line"
        fi
    done <"$EXAMPLE_FILE"
}

main() {
    [ -r "$EXAMPLE_FILE" ] || die "$EXAMPLE_FILE is not readable"
    [ ! -e "$ENV_FILE" ] || die "$ENV_FILE already exists; it is never overwritten (delete it first to start over)"
    command -v openssl >/dev/null || die "openssl is needed to make the secrets"

    umask 077
    with_generated_secrets >"$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "gen-env: wrote $ENV_FILE (mode 600) with new values for ${SECRET_NAMES[*]}"
}

main "$@"
