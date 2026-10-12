#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BASE_FILE=docker-compose.yml
DEV_FILE=docker-compose.dev.yml
failed=0

ok() { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }

check() {
    local description=$1 detail
    shift
    if detail=$("$@" 2>&1); then
        ok "$description"
    else
        detail=${detail//$'\n'/; }
        fail "$description${detail:+ ($detail)}"
    fi
}

compose() { docker compose "${COMPOSE_FILES[@]}" "$@"; }

policy_violations() {
    python3 -I - "$1" "$2" "${3:-{\}}" <<'PY'
import json
import sys

check, config = sys.argv[1], json.loads(sys.argv[2])
services = config["services"]
published = [(name, port) for name, svc in services.items() for port in svc.get("ports", [])]

if check == "loopback-only":
    problems = [
        f"{name} publishes {port.get('published')} on {port.get('host_ip') or 'all interfaces'}"
        for name, port in published
        if port.get("host_ip") != "127.0.0.1"
    ]
elif check == "frontend-only":
    publishers = {name for name, _ in published}
    problems = [] if publishers == {"frontend"} else [f"only the frontend may publish ports, found {sorted(publishers)}"]
elif check == "dev-frontend-vite-only":
    extra = [port.get("published") for name, port in published if name == "frontend" and port.get("target") != 5173]
    problems = [f"frontend also publishes {', '.join(extra)} in dev"] if extra else []
elif check == "distinct-build-image-tags":
    other = json.loads(sys.argv[3])
    collisions = [
        f"{name} is tagged {image!r} in both files"
        for name, svc in services.items()
        if "build" in svc
        for image in [svc.get("image")]
        if image and other.get("services", {}).get(name, {}).get("image") == image
    ]
    print("; ".join(collisions))
    sys.exit(1 if collisions else 0)
elif check == "no-docker-socket":
    problems = [
        f"{name} mounts {volume['source']}"
        for name, svc in services.items()
        for volume in svc.get("volumes", [])
        if "docker.sock" in volume.get("source", "")
    ]
else:
    sys.exit(f"unknown check {check}")

print("; ".join(problems))
sys.exit(1 if problems else 0)
PY
}

http_status_is_200() {
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1") || true
    [[ $code == 200 ]] || { echo "got ${code:-no response}"; return 1; }
}

opensearch_cluster_is_green_or_yellow() {
    local status
    status=$(compose exec -T opensearch curl -s localhost:9200/_cluster/health |
        sed -n 's/.*"status":"\([a-z]*\)".*/\1/p') || status=""
    [[ $status == green || $status == yellow ]] || { echo "status is '${status:-unreachable}'"; return 1; }
}

postgres_lists_database() {
    compose exec -T postgres sh -c \
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select datname from pg_database"' |
        grep -qFx "$1"
}

check_static() {
    local mode config prod_config dev_config other_config
    COMPOSE_FILES=(-f "$BASE_FILE"); prod_config=$(compose config --format json) || prod_config="{}"
    COMPOSE_FILES=(-f "$BASE_FILE" -f "$DEV_FILE"); dev_config=$(compose config --format json) || dev_config="{}"
    for mode in prod dev; do
        COMPOSE_FILES=(-f "$BASE_FILE")
        if [[ $mode == dev ]]; then
            COMPOSE_FILES+=(-f "$DEV_FILE")
            config=$dev_config; other_config=$prod_config
        else
            config=$prod_config; other_config=$dev_config
        fi
        if [[ $config == "{}" ]]; then
            fail "$mode: docker compose config (is .env present?)"
            continue
        fi
        check "$mode: every published port binds 127.0.0.1" policy_violations loopback-only "$config"
        check "$mode: no service mounts the Docker socket" policy_violations no-docker-socket "$config"
        check "$mode: built images are not shared with the other compose file" \
            policy_violations distinct-build-image-tags "$config" "${other_config:-{\}}"
        if [[ $mode == prod ]]; then
            check "prod: only the frontend publishes a port" policy_violations frontend-only "$config"
        else
            check "dev: the frontend publishes only the Vite port" policy_violations dev-frontend-vite-only "$config"
        fi
    done
}

check_postgres_databases() {
    local names db
    if ! names=$(compose exec -T postgres printenv POSTGRES_DB CAPE_DB_NAME); then
        fail "postgres: cannot read database names (is the stack up?)"
        return
    fi
    for db in $names; do
        check "postgres has database $db" postgres_lists_database "$db"
    done
}

check_http() {
    local service=$1 container_port=$2 path=$3 address
    if ! address=$(compose port "$service" "$container_port"); then
        fail "$service port $container_port is not published"
        return
    fi
    check "GET http://$address$path returns 200" http_status_is_200 "http://$address$path"
}

check_running_stack() {
    check_postgres_databases
    check "opensearch cluster health is green or yellow" opensearch_cluster_is_green_or_yellow
}

check_prod() {
    COMPOSE_FILES=(-f "$BASE_FILE")
    check_running_stack
    check_http frontend 80 /api/system/health
}

check_dev() {
    COMPOSE_FILES=(-f "$BASE_FILE" -f "$DEV_FILE")
    check_running_stack
    check_http backend 8000 /api/system/health
    check_http frontend 5173 /api/system/health
}

case "${1:-}" in
    static) check_static ;;
    prod) check_prod ;;
    dev) check_dev ;;
    *) echo "usage: smoke.sh static|prod|dev" >&2; exit 2 ;;
esac

exit "$failed"
