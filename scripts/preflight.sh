#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROC_DIR="${PREFLIGHT_PROC_DIR:-/proc}"
DEV_DIR="${PREFLIGHT_DEV_DIR:-/dev}"

MIN_COMPOSE_VERSION="2.24.4"
MIN_MAX_MAP_COUNT=262144
MIN_RAM_KB=$((15 * 1024 * 1024))
MIN_FREE_DISK_KB=$((200 * 1024 * 1024))
MIN_NODE_MAJOR=24

FAILED=0

ok() { echo "[ OK ] $*"; }
warn() { echo "[WARN] $*"; }
fail() {
    echo "[FAIL] $*"
    FAILED=1
}

version_at_least() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n 1)" = "$2" ]
}

compose_version() {
    docker compose version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n 1
}

check_docker_daemon() {
    if docker info >/dev/null 2>&1; then
        ok "Docker daemon reachable"
    else
        fail "Docker daemon unreachable: add your user to the docker group (then log in again) or use rootless Docker"
    fi
}

check_compose() {
    local version
    version=$(compose_version || true)
    if [ -z "$version" ]; then
        fail "Docker Compose not available (\`docker compose version\` failed)"
    elif version_at_least "$version" "$MIN_COMPOSE_VERSION"; then
        ok "Docker Compose $version"
    else
        fail "Docker Compose $version is older than $MIN_COMPOSE_VERSION (develop.watch and ports: !override need it)"
    fi
}

check_max_map_count() {
    local value
    value=$(sysctl -n vm.max_map_count 2>/dev/null || true)
    if [[ "$value" =~ ^[0-9]+$ ]] && (( value >= MIN_MAX_MAP_COUNT )); then
        ok "vm.max_map_count $value"
    else
        fail "vm.max_map_count is ${value:-unknown}, OpenSearch needs >= $MIN_MAX_MAP_COUNT (sudo sysctl -w vm.max_map_count=$MIN_MAX_MAP_COUNT)"
    fi
}

check_kvm() {
    if [ -e "$DEV_DIR/kvm" ]; then
        ok "$DEV_DIR/kvm present"
    else
        warn "$DEV_DIR/kvm missing: the cape container, part of \`make up\`, needs KVM (the UI alone runs without it, see the README)"
    fi
}

check_cpu_virtualization() {
    if grep -Eqw 'vmx|svm' "$PROC_DIR/cpuinfo" 2>/dev/null; then
        ok "CPU virtualization extensions present"
    else
        warn "no vmx/svm in $PROC_DIR/cpuinfo: hardware virtualization is unavailable (the cape container needs it)"
    fi
}

check_ram() {
    local total_kb
    total_kb=$(awk '/^MemTotal:/ {print $2}' "$PROC_DIR/meminfo" 2>/dev/null || true)
    if [[ ! "$total_kb" =~ ^[0-9]+$ ]]; then
        warn "could not read RAM from $PROC_DIR/meminfo"
    elif (( total_kb >= MIN_RAM_KB )); then
        ok "RAM $((total_kb / 1024 / 1024)) GiB"
    else
        warn "RAM $((total_kb / 1024 / 1024)) GiB is below the 16 GB the full stack is sized for"
    fi
}

check_disk() {
    local free_kb
    free_kb=$(df -Pk "$REPO_DIR" 2>/dev/null | awk 'NR == 2 {print $4}' || true)
    if [[ ! "$free_kb" =~ ^[0-9]+$ ]]; then
        warn "could not read free disk space for $REPO_DIR"
    elif (( free_kb >= MIN_FREE_DISK_KB )); then
        ok "free disk $((free_kb / 1024 / 1024)) GiB"
    else
        warn "free disk $((free_kb / 1024 / 1024)) GiB is below 200 GB (Windows ISO, guest images)"
    fi
}

check_uv() {
    if command -v uv >/dev/null 2>&1; then
        ok "uv found"
    else
        warn "uv not found: needed to run backend tests on the host"
    fi
}

check_node() {
    local version major
    version=$(node --version 2>/dev/null || true)
    major=${version#v}
    major=${major%%.*}
    if [[ ! "$major" =~ ^[0-9]+$ ]]; then
        warn "node not found: Node $MIN_NODE_MAJOR or newer is needed to run frontend tests on the host"
    elif (( major < MIN_NODE_MAJOR )); then
        warn "node $version is older than $MIN_NODE_MAJOR"
    else
        ok "node $version"
    fi
}

main() {
    check_docker_daemon
    check_compose
    check_max_map_count
    check_kvm
    check_cpu_virtualization
    check_ram
    check_disk
    check_uv
    check_node
    exit "$FAILED"
}

main "$@"
