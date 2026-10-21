#!/usr/bin/env bash
# Tests scripts/verify-isolation.sh with `docker` and `sleep` replaced by stubs on PATH. The docker stub
# answers each guest's probe from a fixture named exec-<from ip>-<target ip>, so the verdicts (blocked
# between guests, open to the gateway, a probe that never ran) are exercised without libvirt.
set -uo pipefail

VERIFY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verify-isolation.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

A_IP=192.168.150.11
B_IP=192.168.150.12
GATEWAY=192.168.150.1

failures=0
OUTPUT=""
STATUS=0

fixture() { printf '%s\n' "$2" >"$STUB_DIR/f/$1"; }

install_stubs() {
    cat >"$STUB_DIR/bin/docker" <<'STUB'
#!/usr/bin/env bash
f="$STUB_DIR/f"
args="$*"
echo "$args" >>"$STUB_DIR/calls"
case "$args" in
    *"printenv CAPE_API_TOKEN"*) echo test-token ;;
    *"printenv GUEST_SUBNET"*) ;;
    *"machines/list"*) cat "$f/machines" ;;
    *"domstate "*) guest=${args##*domstate }; [[ -e $f/running-$guest ]] && echo running || echo "shut off" ;;
    *"snapshot-revert lab1 "*) [[ -e $f/revert-fails ]] && exit 1; exit 0 ;;
    *"snapshot-revert"*) exit 0 ;;
    *"-w %{http_code}"*) cat "$f/agent-code" ;;
    *"/store"*) exit 0 ;;
    *"/execute"*)
        from=${args##*http://}; from=${from%%:*}
        target=${args##*-Target }; target=${target%% *}
        cat "$f/exec-$from-$target" 2>/dev/null || echo '{}' ;;
    *"destroy"* | *"up -d --wait"* | *" cp "*) exit 0 ;;
    *) echo "unstubbed docker call: $args" >&2; exit 99 ;;
esac
STUB
    printf '#!/usr/bin/env bash\nexit 0\n' >"$STUB_DIR/bin/sleep"
    chmod +x "$STUB_DIR"/bin/*
}

probe_answer() { # lines... -> the agent's JSON reply
    local text="" line
    for line in "$@"; do text+="$line\\r\\n"; done
    printf '{"message": "ok", "stdout": "%sDONE\\r\\n"}' "$text"
}

healthy_fixtures() {
    fixture machines "{\"error\": false, \"data\": [{\"name\": \"lab1\", \"label\": \"lab1\", \"ip\": \"$A_IP\"}, {\"name\": \"lab5\", \"label\": \"lab5\", \"ip\": \"$B_IP\"}]}"
    fixture agent-code 200
    local blocked open
    blocked=$(probe_answer "REACH tcp/8000 no" "REACH tcp/445 no" "REACH icmp no")
    open=$(probe_answer "REACH tcp/2042 yes" "REACH tcp/80 yes")
    fixture "exec-$A_IP-$B_IP" "$blocked"
    fixture "exec-$B_IP-$A_IP" "$blocked"
    fixture "exec-$A_IP-$GATEWAY" "$open"
    fixture "exec-$B_IP-$GATEWAY" "$open"
}

new_sandbox() {
    STUB_DIR="$(mktemp -d -p "$WORK_DIR")"
    export STUB_DIR
    mkdir "$STUB_DIR/bin" "$STUB_DIR/f"
    install_stubs
    healthy_fixtures
}

run_verify() {
    OUTPUT="$(PATH="$STUB_DIR/bin:$PATH" ISOLATION_AGENT_TIMEOUT=1 CAPE_API_TOKEN=test-token bash "$VERIFY" "$@" 2>&1)"
    STATUS=$?
}

dump() { echo "$OUTPUT" | sed 's/^/    /'; }

expect_status() {
    [[ $STATUS -eq $1 ]] || { echo "  expected status $1, got $STATUS"; dump; return 1; }
}

expect_line() {
    [[ $OUTPUT == *"$1"* ]] || { echo "  expected a line containing '$1'"; dump; return 1; }
}

run_test() {
    local name=$1
    new_sandbox
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_passes_when_guests_are_isolated_and_reach_the_gateway() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    [[ $OUTPUT != *"[FAIL]"* ]] || { dump; return 1; }
    expect_line "[ OK ] lab1 cannot reach lab5 on the CAPE agent (tcp/8000)" &&
        expect_line "[ OK ] lab5 reaches INetSim ($GATEWAY:80)"
}

test_fails_when_a_guest_reaches_the_other_guests_agent() {
    fixture "exec-$A_IP-$B_IP" "$(probe_answer "REACH tcp/8000 yes" "REACH tcp/445 no" "REACH icmp no")"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 cannot reach lab5 on the CAPE agent (tcp/8000)"
}

test_fails_when_a_guest_can_ping_the_other() {
    fixture "exec-$B_IP-$A_IP" "$(probe_answer "REACH tcp/8000 no" "REACH tcp/445 no" "REACH icmp yes")"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab5 cannot ping lab1"
}

test_fails_when_a_guest_loses_the_gateway() {
    fixture "exec-$B_IP-$GATEWAY" "$(probe_answer "REACH tcp/2042 yes" "REACH tcp/80 no")"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab5 reaches INetSim"
}

test_a_probe_that_never_ran_is_not_taken_for_a_blocked_one() {
    fixture "exec-$A_IP-$B_IP" '{}'
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 -> lab5: the probe ran to the end" &&
        expect_line "[FAIL] lab1 cannot reach lab5 on SMB (tcp/445) (tcp/445 -> no report"
}

test_fails_when_cape_does_not_list_a_guest() {
    run_verify lab1 lab9
    expect_status 1 && expect_line "[FAIL] setup: CAPE does not list both"
}

test_fails_when_the_agent_never_answers() {
    fixture agent-code 000
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 starts and its agent answers"
}

test_powers_off_only_the_guests_it_started() {
    : >"$STUB_DIR/f/running-lab5"
    run_verify lab1 lab5
    expect_status 0 || return 1
    grep -q "snapshot-revert lab1 tartarus-clean" "$STUB_DIR/calls" &&
        ! grep -q "snapshot-revert lab5" "$STUB_DIR/calls" &&
        grep -q "destroy lab1" "$STUB_DIR/calls" &&
        ! grep -q "destroy lab5" "$STUB_DIR/calls" || { echo "  wrong guests started or destroyed"; cat "$STUB_DIR/calls"; return 1; }
}

test_usage_error_needs_two_different_guests() {
    run_verify lab1 lab1
    expect_status 2
}

for name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do run_test "$name"; done
exit "$failures"
