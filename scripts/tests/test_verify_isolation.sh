#!/usr/bin/env bash
# Tests scripts/verify-isolation.sh with `docker` and `sleep` replaced by stubs on PATH. The docker stub
# stands in for the whole stack: it knows which route and which tricks (an invented address, another guest's
# address, a neighbour entry pointing at the gateway) the script has set up on a guest, and answers that
# guest's probe from a list of the probes it lets through, so the verdicts are exercised without libvirt.
# fixture allow-<scenario> holds the names a guest reaches in that scenario; anything else answers `no`.
set -uo pipefail

VERIFY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verify-isolation.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

A_IP=192.168.150.11
B_IP=192.168.150.12
GATEWAY=192.168.150.1
GATEWAY_ONLY="gateway-dns gateway-http gateway-resultserver"

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
# The real `compose exec -T` reads its stdin, which is what ate the rest of a loop's input once.
[[ $args == "compose exec"* ]] && cat >/dev/null

guest_json() { printf '{"message": "ok", "stdout": "%s"}' "$1"; }

scenario_of() { # from-ip spec-file
    local from=$1 spec=$2 source
    source=$(awk -F'\t' '$6 != "" {print $6; exit}' "$spec")
    if [[ -n $source ]]; then
        [[ $source == "$A_IP" || $source == "$B_IP" ]] && echo impersonating || echo alternate
    elif [[ -e $f/neighbor-$from ]]; then echo hairpin
    else cat "$f/route-$from" 2>/dev/null || echo raw
    fi
}

answer_probe() { # from-ip
    local from=$1 spec="$STUB_DIR/spec" scenario text="" name
    [[ -e $f/unfinished-$from ]] && { echo '{}'; return; }
    scenario=$(scenario_of "$from" "$spec")
    while IFS=$'\t' read -r name _; do
        [[ -n $name ]] || continue
        if grep -qw -- "$name" "$f/allow-$scenario" 2>/dev/null; then text+="REACH $name yes\\r\\n"; else text+="REACH $name no\\r\\n"; fi
    done <"$spec"
    guest_json "${text}DONE\\r\\n"
}

case "$args" in
    *"printenv CAPE_API_TOKEN"*) echo test-token ;;
    *"printenv GUEST_SUBNET"*) ;;
    *"machines/list"*) cat "$f/machines" ;;
    *"cat /sys/class/net/tt-guest/address"*) echo 52:54:00:5a:01:53 ;;
    *"getent ahostsv4 cape-internal"*) echo "172.19.0.2 STREAM cape-internal" ;;
    *"getent ahostsv4 cape-control"*) echo "172.18.0.2 STREAM cape-control" ;;
    *"network inspect"*) echo 172.19.0.1 ;;
    *"inspect -f"*)
        network=${args#*Networks \"}; network=${network%%\"*}
        container=${args##* }
        cat "$f/addr-$container-$network" 2>/dev/null ;;
    *"domstate "*) guest=${args##*domstate }; [[ -e $f/running-$guest ]] && echo running || echo "shut off" ;;
    *"snapshot-revert lab1 "*) [[ -e $f/revert-fails ]] && exit 1; exit 0 ;;
    *"snapshot-revert"*) exit 0 ;;
    *"-w %{http_code}"*) cat "$f/agent-code" ;;
    *"/store"*) exit 0 ;;
    *"/dev/tcp/"*)
        target=${args#*head -c 4096 }; target=${target%% *}
        [[ -e $f/no-control-$target ]] && exit 1
        echo "Server: gunicorn unauthorized uvicorn SCRAM cluster_name tartarus-canary INetSim HTTP/1.1 301 CAPE Agent 4.args" ;;
    *"python - enable "*|*"python - disable "*)
        words=${args#*python - }; read -r action route ip <<<"$words"
        if [[ $action == enable ]]; then echo "$route" >"$f/route-$ip"; else rm -f "$f/route-$ip"; fi ;;
    *"/execute"*)
        from=${args##*http://}; from=${from%%:*}
        case "$args" in
            *Get-NetAdapter*) guest_json 'Ethernet\r\n' ;;
            *"netsh interface ipv4 add neighbors"*) touch "$f/neighbor-$from"; guest_json "" ;;
            *"netsh interface ipv4 delete neighbors"*) rm -f "$f/neighbor-$from"; guest_json "" ;;
            *"netsh interface ipv4 "*) guest_json "" ;;
            *Get-NetIPAddress*) [[ -e $f/address-tentative ]] && guest_json 'Tentative\r\n' || guest_json 'Preferred\r\n' ;;
            *isolation-probe.ps1*) answer_probe "$from" ;;
            *) echo '{}' ;;
        esac ;;
    *" cp "*)
        source=${args#*cp }; source=${source%% *}
        case "$args" in *isolation-spec*) cp "$source" "$STUB_DIR/spec" ;; esac ;;
    *"destroy"* | *"up -d --wait"*) exit 0 ;;
    *) echo "unstubbed docker call: $args" >&2; exit 99 ;;
