#!/usr/bin/env bash
# Tests scripts/gen-env.sh against a throwaway .env.example.
set -uo pipefail

GEN_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/gen-env.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

EXAMPLE="$WORK/env.example"
TARGET="$WORK/env"
failures=0
OUTPUT=""
STATUS=0

value_of() { sed -n "s/^$1=//p" "$TARGET" | tail -n 1; }

write_example() {
    cat >"$EXAMPLE" <<'ENV'
# Copy to .env.
TARTARUS_PORT=8080
TARTARUS_ALLOWED_HOSTS=
POSTGRES_USER=tartarus
POSTGRES_PASSWORD=
CAPE_DB_PASSWORD=
CAPE_REF=
CAPE_API_TOKEN=
GUEST_CONTROL_TOKEN=
ENV
}

run_gen_env() {
    OUTPUT=$(GEN_ENV_EXAMPLE="$EXAMPLE" GEN_ENV_FILE="$TARGET" bash "$GEN_ENV" 2>&1)
    STATUS=$?
}

run_test() {
    local name=$1
    rm -f "$TARGET"
    write_example
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_fills_every_secret_with_64_hex_characters() {
    run_gen_env
    local name
    [[ $STATUS -eq 0 ]] || return 1
    for name in POSTGRES_PASSWORD CAPE_DB_PASSWORD CAPE_API_TOKEN GUEST_CONTROL_TOKEN; do
        [[ $(value_of "$name") =~ ^[0-9a-f]{64}$ ]] || { echo "  $name is not 64 hex characters"; return 1; }
    done
}

test_database_passwords_fit_the_url_safe_alphabet() {
    run_gen_env
    [[ $(value_of POSTGRES_PASSWORD) =~ ^[A-Za-z0-9._-]+$ && $(value_of CAPE_DB_PASSWORD) =~ ^[A-Za-z0-9._-]+$ ]]
}

test_every_secret_is_different() {
    run_gen_env
    local distinct
    distinct=$(grep -E '^(POSTGRES_PASSWORD|CAPE_DB_PASSWORD|CAPE_API_TOKEN|GUEST_CONTROL_TOKEN)=' "$TARGET" | sort -u | wc -l)
    [[ $distinct -eq 4 ]]
}

test_other_empty_settings_stay_empty() {
    run_gen_env
    [[ $(value_of CAPE_REF) == "" && $(value_of TARTARUS_ALLOWED_HOSTS) == "" ]] && grep -q '^CAPE_REF=$' "$TARGET"
}

test_other_lines_are_copied_unchanged() {
    run_gen_env
    grep -qx '# Copy to .env.' "$TARGET" && grep -qx 'POSTGRES_USER=tartarus' "$TARGET" && grep -qx 'TARTARUS_PORT=8080' "$TARGET"
}

test_the_file_is_readable_by_the_owner_only() {
    run_gen_env
    [[ $(stat -c %a "$TARGET") == 600 ]]
}

test_a_secret_the_example_already_sets_is_kept() {
    sed -i 's/^CAPE_API_TOKEN=$/CAPE_API_TOKEN=chosen-by-hand/' "$EXAMPLE"
    run_gen_env
    [[ $(value_of CAPE_API_TOKEN) == chosen-by-hand ]]
}

test_refuses_to_overwrite_an_existing_env() {
    echo "POSTGRES_PASSWORD=mine" >"$TARGET"
    run_gen_env
    [[ $STATUS -ne 0 && $OUTPUT == *"already exists"* && $(cat "$TARGET") == "POSTGRES_PASSWORD=mine" ]]
}

test_fails_when_there_is_no_example() {
    rm "$EXAMPLE"
    run_gen_env
    [[ $STATUS -ne 0 && ! -e $TARGET ]]
}

test_output_never_prints_a_secret() {
    run_gen_env
    local name
    for name in POSTGRES_PASSWORD CAPE_DB_PASSWORD CAPE_API_TOKEN GUEST_CONTROL_TOKEN; do
        [[ $OUTPUT != *"$(value_of "$name")"* ]] || return 1
    done
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
