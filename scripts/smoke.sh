#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

BASE_FILE=docker-compose.yml
DEV_FILE=docker-compose.dev.yml
failed=0
MODE=

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

compose_all_profiles_config() { compose --profile '*' config --format json; }

# The resolved compose config holds every secret, so it travels over stdin, never in an argument list
# (which any local user can read from /proc while the script runs). printf is a builtin: no process
# is spawned with the config in its arguments.
policy_violations() {
    printf '{"mode":"%s","config":%s,"other":%s}' "$MODE" "$2" "${3:-{\}}" |
        python3 -I -c "$POLICY_PROGRAM" "$1"
}

IFS= read -r -d '' POLICY_PROGRAM <<'PY' || true
import json
import sys

check = sys.argv[1]
payload = json.load(sys.stdin)
config = payload["config"]
services = config["services"]
published = [(name, port) for name, svc in services.items() for port in svc.get("ports", [])]


def networks_of(name):
    return set(services.get(name, {}).get("networks") or {})


def peers_of(name):
    return {other for other in services if other != name and networks_of(other) & networks_of(name)}


def non_internal_joins(name, publishing_networks):
    declared = config.get("networks", {})
    return [
        f"{name} joins {network}, which is not internal"
        for network in sorted(networks_of(name) - publishing_networks)
        if not declared.get(network, {}).get("internal")
    ]


def unexpected_peers(name, allowed):
    return [f"{name} is reachable by {peer}" if name == "opensearch" else f"{name} shares a network with {peer}"
            for peer in sorted(peers_of(name) - allowed)]


# Docker publishes a port only from a network that has a route out, so in dev the databases join
# one more network for that alone, and postgres is then next to opensearch on it.
dev = payload["mode"] == "dev"
publishing_networks = {"tartarus-dev"} if dev else set()


def volume_mounts(service, volume):
    return [m for m in service.get("volumes", []) if m.get("type") == "volume" and m.get("source") == volume]


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
    other = payload["other"].get("services", {})
    collisions = [
        f"{name} is tagged {image!r} in both files but built differently"
        for name, svc in services.items()
        if "build" in svc
        for image in [svc.get("image")]
        if image
        and other.get(name, {}).get("image") == image
        and other.get(name, {}).get("build") != svc["build"]
    ]
    print("; ".join(collisions))
    sys.exit(1 if collisions else 0)
elif check == "same-build-same-image-tag":
    other = payload["other"].get("services", {})
    problems = [
        f"{name} is tagged {svc['image']!r} here and {other[name]['image']!r} in the other compose file"
        for name, svc in services.items()
        if name in other
        and svc.get("image")
        and other[name].get("image")
        and svc.get("build") == other[name].get("build")
        and svc["image"] != other[name]["image"]
    ]
elif check == "cape-storage-read-only-in-backend":
    mounts = volume_mounts(services.get("backend", {}), "cape-storage")
    if not mounts:
        problems = ["backend does not mount cape-storage"]
    else:
        problems = ["backend mounts cape-storage read-write" for mount in mounts if not mount.get("read_only")]
elif check == "cape-storage-only-in-backend-and-cape":
    problems = [
        f"{name} mounts cape-storage"
        for name, svc in services.items()
        if name not in ("backend", "cape") and volume_mounts(svc, "cape-storage")
    ]
elif check == "sample-store-only-in-backend":
    problems = [] if volume_mounts(services.get("backend", {}), "sample-store") else ["backend does not mount sample-store"]
    problems += [
        f"{name} mounts sample-store"
        for name, svc in services.items()
        if name != "backend" and volume_mounts(svc, "sample-store")
    ]
elif check == "opensearch-reachable-only-by-backend":
    problems = unexpected_peers("opensearch", {"backend", "postgres"} if dev else {"backend"})
elif check == "databases-only-on-internal-networks":
    problems = non_internal_joins("postgres", publishing_networks) + non_internal_joins("opensearch", publishing_networks)
elif check == "frontend-reaches-only-backend":
    problems = unexpected_peers("frontend", {"backend"})
elif check == "cape-reaches-only-backend-and-postgres":
    problems = unexpected_peers("cape", {"backend", "postgres"})
elif check == "cape-no-ports":
    problems = [f"cape publishes {port.get('published')}" for name, port in published if name == "cape"]
elif check == "cape-iso-readonly":
    cape = services.get("cape", {})
    iso_mounts = [v for v in cape.get("volumes", []) if v.get("target") == "/data/iso"]
    if not iso_mounts:
        problems = ["cape does not mount /data/iso"]
    else:
        problems = ["cape mounts /data/iso read-write" for v in iso_mounts if not v.get("read_only")]
elif check == "only-cape-privileged":
    problems = [f"{name} is privileged" for name, svc in services.items() if svc.get("privileged") and name != "cape"]
elif check == "no-host-network":
    problems = [f"{name} uses the host network" for name, svc in services.items() if svc.get("network_mode") == "host"]
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
    COMPOSE_FILES=(-f "$BASE_FILE"); prod_config=$(compose_all_profiles_config) || prod_config="{}"
    COMPOSE_FILES=(-f "$BASE_FILE" -f "$DEV_FILE"); dev_config=$(compose_all_profiles_config) || dev_config="{}"
    for mode in prod dev; do
        MODE=$mode
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
        check "$mode: cape publishes no ports" policy_violations cape-no-ports "$config"
        check "$mode: cape mounts ./data/iso read-only" policy_violations cape-iso-readonly "$config"
        check "$mode: no service other than cape is privileged" policy_violations only-cape-privileged "$config"
        check "$mode: no service uses the host network" policy_violations no-host-network "$config"
        check "$mode: backend mounts cape-storage read-only" policy_violations cape-storage-read-only-in-backend "$config"
        check "$mode: only backend and cape mount cape-storage" policy_violations cape-storage-only-in-backend-and-cape "$config"
        check "$mode: only backend mounts sample-store" policy_violations sample-store-only-in-backend "$config"
        check "$mode: opensearch shares a network only with the services that need it" \
            policy_violations opensearch-reachable-only-by-backend "$config"
        check "$mode: postgres and opensearch join internal networks only" policy_violations databases-only-on-internal-networks "$config"
        check "$mode: the frontend shares a network with the backend only" policy_violations frontend-reaches-only-backend "$config"
        check "$mode: cape shares a network with the backend and postgres only" \
            policy_violations cape-reaches-only-backend-and-postgres "$config"
        check "$mode: unchanged builds keep their image tag across both compose files" \
            policy_violations same-build-same-image-tag "$config" "${other_config:-{\}}"
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
    check_http frontend 80 /api/settings
}

check_dev() {
    COMPOSE_FILES=(-f "$BASE_FILE" -f "$DEV_FILE")
    check_running_stack
    check_http backend 8000 /api/system/health
    check_http backend 8000 /api/settings
    check_http frontend 5173 /api/system/health
}

case "${1:-}" in
    static) check_static ;;
    prod) check_prod ;;
    dev) check_dev ;;
    *) echo "usage: smoke.sh static|prod|dev" >&2; exit 2 ;;
esac

exit "$failed"
