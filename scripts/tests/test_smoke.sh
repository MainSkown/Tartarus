#!/usr/bin/env bash
# Tests scripts/smoke.sh with `docker` and `curl` replaced by stubs on PATH.
set -uo pipefail

SMOKE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/smoke.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0

port_entry() { printf '{"mode":"ingress","host_ip":"%s","target":%s,"published":"%s","protocol":"tcp"}' "$1" "$2" "$3"; }

CAPE_STORAGE_VOLUME='{"type":"volume","source":"cape-storage","target":"/opt/CAPEv2/storage"}'
ISO_MOUNT='{"type":"bind","source":"/repo/data/iso","target":"/data/iso","read_only":true}'
CAPE_NETWORKS='{"tartarus-internal":null,"tartarus-control":null,"tartarus-cape-db":null}'
DEFAULT_CAPE='{"image":"tartarus-cape:latest","build":{},"privileged":true,"devices":[{"source":"/dev/kvm","target":"/dev/kvm","permissions":"rwm"}],"volumes":['"$CAPE_STORAGE_VOLUME,$ISO_MOUNT"'],"networks":'"$CAPE_NETWORKS"'}'
CAPE_STORAGE_READ_ONLY='{"type":"volume","source":"cape-storage","target":"/cape-storage","read_only":true}'
SAMPLE_STORE='{"type":"volume","source":"sample-store","target":"/data/samples"}'
DEFAULT_BACKEND_VOLUMES="$CAPE_STORAGE_READ_ONLY,$SAMPLE_STORE"
BACKEND_NETWORKS='"networks":{"tartarus-web":null,"tartarus-db":null,"tartarus-search":null,"tartarus-internal":null,"tartarus-control":null}'
PROD_NETWORKS='{"tartarus-web":{},"tartarus-internal":{},"tartarus-db":{"internal":true},"tartarus-search":{"internal":true},"tartarus-cape-db":{"internal":true},"tartarus-control":{"internal":true}}'
DEV_NETWORKS='{"tartarus-web":{},"tartarus-internal":{},"tartarus-dev":{},"tartarus-db":{"internal":true},"tartarus-search":{"internal":true},"tartarus-cape-db":{"internal":true},"tartarus-control":{"internal":true}}'

write_prod_config() {
    local frontend_ip=$1 backend_ports=$2 backend_image=${3:-tartarus-backend:latest} frontend_image=${4:-tartarus-frontend:latest}
    local cape=${5:-$DEFAULT_CAPE} backend_extra=${6:-} backend_volumes=${7-$DEFAULT_BACKEND_VOLUMES}
    local postgres_image=${8:-postgres:16}
    cat >"$STUB_DIR/config-prod.json" <<JSON
{"services":{
  "frontend":{"image":"$frontend_image","build":{"target":"production-stage"},"ports":[$(port_entry "$frontend_ip" 80 8080)],"networks":{"tartarus-web":null}},
  "backend":{"image":"$backend_image","build":{"target":"prod"},"ports":[$backend_ports],"volumes":[$backend_volumes],$BACKEND_NETWORKS${backend_extra:+,$backend_extra}},
  "cape":$cape,
  "postgres":{"image":"$postgres_image","volumes":[{"type":"volume","source":"pg-data","target":"/var/lib/postgresql/data"}],"networks":{"tartarus-db":null,"tartarus-cape-db":null}},
  "opensearch":{"volumes":[{"type":"volume","source":"os-data","target":"/usr/share/opensearch/data"}],"networks":{"tartarus-search":null}}
},"networks":$PROD_NETWORKS}
JSON
}

write_dev_config() {
    local postgres_ip=$1 backend_volumes=$2 extra_frontend_ports=${3:-} backend_image=${4:-tartarus-backend:dev} frontend_image=${5:-tartarus-frontend:dev}
    local cape=${6:-$DEFAULT_CAPE} postgres_image=${7:-postgres:16}
    cat >"$STUB_DIR/config-dev.json" <<JSON
{"services":{
  "frontend":{"image":"$frontend_image","build":{"target":"dev-stage"},"ports":[$(port_entry 127.0.0.1 5173 5173)${extra_frontend_ports:+,$extra_frontend_ports}],"networks":{"tartarus-web":null}},
  "backend":{"image":"$backend_image","build":{"target":"dev"},"ports":[$(port_entry 127.0.0.1 8000 8000)],"volumes":[$backend_volumes],$BACKEND_NETWORKS},
  "cape":$cape,
  "postgres":{"image":"$postgres_image","ports":[$(port_entry "$postgres_ip" 5432 5432)],"networks":{"tartarus-db":null,"tartarus-cape-db":null,"tartarus-dev":null}},
  "opensearch":{"ports":[$(port_entry 127.0.0.1 9200 9200)],"networks":{"tartarus-search":null,"tartarus-dev":null}}
},"networks":$DEV_NETWORKS}
JSON
}