esac
STUB
    printf '#!/usr/bin/env bash\nexit 0\n' >"$STUB_DIR/bin/sleep"
    chmod +x "$STUB_DIR"/bin/*
}

healthy_fixtures() {
    fixture machines "{\"error\": false, \"data\": [{\"name\": \"lab1\", \"label\": \"lab1\", \"ip\": \"$A_IP\"}, {\"name\": \"lab5\", \"label\": \"lab5\", \"ip\": \"$B_IP\"}]}"
    fixture agent-code 200
    fixture allow-raw "$GATEWAY_ONLY"
    fixture allow-none "gateway-resultserver"
    fixture allow-inetsim "$GATEWAY_ONLY"
    fixture allow-internet "$GATEWAY_ONLY internet"
    fixture allow-alternate "$GATEWAY_ONLY"
    fixture allow-impersonating "other-guest-agent other-guest-ping"
    fixture allow-hairpin ""
    fixture addr-tartarus-backend-tartarus-internal 172.19.0.3
    fixture addr-tartarus-postgres-tartarus-cape-db 172.20.0.2
    fixture addr-tartarus-opensearch-tartarus-search 172.22.0.2
}

new_sandbox() {
    STUB_DIR="$(mktemp -d -p "$WORK_DIR")"
    export STUB_DIR A_IP B_IP
    mkdir "$STUB_DIR/bin" "$STUB_DIR/f"
    install_stubs
    healthy_fixtures
}

run_verify() {
    OUTPUT="$(PATH="$STUB_DIR/bin:$PATH" ISOLATION_AGENT_TIMEOUT=1 ISOLATION_LAN_ADDRESS=127.0.0.1 ISOLATION_CANARY_PORT=18913 \
        CAPE_API_TOKEN=test-token bash "$VERIFY" "$@" 2>&1 </dev/null)"
    STATUS=$?
}

dump() { echo "$OUTPUT" | sed 's/^/    /'; }

expect_status() {
    [[ $STATUS -eq $1 ]] || { echo "  expected status $1, got $STATUS"; dump; return 1; }
}

expect_line() {
    [[ $OUTPUT == *"$1"* ]] || { echo "  expected a line containing '$1'"; dump; return 1; }
}

expect_no_failure() {
    [[ $OUTPUT != *"[FAIL]"* ]] || { echo "  unexpected failure"; dump; return 1; }
}

calls_matching() { grep -c -- "$1" "$STUB_DIR/calls"; }

run_test() {
    local name=$1
    new_sandbox
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

# --- the routes ---------------------------------------------------------------------------------

test_passes_when_each_route_lets_through_only_what_it_should() {
    run_verify lab1 lab5
    expect_status 0 && expect_no_failure || return 1
    local route guest
    for guest in lab1 lab5; do
        for route in raw none inetsim internet; do
            expect_line "[ OK ] $guest on route $route: every probe answers as expected" || return 1
        done
    done
}

test_fails_when_a_guest_on_the_internet_route_reaches_the_cape_web_interface() {
    fixture allow-internet "$GATEWAY_ONLY internet cape-web"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 on route internet: every probe answers as expected (cape-web -> yes, expected no"
}

test_fails_when_a_guest_reaches_the_compose_networks_or_the_lan() {
    fixture allow-internet "$GATEWAY_ONLY internet backend docker-host lan-host"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "backend -> yes, expected no" &&
        expect_line "docker-host -> yes, expected no" &&
        expect_line "lan-host -> yes, expected no"
}

test_fails_when_guacd_or_the_control_service_answers_a_guest_with_no_route() {
    fixture allow-raw "$GATEWAY_ONLY guacd guest-control"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab1 on route raw: every probe answers as expected (guacd -> yes, expected no; guest-control -> yes, expected no"
}

test_fails_when_a_guest_loses_the_gateway_on_the_inetsim_route() {
    fixture allow-inetsim "gateway-dns gateway-resultserver"
    run_verify lab1 lab5
    expect_status 1 && expect_line "gateway-http -> no, expected yes"
}

test_fails_when_the_internet_route_no_longer_reaches_the_internet() {
    fixture allow-internet "$GATEWAY_ONLY"
    run_verify lab1 lab5
    expect_status 1 && expect_line "internet -> no, expected yes"
}

test_the_none_route_leaves_a_guest_only_the_resultserver() {
    fixture allow-none "gateway-resultserver gateway-http"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 on route none: every probe answers as expected (gateway-http -> yes, expected no"
}

# --- tricks a hostile guest has ------------------------------------------------------------------

test_a_guest_with_an_address_it_invented_reaches_only_the_gateway() {
    run_verify lab1 lab5
    expect_status 0 && expect_line "[ OK ] lab1 from an address of its own invention: every probe answers as expected"
}

test_fails_when_an_invented_address_reaches_the_control_service() {
    fixture allow-alternate "$GATEWAY_ONLY guest-control"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab1 from an address of its own invention: every probe answers as expected (guest-control -> yes, expected no"
}

test_fails_when_a_guest_can_speak_with_the_address_of_the_other() {
    fixture allow-impersonating "other-guest-agent other-guest-ping gateway-http"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab1 claiming the address of lab5: every probe answers as expected (gateway-http -> yes, expected no"
}

test_fails_when_a_guest_reaches_the_other_through_the_gateway() {
    fixture allow-hairpin "other-guest-agent"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab1 to lab5 through the gateway on route internet: every probe answers as expected (other-guest-agent -> yes, expected no"
}

test_the_hairpin_is_tried_in_both_directions_and_on_a_guest_with_no_route() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local pair route
    for pair in "lab1 to lab5" "lab5 to lab1"; do
        for route in raw internet; do
            expect_line "[ OK ] $pair through the gateway on route $route: every probe answers as expected" || return 1
        done
    done
}

test_the_gateways_mac_is_what_the_guests_are_told_for_each_other() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    grep -q "netsh interface ipv4 add neighbors Ethernet $B_IP 52-54-00-5a-01-53" "$STUB_DIR/calls" &&
        grep -q "netsh interface ipv4 add neighbors Ethernet $A_IP 52-54-00-5a-01-53" "$STUB_DIR/calls" || {
        echo "  neighbour entries for the gateway MAC were not set on both guests"
        return 1
    }
}

test_an_address_is_not_used_before_windows_has_finished_checking_it() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local added used
    added=$(grep -n "add address" "$STUB_DIR/calls" | head -n1 | cut -d: -f1)
    used=$(grep -n "Get-NetIPAddress" "$STUB_DIR/calls" | head -n1 | cut -d: -f1)
    [[ -n $added && -n $used && $used -gt $added ]] || { echo "  the address was not checked after it was added"; return 1; }
}

test_an_address_that_never_becomes_usable_fails_instead_of_passing_for_blocked() {
    : >"$STUB_DIR/f/address-tentative"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] 192.168.150.250 on 192.168.150.11 is still not usable"
}

# --- a probe that cannot be believed -------------------------------------------------------------

test_a_probe_that_never_ran_is_not_taken_for_a_blocked_one() {
    : >"$STUB_DIR/f/unfinished-$A_IP"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 on route raw: every probe answers as expected (the probe did not finish"
}

test_a_target_the_cape_container_cannot_reach_either_is_not_counted_as_blocked() {
    : >"$STUB_DIR/f/no-control-172.22.0.2"
    run_verify lab1 lab5
    expect_status 0 && expect_line "[INFO] opensearch does not answer from the cape container either: not probed from the guests"
}

test_without_the_internet_the_internet_route_is_not_asked_to_reach_it() {
    : >"$STUB_DIR/f/no-control-1.1.1.1"
    fixture allow-internet "$GATEWAY_ONLY"
    run_verify lab1 lab5
    expect_status 0 && expect_line "[INFO] internet does not answer from the cape container either"
}

# --- setup, teardown ------------------------------------------------------------------------------

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

test_every_route_neighbour_and_address_it_sets_up_is_taken_down_again() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local kind
    for kind in "python - %s" "netsh interface ipv4 %s neighbors" "netsh interface ipv4 %s address"; do
        local opened closed
        opened=$(calls_matching "$(printf "$kind" add)\|$(printf "$kind" enable)")
        closed=$(calls_matching "$(printf "$kind" delete)\|$(printf "$kind" disable)")
        [[ $opened -gt 0 && $opened -eq $closed ]] || { echo "  '$kind': $opened set up, $closed taken down"; return 1; }
    done
    [[ ! -e $STUB_DIR/f/route-$A_IP && ! -e $STUB_DIR/f/route-$B_IP ]] || { echo "  a route was left open"; return 1; }
}

test_the_rules_are_taken_down_when_a_check_fails() {
    fixture allow-internet "$GATEWAY_ONLY internet cape-web"
    run_verify lab1 lab5
    expect_status 1 || return 1
    [[ ! -e $STUB_DIR/f/route-$A_IP && ! -e $STUB_DIR/f/route-$B_IP && ! -e $STUB_DIR/f/neighbor-$A_IP ]] ||
        { echo "  something was left set up on a guest"; return 1; }
}

test_usage_error_needs_two_different_guests() {
    run_verify lab1 lab1
    expect_status 2
}

for name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do run_test "$name"; done
exit "$failures"
