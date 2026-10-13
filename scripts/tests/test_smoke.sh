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

DEFAULT_CAPE='{"profiles":["cape"],"image":"tartarus-cape:latest","build":{},"privileged":true,"devices":[{"source":"/dev/kvm","target":"/dev/kvm","permissions":"rwm"}],"networks":{"tartarus-internal":null}}'

write_prod_config() {
    local frontend_ip=$1 backend_ports=$2 backend_image=${3:-tartarus-backend:latest} frontend_image=${4:-tartarus-frontend:latest}
    local cape=${5:-$DEFAULT_CAPE} backend_extra=${6:-}
    cat >"$STUB_DIR/config-prod.json" <<JSON
{"services":{
  "frontend":{"image":"$frontend_image","build":{"target":"production-stage"},"ports":[$(port_entry "$frontend_ip" 80 8080)]},
  "backend":{"image":"$backend_image","build":{"target":"prod"},"ports":[$backend_ports],"volumes":[]${backend_extra:+,$backend_extra}},
  "cape":$cape,
  "postgres":{"volumes":[{"type":"volume","source":"pg-data","target":"/var/lib/postgresql/data"}]},
  "opensearch":{"volumes":[{"type":"volume","source":"os-data","target":"/usr/share/opensearch/data"}]}
}}
JSON
}

write_dev_config() {
    local postgres_ip=$1 backend_volumes=$2 extra_frontend_ports=${3:-} backend_image=${4:-tartarus-backend:dev} frontend_image=${5:-tartarus-frontend:dev}
    local cape=${6:-$DEFAULT_CAPE}
    cat >"$STUB_DIR/config-dev.json" <<JSON
{"services":{
  "frontend":{"image":"$frontend_image","build":{"target":"dev-stage"},"ports":[$(port_entry 127.0.0.1 5173 5173)${extra_frontend_ports:+,$extra_frontend_ports}]},
  "backend":{"image":"$backend_image","build":{"target":"dev"},"ports":[$(port_entry 127.0.0.1 8000 8000)],"volumes":[$backend_volumes]},
  "cape":$cape,
  "postgres":{"ports":[$(port_entry "$postgres_ip" 5432 5432)]},
  "opensearch":{"ports":[$(port_entry 127.0.0.1 9200 9200)]}
}}
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
    write_dev_config 127.0.0.1 ""
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
    write_dev_config 0.0.0.0 ""
    run_smoke static
    expect_fail_mentioning "postgres"
}

test_static_rejects_prod_publishing_more_than_frontend() {
    write_prod_config 127.0.0.1 "$(port_entry 127.0.0.1 8000 8000)"
    run_smoke static
    expect_fail_mentioning "only the frontend"
}

test_static_rejects_docker_socket_mount() {
    write_dev_config 127.0.0.1 '{"type":"bind","source":"/var/run/docker.sock","target":"/var/run/docker.sock"}'
    run_smoke static
    expect_fail_mentioning "docker.sock"
}

test_static_rejects_dev_frontend_also_publishing_prod_port() {
    write_dev_config 127.0.0.1 "" "$(port_entry 127.0.0.1 80 8080)"
    run_smoke static
    expect_fail_mentioning "8080"
}

test_static_rejects_dev_and_prod_sharing_an_image_tag() {
    write_prod_config 127.0.0.1 "" "tartarus-backend:latest" "tartarus-frontend:latest"
    write_dev_config 127.0.0.1 "" "" "tartarus-backend:latest" "tartarus-frontend:dev"
    run_smoke static
    expect_fail_mentioning "backend"
}

test_static_rejects_cape_publishing_a_port() {
    write_dev_config 127.0.0.1 "" "" "" "" '{"profiles":["cape"],"privileged":true,"ports":['"$(port_entry 127.0.0.1 16509 16509)"']}'
    run_smoke static
    expect_fail_mentioning "cape publishes"
}

test_static_rejects_a_privileged_service_other_than_cape() {
    write_prod_config 127.0.0.1 "" "" "" "" '"privileged":true'
    run_smoke static
    expect_fail_mentioning "backend is privileged"
}

test_static_rejects_host_networking() {
    write_prod_config 127.0.0.1 "" "" "" '{"profiles":["cape"],"privileged":true,"network_mode":"host"}'
    run_smoke static
    expect_fail_mentioning "cape uses the host network"
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
