#!/usr/bin/env bash
# Tests scripts/verify-guest.sh with `docker` and `sleep` replaced by stubs on PATH. The docker
# stub answers each call from a fixture file and walks the submitted task through
# pending -> running -> reported, so the "live .bson while running" logic is exercised.
set -uo pipefail

VERIFY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verify-guest.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0

fixture() { printf '%s\n' "$2" >"$STUB_DIR/f/$1"; }

install_stubs() {
    cat >"$STUB_DIR/bin/docker" <<'STUB'
#!/usr/bin/env bash
f="$STUB_DIR/f"
show() { cat "$f/$1"; }
args="$*"
echo "$args" >>"$STUB_DIR/calls"
next_status() {
    local n; n=$(cat "$STUB_DIR/polls" 2>/dev/null || echo 0); echo $((n + 1)) >"$STUB_DIR/polls"
    sed -n "$((n + 1))p" "$f/status-sequence" | grep . || tail -n 1 "$f/status-sequence"
}
case "$args" in
    *"up -d --wait"*) [[ -e $f/cape-unhealthy && $args == *cape* ]] && exit 1; exit 0 ;;
    *"printenv CAPE_API_TOKEN"*) echo test-token ;;
    *"dominfo win"*) [[ -e $f/no-domain ]] && exit 1; echo "Name: win" ;;
    *"snapshot-list win --name"*) show snapshots ;;
    *"snapshot-revert"*) [[ -e $f/revert-fails ]] && exit 1; exit 0 ;;
    *"curl -s -o /dev/null -w %{http_code} -m 5 http://192.168.150.10:8000/"*) show agent-code ;;
    *"machines/list"*) show machines ;;
    *"ss -Hltn"*) show resultserver ;;
    *"tasks/create/file"*) show submit ;;
    *"tasks/status"*) printf '{"error": false, "data": "%s"}\n' "$(next_status)" ;;
    *"logs/*.bson"*) [[ $(cat "$STUB_DIR/polls" 2>/dev/null) -ge ${BSON_FROM_POLL:-2} ]] && [[ ! -e $f/no-bson ]] ;;
    *"reports/report.json"*" | head -n1"*) show report-domain ;;
    *"test -f"*"report.json"*) [[ ! -e $f/no-report ]] ;;
    *"logs tt-callback"*) show callback-log ;;
    *"8000/execute"*) show agent-execute ;;
    *"8000/retrieve"*) show agent-provision-log ;;
    *"run -d --name tt-callback"* | *"rm -f tt-callback"*) ;;
    *"exec -T cape"* | *"compose"*) ;;
    *) echo "unstubbed docker call: $args" >&2; exit 99 ;;
