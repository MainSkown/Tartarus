#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFLIGHT="$TESTS_DIR/../preflight.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

STUB_BIN="$WORK/bin"
PROC="$WORK/proc"
DEV="$WORK/dev"
EMPTY_DEV="$WORK/empty-dev"
ENV_FILE="$WORK/env"
GOOD_TOKEN=0123456789abcdef0123456789abcdef
FAILURES=0

write_stub() {
    local name=$1
    { echo '#!/usr/bin/env bash'; cat; } > "$STUB_BIN/$name"
    chmod +x "$STUB_BIN/$name"
}

make_stubs() {
    mkdir -p "$STUB_BIN"
    write_stub docker <<'STUB'
case "$1" in
    info) exit "${FAKE_DOCKER_INFO_EXIT:-0}" ;;
    compose) echo "Docker Compose version ${FAKE_COMPOSE_VERSION:-v2.29.1}" ;;
esac
STUB
    write_stub sysctl <<'STUB'
echo "${FAKE_MAX_MAP_COUNT:-262144}"
STUB
    write_stub df <<'STUB'
printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\nfake 1 1 %s 1%% /\n' "${FAKE_FREE_KB:-524288000}"
STUB
    write_stub uv <<'STUB'
echo "uv 0.9.0"
STUB
    write_stub node <<'STUB'
echo "${FAKE_NODE_VERSION:-v24.1.0}"
STUB
}

make_fake_host() {
    mkdir -p "$PROC" "$DEV" "$EMPTY_DEV"
    printf 'flags\t\t: fpu vme de pse vmx ept\n' > "$PROC/cpuinfo"
    printf 'MemTotal:       33554432 kB\n' > "$PROC/meminfo"
    : > "$DEV/kvm"
}

run_case() {
    local name=$1 expected_exit=$2 expected_text=$3
    shift 3
    local output actual_exit=0
    output=$(env PATH="$STUB_BIN:/usr/bin:/bin" PREFLIGHT_PROC_DIR="$PROC" PREFLIGHT_DEV_DIR="$DEV" \
        PREFLIGHT_ENV_FILE="$ENV_FILE" GUEST_CONTROL_TOKEN="$GOOD_TOKEN" "$@" "$PREFLIGHT" 2>&1) || actual_exit=$?

    if [ "$actual_exit" -eq "$expected_exit" ] && grep -qF -- "$expected_text" <<< "$output"; then
        echo "PASS $name"
    else
        echo "FAIL $name (exit $actual_exit, expected $expected_exit; expected text: '$expected_text')"
        sed 's/^/    | /' <<< "$output"
        FAILURES=$((FAILURES + 1))
    fi
}

main() {
    make_stubs
    make_fake_host

    run_case "all good exits 0" 0 "[ OK ] Docker Compose 2.29.1"
    run_case "daemon down exits 1 with docker group hint" 1 "docker group" FAKE_DOCKER_INFO_EXIT=1
    run_case "compose 2.21 fails" 1 "[FAIL] Docker Compose 2.21.0" FAKE_COMPOSE_VERSION=v2.21.0
    run_case "compose 2.24.3 fails (ports !override needs 2.24.4)" 1 "[FAIL] Docker Compose 2.24.3" FAKE_COMPOSE_VERSION=v2.24.3
    run_case "compose 5.4.0 passes" 0 "[ OK ] Docker Compose 5.4.0" FAKE_COMPOSE_VERSION=v5.4.0
    run_case "compose desktop suffix parses" 0 "[ OK ] Docker Compose 2.30.3" FAKE_COMPOSE_VERSION=v2.30.3-desktop.1
    run_case "low max_map_count fails" 1 "[FAIL] vm.max_map_count is 65530" FAKE_MAX_MAP_COUNT=65530
    run_case "missing kvm warns and exits 0" 0 "[WARN] $EMPTY_DEV/kvm missing" PREFLIGHT_DEV_DIR="$EMPTY_DEV"
    run_case "missing kvm says the default stack needs it" 0 "make up" PREFLIGHT_DEV_DIR="$EMPTY_DEV"
    run_case "node 22 warns and exits 0" 0 "[WARN] node v22.11.0" FAKE_NODE_VERSION=v22.11.0
    run_case "a 32 character control token passes" 0 "[ OK ] GUEST_CONTROL_TOKEN"
    run_case "a missing control token fails" 1 "[FAIL] GUEST_CONTROL_TOKEN is not set" GUEST_CONTROL_TOKEN=
    run_case "a missing control token says how to make one" 1 "openssl rand -hex 32" GUEST_CONTROL_TOKEN=
    run_case "a 31 character control token fails" 1 "[FAIL] GUEST_CONTROL_TOKEN is 31 characters" GUEST_CONTROL_TOKEN="${GOOD_TOKEN%?}"
    run_case "a short control token is reported by its length" 1 "GUEST_CONTROL_TOKEN is 5 characters" GUEST_CONTROL_TOKEN=s3cr3
    printf '# the settings\nGUEST_CONTROL_TOKEN=%s\n' "$GOOD_TOKEN" > "$ENV_FILE"
    run_case "the token is read from .env when the shell has none" 0 "[ OK ] GUEST_CONTROL_TOKEN" GUEST_CONTROL_TOKEN=
    printf 'GUEST_CONTROL_TOKEN="%s"\n' "$GOOD_TOKEN" > "$ENV_FILE"
    run_case "a quoted token in .env counts without its quotes" 0 "[ OK ] GUEST_CONTROL_TOKEN" GUEST_CONTROL_TOKEN=
    printf 'GUEST_CONTROL_TOKEN=\n' > "$ENV_FILE"
    run_case "an empty token in .env fails" 1 "[FAIL] GUEST_CONTROL_TOKEN is not set" GUEST_CONTROL_TOKEN=
    rm -f "$ENV_FILE"

    if [ "$FAILURES" -gt 0 ]; then
        echo "$FAILURES case(s) failed"
        exit 1
    fi
    echo "all cases passed"
}

main "$@"