install_stubs() {
    cat >"$STUB_DIR/bin/docker" <<'STUB'
#!/usr/bin/env bash
without_profiled_services() {
    python3 -I -c 'import json, sys; c = json.load(sys.stdin); c["services"] = {n: s for n, s in c["services"].items() if "profiles" not in s}; print(json.dumps(c))'
}
args="$*"
case "$args" in
    *"config --format json"*)
        if [[ $args == *docker-compose.dev.yml* ]]; then config="$STUB_DIR/config-dev.json"; else config="$STUB_DIR/config-prod.json"; fi
        if [[ $args == *"--profile"* ]]; then cat "$config"; else without_profiled_services <"$config"; fi ;;
    *"exec -T postgres printenv"*) cat "$STUB_DIR/postgres-env" ;;
    *"exec -T postgres"*) cat "$STUB_DIR/postgres-databases" ;;
    *"exec -T opensearch"*) cat "$STUB_DIR/opensearch-health" ;;
    *" port "*) cat "$STUB_DIR/port-${args##* port }" 2>/dev/null || exit 1 ;;
    *) echo "unstubbed docker call: $args" >&2; exit 99 ;;
esac
STUB
    cat >"$STUB_DIR/bin/curl" <<'STUB'
#!/usr/bin/env bash
url="${*: -1}"
host_port="${url#http://}"
path="/${host_port#*/}"
host_port="${host_port%%/*}"
port="${host_port##*:}"
cat "$STUB_DIR/http-${port}${path//\//_}" 2>/dev/null || cat "$STUB_DIR/http-${port}" 2>/dev/null || printf 000
STUB
    chmod +x "$STUB_DIR/bin/docker" "$STUB_DIR/bin/curl"
}

new_sandbox() {
    STUB_DIR="$(mktemp -d -p "$WORK_DIR")"
    export STUB_DIR
    mkdir "$STUB_DIR/bin"
    install_stubs
    write_prod_config 127.0.0.1 ""
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES"
    printf 'tartarus\ncape\n' >"$STUB_DIR/postgres-databases"
    printf 'tartarus\ncape\n' >"$STUB_DIR/postgres-env"
    printf '{"cluster_name":"tartarus","status":"green"}' >"$STUB_DIR/opensearch-health"
    echo 127.0.0.1:8080 >"$STUB_DIR/port-frontend 80"
    echo 127.0.0.1:5173 >"$STUB_DIR/port-frontend 5173"
    echo 127.0.0.1:8000 >"$STUB_DIR/port-backend 8000"
    for port in 8080 5173 8000; do printf 200 >"$STUB_DIR/http-$port"; done
}

run_smoke() {
    OUTPUT="$(PATH="$STUB_DIR/bin:$PATH" bash "$SMOKE" "$@" 2>&1)"
    STATUS=$?
}