esac
STUB
    printf '#!/usr/bin/env bash\nexit 0\n' >"$STUB_DIR/bin/sleep"
    chmod +x "$STUB_DIR"/bin/*
}

healthy_fixtures() {
    fixture snapshots 'tartarus-clean'
    fixture agent-code '200'
    fixture machines '{"error": false, "data": [{"name": "win", "label": "win", "ip": "192.168.150.10"}]}'
    fixture resultserver 'LISTEN 0 5 192.168.150.1:2042 0.0.0.0:*'
    fixture submit '{"error": false, "data": {"task_ids": [7]}}'
    printf 'pending\nrunning\nrunning\nrunning\ncompleted\nreported\n' >"$STUB_DIR/f/status-sequence"
    fixture report-domain 'tartarus-selftest.example'
    fixture callback-log 'CALLBACK {"task_id": 7}'
    fixture agent-execute '{"message": "ok", "stdout": "FACT system.manufacturer=Dell Inc.\r\nFACT cpu.hypervisor_present=False\r\n"}'
    fixture agent-provision-log $'2026-10-13 03:50:00  STEP disable Windows Update\r\n2026-10-13 03:50:01    ok'
    mkdir -p "$STUB_DIR/tmp/tt-guest-verify"
    : >"$STUB_DIR/tmp/tt-guest-verify/benign.exe"
}

new_sandbox() {
    STUB_DIR="$(mktemp -d -p "$WORK_DIR")"
    export STUB_DIR
    mkdir "$STUB_DIR/bin" "$STUB_DIR/f" "$STUB_DIR/tmp"
    install_stubs
    healthy_fixtures
}

run_verify() {
    OUTPUT="$(PATH="$STUB_DIR/bin:$PATH" TMPDIR="$STUB_DIR/tmp" GUEST_AGENT_TIMEOUT=1 GUEST_REGISTRATION_TIMEOUT=1 \
        GUEST_ANALYSIS_TIMEOUT=3 CAPE_API_TOKEN=test-token bash "$VERIFY" "$@" 2>&1)"
    STATUS=$?
}

expect_pass() {
    if [[ $STATUS -ne 0 || $OUTPUT == *"[FAIL]"* ]]; then
        echo "  expected success, got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

expect_fail_mentioning() {
    if [[ $STATUS -eq 0 || $OUTPUT != *"[FAIL] $1"* ]]; then
        echo "  expected a [FAIL] line starting '$1', got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

run_test() {
    local name=$1
    new_sandbox
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_passes_when_every_check_holds() {
    run_verify
    expect_pass || return 1
    local number
    for number in 8 9 10 11 12; do
        [[ $OUTPUT == *"[ OK ] $number "* ]] || { echo "  no [ OK ] line for check $number"; echo "$OUTPUT" | sed 's/^/    /'; return 1; }
    done
}

test_reports_guest_facts_and_provisioning_as_info() {
    run_verify
    [[ $OUTPUT == *"[INFO] guest: system.manufacturer=Dell Inc."* && $OUTPUT == *"[INFO] provision: STEP disable Windows Update"* ]] ||
        { echo "  facts or provisioning not reported"; echo "$OUTPUT" | sed 's/^/    /'; return 1; }
}

test_stops_early_without_a_built_guest() {
    : >"$STUB_DIR/f/no-domain"
    run_verify
    expect_fail_mentioning "no 'win' domain"
}

test_check9_fails_without_the_snapshot() {
    fixture snapshots ''
    run_verify
    expect_fail_mentioning "9 snapshot"
}

test_check9_fails_when_cape_does_not_list_the_guest() {
    fixture machines '{"error": false, "data": []}'
    run_verify
    expect_fail_mentioning "9 registration"
}

test_check11_fails_when_resultserver_binds_elsewhere() {
    fixture resultserver 'LISTEN 0 5 0.0.0.0:2042 0.0.0.0:*'
    run_verify
    expect_fail_mentioning "11 resultserver"
}

test_check8_fails_when_the_agent_never_answers() {
    fixture agent-code '000'
    run_verify
    expect_fail_mentioning "8 guest"
}

test_check10_fails_when_the_task_fails_analysis() {
    printf 'pending\nrunning\nfailed_analysis\n' >"$STUB_DIR/f/status-sequence"
    run_verify
    expect_fail_mentioning "10 analysis"
}

test_check10_live_fails_when_bson_only_appears_after_the_run() {
    BSON_FROM_POLL=5 run_verify
    expect_fail_mentioning "10 live"
}

test_check10_fails_without_a_report() {
    : >"$STUB_DIR/f/no-report"
    run_verify
    expect_fail_mentioning "10 final"
}

test_check10_fails_when_the_callback_never_arrives() {
    fixture callback-log ''
    run_verify
    expect_fail_mentioning "10 callback"
}

test_check10_submits_without_free_mode() {
    run_verify
    ! grep -q 'free=' "$STUB_DIR/calls" || { echo "  submission disables capemon with free="; return 1; }
}

test_removes_only_its_own_override_and_never_the_permanent_reporting_config() {
    run_verify
    expect_pass || return 1
    local removals call
    removals=$(grep -E 'exec -T cape rm ' "$STUB_DIR/calls")
    [[ -n $removals ]] || { echo "  expected the temporary callback.conf to be removed"; return 1; }
    while read -r call; do
        [[ $call == *"rm -f /opt/CAPEv2/custom/conf/reporting.conf.d/callback.conf" ]] ||
            { echo "  removes something other than the temporary override: $call"; return 1; }
    done <<<"$removals"
    ! grep -qE '> */opt/CAPEv2/custom/conf/reporting\.conf( |$)' "$STUB_DIR/calls" ||
        { echo "  writes over the permanent reporting.conf"; return 1; }
}

test_writes_its_override_into_the_directory_that_layers_over_reporting_conf() {
    run_verify
    grep -q '> /opt/CAPEv2/custom/conf/reporting.conf.d/callback.conf' "$STUB_DIR/calls" ||
        { echo "  override is not written to reporting.conf.d/callback.conf"; return 1; }
}

test_does_not_need_the_cape_compose_profile() {
    run_verify
    ! grep -q -- '--profile' "$STUB_DIR/calls" || { echo "  still passes --profile"; return 1; }
}

test_check12_fails_when_cape_does_not_come_back() {
    : >"$STUB_DIR/f/cape-unhealthy"
    run_verify
    [[ $STATUS -ne 0 ]]
}

test_unknown_argument_prints_usage_and_exits_2() {
    run_verify --bogus
    [[ $STATUS -eq 2 && $OUTPUT == *"usage"* ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