expect_pass() {
    if [[ $STATUS -ne 0 || $OUTPUT == *"[FAIL]"* ]]; then
        echo "  expected success, got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

expect_fail_mentioning() {
    if [[ $STATUS -eq 0 || $OUTPUT != *"[FAIL]"*"$1"* ]]; then
        echo "  expected a [FAIL] line mentioning '$1', got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

run_test() {
    local name=$1
    new_sandbox
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

REAL_PYTHON="$(command -v python3)"

record_python_arguments() {
    cat >"$STUB_DIR/bin/python3" <<STUB
#!/usr/bin/env bash
printf '%s\\n' "\$*" >>"\$STUB_DIR/python-arguments"
exec "$REAL_PYTHON" "\$@"
STUB
    chmod +x "$STUB_DIR/bin/python3"
}

test_static_keeps_resolved_secrets_off_every_command_line() {
    write_prod_config 127.0.0.1 "" "" "" "" '"environment":{"CAPE_API_TOKEN":"SECRET-MARKER-123"}'
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES"
    record_python_arguments
    run_smoke static
    expect_pass || return 1
    if [[ ! -s $STUB_DIR/python-arguments ]]; then echo "  the python stub was never called"; return 1; fi
    if grep -q SECRET-MARKER-123 "$STUB_DIR/python-arguments"; then
        echo "  the resolved config reached a python command line"; return 1
    fi
}

test_static_output_never_contains_resolved_secrets() {
    write_prod_config 127.0.0.1 "" "" "" "" '"environment":{"CAPE_API_TOKEN":"SECRET-MARKER-123"},"privileged":true'
    run_smoke static
    [[ $OUTPUT != *SECRET-MARKER-123* ]]
}

edit_config() {
    local file=$STUB_DIR/config-$1.json
    python3 -I - "$file" "$2" <<'PY'
import json, sys
path, snippet = sys.argv[1], sys.argv[2]
config = json.load(open(path))
exec(snippet)
json.dump(config, open(path, "w"))
PY
}

test_static_rejects_opensearch_shared_with_the_frontend() {
    edit_config prod 'config["services"]["frontend"]["networks"]["tartarus-search"] = None'
    run_smoke static
    expect_fail_mentioning "opensearch is reachable by frontend"
}

test_static_rejects_opensearch_shared_with_cape() {
    edit_config prod 'config["services"]["cape"]["networks"]["tartarus-search"] = None'
    run_smoke static
    expect_fail_mentioning "opensearch is reachable by cape"
}

test_static_rejects_opensearch_shared_with_postgres_in_prod() {
    edit_config prod 'config["services"]["opensearch"]["networks"]["tartarus-db"] = None'
    run_smoke static
    expect_fail_mentioning "opensearch is reachable by postgres"
}

test_static_accepts_postgres_next_to_opensearch_in_dev() {
    run_smoke static
    expect_pass && [[ $OUTPUT == *"dev: opensearch shares a network only with"* ]]
}

test_static_rejects_opensearch_on_a_network_with_a_route_out() {
    edit_config prod 'config["services"]["opensearch"]["networks"]["tartarus-internal"] = None'
    run_smoke static
    expect_fail_mentioning "opensearch joins tartarus-internal, which is not internal"
}

test_static_rejects_postgres_on_a_network_with_a_route_out_in_prod() {
    edit_config prod 'config["services"]["postgres"]["networks"]["tartarus-web"] = None'
    run_smoke static
    expect_fail_mentioning "postgres joins tartarus-web, which is not internal"
}

test_static_rejects_dev_postgres_on_a_route_out_network_other_than_the_dev_one() {
    edit_config dev 'config["services"]["postgres"]["networks"]["tartarus-internal"] = None'
    run_smoke static
    expect_fail_mentioning "postgres joins tartarus-internal, which is not internal"
}

test_static_rejects_prod_publishing_network_for_a_database() {
    edit_config prod 'config["networks"]["tartarus-dev"] = {}; config["services"]["postgres"]["networks"]["tartarus-dev"] = None'
    run_smoke static
    expect_fail_mentioning "postgres joins tartarus-dev, which is not internal"
}

test_static_rejects_a_database_network_that_lost_its_internal_flag() {
    edit_config prod 'config["networks"]["tartarus-search"] = {}'
    run_smoke static
    expect_fail_mentioning "opensearch joins tartarus-search, which is not internal"
}

test_static_rejects_the_frontend_sharing_a_network_with_cape() {
    edit_config prod 'config["services"]["frontend"]["networks"]["tartarus-internal"] = None'
    run_smoke static
    expect_fail_mentioning "frontend shares a network with cape"
}

test_static_rejects_the_frontend_sharing_a_network_with_postgres() {
    edit_config prod 'config["services"]["frontend"]["networks"]["tartarus-db"] = None'
    run_smoke static
    expect_fail_mentioning "frontend shares a network with postgres"
}

test_static_rejects_cape_sharing_a_network_with_the_frontend() {
    edit_config prod 'config["services"]["cape"]["networks"]["tartarus-web"] = None'
    run_smoke static
    expect_fail_mentioning "cape shares a network with frontend"
}

test_static_passes_on_loopback_only_config() {
    run_smoke static
    expect_pass && [[ $OUTPUT == *"[ OK ]"* ]]
}

test_static_rejects_prod_port_on_all_interfaces() {
    write_prod_config 0.0.0.0 ""
    run_smoke static
    expect_fail_mentioning "frontend"
}

test_static_rejects_prod_port_without_host_ip() {
    write_prod_config "" ""
    run_smoke static
    expect_fail_mentioning "frontend"
}

test_static_rejects_dev_port_on_all_interfaces() {
    write_dev_config 0.0.0.0 "$DEFAULT_BACKEND_VOLUMES"
    run_smoke static
    expect_fail_mentioning "postgres"
}

test_static_rejects_prod_publishing_more_than_frontend() {
    write_prod_config 127.0.0.1 "$(port_entry 127.0.0.1 8000 8000)"
    run_smoke static
    expect_fail_mentioning "only the frontend"
}

test_static_rejects_docker_socket_mount() {
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES"',{"type":"bind","source":"/var/run/docker.sock","target":"/var/run/docker.sock"}'
    run_smoke static
    expect_fail_mentioning "docker.sock"
}

test_static_rejects_dev_frontend_also_publishing_prod_port() {
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES" "$(port_entry 127.0.0.1 80 8080)"
    run_smoke static
    expect_fail_mentioning "8080"
}

test_static_rejects_dev_and_prod_sharing_an_image_tag() {
    write_prod_config 127.0.0.1 "" "tartarus-backend:latest" "tartarus-frontend:latest"
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES" "" "tartarus-backend:latest" "tartarus-frontend:dev"
    run_smoke static
    expect_fail_mentioning "backend"
}

test_static_rejects_cape_publishing_a_port() {
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES" "" "" "" '{"privileged":true,"ports":['"$(port_entry 127.0.0.1 16509 16509)"']}'
    run_smoke static
    expect_fail_mentioning "cape publishes"
}

test_static_rejects_a_privileged_service_other_than_cape() {
    write_prod_config 127.0.0.1 "" "" "" "" '"privileged":true'
    run_smoke static
    expect_fail_mentioning "backend is privileged"
}

test_static_rejects_cape_mounting_the_iso_read_write() {
    write_prod_config 127.0.0.1 "" "" "" '{"privileged":true,"volumes":[{"type":"bind","source":"/repo/data/iso","target":"/data/iso","read_only":false}],"networks":{"tartarus-internal":null}}'
    run_smoke static
    expect_fail_mentioning "read-write"
}

test_static_rejects_cape_not_mounting_the_iso() {
    write_prod_config 127.0.0.1 "" "" "" '{"privileged":true,"networks":{"tartarus-internal":null}}'
    run_smoke static
    expect_fail_mentioning "does not mount /data/iso"
}

test_static_rejects_host_networking() {
    write_prod_config 127.0.0.1 "" "" "" '{"privileged":true,"network_mode":"host"}'
    run_smoke static
    expect_fail_mentioning "cape uses the host network"
}

test_static_checks_services_behind_a_profile() {
    python3 -I - "$STUB_DIR/config-prod.json" <<'PY'
import json, sys
path = sys.argv[1]
config = json.load(open(path))
config["services"]["debug"] = {"profiles": ["debug"], "privileged": True}
json.dump(config, open(path, "w"))
PY
    run_smoke static
    expect_fail_mentioning "debug is privileged"
}

test_static_rejects_backend_mounting_cape_storage_read_write() {
    write_prod_config 127.0.0.1 "" "" "" "" "" '{"type":"volume","source":"cape-storage","target":"/cape-storage"},'"$SAMPLE_STORE"
    run_smoke static
    expect_fail_mentioning "backend mounts cape-storage read-write"
}

test_static_rejects_backend_not_mounting_cape_storage() {
    write_prod_config 127.0.0.1 "" "" "" "" "" "$SAMPLE_STORE"
    run_smoke static
    expect_fail_mentioning "backend does not mount cape-storage"
}

test_static_rejects_dev_backend_mounting_cape_storage_read_write() {
    write_dev_config 127.0.0.1 '{"type":"volume","source":"cape-storage","target":"/cape-storage"},'"$SAMPLE_STORE"
    run_smoke static
    expect_fail_mentioning "backend mounts cape-storage read-write"
}

test_static_rejects_a_third_service_mounting_cape_storage() {
    python3 -I - "$STUB_DIR/config-prod.json" <<'PY'
import json, sys
path = sys.argv[1]
config = json.load(open(path))
config["services"]["frontend"]["volumes"] = [
    {"type": "volume", "source": "cape-storage", "target": "/cape-storage", "read_only": True}
]
json.dump(config, open(path, "w"))
PY
    run_smoke static
    expect_fail_mentioning "frontend mounts cape-storage"
}

test_static_rejects_cape_storage_bind_mounted_from_the_host_into_backend() {
    write_prod_config 127.0.0.1 "" "" "" "" "" '{"type":"bind","source":"/srv/cape","target":"/cape-storage","read_only":true},'"$SAMPLE_STORE"
    run_smoke static
    expect_fail_mentioning "backend does not mount cape-storage"
}

test_static_rejects_backend_not_mounting_sample_store() {
    write_prod_config 127.0.0.1 "" "" "" "" "" "$CAPE_STORAGE_READ_ONLY"
    run_smoke static
    expect_fail_mentioning "backend does not mount sample-store"
}

test_static_rejects_cape_mounting_sample_store() {
    write_prod_config 127.0.0.1 "" "" "" '{"privileged":true,"volumes":['"$ISO_MOUNT,$SAMPLE_STORE"'],"networks":{"tartarus-internal":null}}'
    run_smoke static
    expect_fail_mentioning "cape mounts sample-store"
}

test_static_rejects_a_pulled_image_pinned_differently_in_dev() {
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES" "" "" "" "" postgres:15
    run_smoke static
    expect_fail_mentioning "postgres"
}

test_static_rejects_cape_tagged_differently_in_dev() {
    write_dev_config 127.0.0.1 "$DEFAULT_BACKEND_VOLUMES" "" "" "" '{"image":"tartarus-cape:dev","build":{},"privileged":true,"volumes":['"$ISO_MOUNT"']}'
    run_smoke static
    expect_fail_mentioning "cape"
}

test_prod_passes_on_healthy_stack() {
    run_smoke prod
    expect_pass
}

test_prod_accepts_yellow_cluster() {
    printf '{"status":"yellow"}' >"$STUB_DIR/opensearch-health"
    run_smoke prod
    expect_pass
}

test_prod_fails_when_cape_database_missing() {
    printf 'tartarus\n' >"$STUB_DIR/postgres-databases"
    run_smoke prod
    expect_fail_mentioning "cape"
}

test_prod_fails_on_red_cluster() {
    printf '{"status":"red"}' >"$STUB_DIR/opensearch-health"
    run_smoke prod
    expect_fail_mentioning "opensearch"
}

test_prod_fails_when_health_endpoint_errors() {
    printf 503 >"$STUB_DIR/http-8080"
    run_smoke prod
    expect_fail_mentioning "/api/system/health"
}

test_prod_fails_when_database_is_not_migrated() {
    printf 500 >"$STUB_DIR/http-8080_api_settings"
    run_smoke prod
    expect_fail_mentioning "/api/settings"
}

test_dev_fails_when_database_is_not_migrated() {
    printf 500 >"$STUB_DIR/http-8000_api_settings"
    run_smoke dev
    expect_fail_mentioning "/api/settings"
}

test_prod_fails_when_stack_is_down() {
    rm "$STUB_DIR/postgres-databases" "$STUB_DIR/postgres-env"
    run_smoke prod
    expect_fail_mentioning "postgres"
}

test_dev_passes_on_healthy_stack() {
    run_smoke dev
    expect_pass
}

test_dev_fails_when_vite_proxy_is_broken() {
    printf 502 >"$STUB_DIR/http-5173"
    run_smoke dev
    expect_fail_mentioning "5173"
}

test_dev_fails_when_backend_port_unreachable() {
    printf 000 >"$STUB_DIR/http-8000"
    run_smoke dev
    expect_fail_mentioning "8000"
}

test_unknown_mode_prints_usage_and_exits_2() {
    run_smoke bogus
    [[ $STATUS -eq 2 && $OUTPUT == *"usage"* ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
