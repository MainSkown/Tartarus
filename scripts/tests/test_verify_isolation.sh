#!/usr/bin/env bash
# Tests scripts/verify-isolation.sh with `docker` and `sleep` replaced by stubs on PATH. The docker stub
# stands in for the whole stack: it knows which route and which tricks (an invented address, another guest's
# address, a neighbour entry pointing at the gateway) the script has set up on a guest, and answers that
# guest's probe from a list of the probes it lets through, so the verdicts are exercised without libvirt.
# fixture allow-<scenario> holds the names a guest reaches in that scenario; anything else answers `no`.
# The fake LAN is modelled the same way: a guest holding a session (the stub records `open` and `close`) reaches
# the hosts and ports of its preset (fixture `presets`) and nothing else; extra-<ip> and deny-<ip> add or take
# away names for one guest, and deleting the two tartarus_guest tables opens everything.
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

guest_ip_of() { case $1 in lab1) echo "$A_IP" ;; lab5) echo "$B_IP" ;; esac; }

# What a correct firewall lets a guest holding a session for `preset` reach: the services of its hosts, and
# ping and ARP for them; never a port the preset does not list.
fake_name_allowed() { # name preset
    local name=$1 preset=$2 octet what
    IFS=- read -r _ octet what _ <<<"$name"
    case $what in
        closed) return 1 ;;
        ping | ttl | arp) grep -q "^$preset;192.168.150.$octet;" "$f/presets" ;;
        *) grep -q "^$preset;192.168.150.$octet;$what;" "$f/presets" ;;
    esac
}

is_route() { [[ $1 == raw || $1 == none || $1 == inetsim || $1 == internet ]]; }

file_words() { [[ -r $1 ]] && echo "$(<"$1")" || true; }

# The words of the files are read once per probe run, not once per name.
load_run_state() { # from scenario
    DENIED=" $(file_words "$f/deny-$1" | tr '\n' ' ') "
    EXTRA=" $(file_words "$f/extra-$1" | tr '\n' ' ') "
    ALLOWED=" $(file_words "$f/allow-$2" | tr '\n' ' ') "
    SESSION_PRESET=$(file_words "$f/session-$1")
    [[ -e $f/tables-deleted ]] && TABLES_GONE=yes || TABLES_GONE=""
}

reaches() { # scenario name
    local scenario=$1 name=$2
    [[ -n $TABLES_GONE ]] && return 0
    [[ $DENIED == *" $name "* ]] && return 1
    [[ $EXTRA == *" $name "* || $ALLOWED == *" $name "* ]] && return 0
    [[ -n $SESSION_PRESET && $name == lan-* ]] && is_route "$scenario" && fake_name_allowed "$name" "$SESSION_PRESET"
}

scenario_of() { # from-ip spec-file
    local from=$1 spec=$2 source
    source=$(awk -F'\t' '$6 != "" {print $6; exit}' "$spec")
    if [[ -n $source ]]; then
        if [[ $source == "$A_IP" || $source == "$B_IP" ]]; then echo impersonating
        elif grep -q ";$source;" "$f/presets"; then echo fakeown
        else echo alternate; fi
    elif [[ -e $f/neighbor-$from ]]; then echo hairpin
    elif [[ $(cat "$f/route-$from" 2>/dev/null) == internet && ,$(cat "$f/blocked" 2>/dev/null), == *,1.1.1.1,* ]]; then echo blocked
    else cat "$f/route-$from" 2>/dev/null || echo raw
    fi
}

answer_probe() { # from-ip
    local from=$1 spec="$STUB_DIR/spec" scenario text="" name
    [[ -e $f/unfinished-$from ]] && { echo '{}'; return; }
    scenario=$(scenario_of "$from" "$spec")
    load_run_state "$from" "$scenario"
    while IFS=$'\t' read -r name _; do
        [[ -n $name ]] || continue
        if reaches "$scenario" "$name"; then text+="REACH $name yes\\r\\n"; else text+="REACH $name no\\r\\n"; fi
    done <"$spec"
    guest_json "${text}DONE\\r\\n"
}

case "$args" in
    *"printenv CAPE_API_TOKEN"*) echo test-token ;;
    *"printenv GUEST_CONTROL_TOKEN"*) echo test-control-token ;;
    *"printenv GUEST_SUBNET"*) ;;
    *"tartarus-backend:latest python - "*)
        words=${args#*python - }; read -r verb key guest preset <<<"$words"
        case $verb in
            health) cat "$f/lan-health" 2>/dev/null || echo ready ;;
            presets) cat "$f/presets" ;;
            list) for held in "$f"/session-key-*; do [[ -e $held ]] && { held=${held##*/session-key-}; echo "$held"; }; done; exit 0 ;;
            open)
                [[ -e $f/lan-open-refuses ]] && { echo "the fake hosts cannot start" >&2; exit 1; }
                ip=$(guest_ip_of "$guest")
                echo "$preset" >"$f/session-$ip"; echo "$ip" >"$f/session-key-$key"
                rm -f "$f/tables-deleted"; echo "opened $key" ;;
            close)
                read -r ip <"$f/session-key-$key" 2>/dev/null
                if [[ -e $f/leak-on-close ]]; then echo residue >"$f/state-residue"; else rm -f "$f/session-$ip"; fi
                rm -f "$f/session-key-$key"; echo "closed $key" ;;
        esac ;;
    *"nft list table inet tartarus_guest"*)
        cat "$f/cape-state"
        [[ -e $f/tables-deleted ]] && echo "(the tables are missing)"
        compgen -G "$f/session-key-*" >/dev/null && echo "iptables -A OUTPUT tartarus-lan"
        cat "$f/state-residue" 2>/dev/null; exit 0 ;;
    *"nft delete table "*) : >"$f/tables-deleted"; exit 0 ;;
    *"printenv GUEST_BLOCKED_ADDRESSES"*) cat "$f/configured-blocked" 2>/dev/null ;;
    *"guest-firewall init"*)
        [[ -e $f/firewall-refuses ]] && exit 1
        rm -f "$f/tables-deleted"
        if [[ $args == *"-e GUEST_BLOCKED_ADDRESSES="* ]]; then
            setting=${args#*-e GUEST_BLOCKED_ADDRESSES=}; echo "${setting%% *}" >"$f/blocked"
        else rm -f "$f/blocked"; fi ;;
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
    fixture allow-internet "$GATEWAY_ONLY internet internet-control"
    fixture allow-blocked "$GATEWAY_ONLY internet-control"
    fixture allow-alternate "$GATEWAY_ONLY"
    fixture allow-impersonating "other-guest-agent other-guest-ping"
    fixture allow-hairpin ""
    fixture presets "small-office;192.168.150.200;445;smb
small-office;192.168.150.201;22;ssh
flat-home;192.168.150.216;445;smb
flat-home;192.168.150.217;3389;rdp"
    fixture cape-state "table inet tartarus_guest { baseline }"
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
    expect_status 0 && expect_line "[INFO] opensearch does not answer outside a guest either: not probed from the guests"
}

test_a_target_outside_the_container_is_tried_from_beside_it_because_its_own_programs_have_no_route_out() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    grep -q 'run --rm -i --network tartarus-internal --network tartarus-cape-db .*/dev/tcp/.* 1\.1\.1\.1 80 ' "$STUB_DIR/calls" ||
        { echo "  the internet is not tried from a container beside cape"; return 1; }
    grep -q 'exec -T cape .*/dev/tcp/.* 4822 ' "$STUB_DIR/calls" ||
        { echo "  guacd, a listener of the container itself, is not tried from inside it"; return 1; }
}

test_without_the_internet_the_internet_route_is_not_asked_to_reach_it() {
    : >"$STUB_DIR/f/no-control-1.1.1.1"
    : >"$STUB_DIR/f/no-control-1.0.0.1"
    fixture allow-internet "$GATEWAY_ONLY"
    run_verify lab1 lab5
    expect_status 0 && expect_line "[INFO] internet does not answer outside a guest either"
}

# --- GUEST_BLOCKED_ADDRESSES ------------------------------------------------------------------------

BLOCKING_INIT='exec -T -e GUEST_BLOCKED_ADDRESSES=[^ ]* cape python3 -I /usr/local/lib/tartarus/guest-firewall init'
PLAIN_INIT='exec -T cape python3 -I /usr/local/lib/tartarus/guest-firewall init'

test_an_address_in_the_blocked_setting_is_refused_on_the_internet_route_and_its_neighbour_is_not() {
    run_verify lab1 lab5
    expect_status 0 && expect_no_failure &&
        expect_line "[ OK ] lab1 on route internet with 1.1.1.1 in GUEST_BLOCKED_ADDRESSES: every probe answers as expected (2 probes)"
}

test_fails_when_a_guest_still_reaches_the_blocked_address() {
    fixture allow-blocked "$GATEWAY_ONLY internet internet-control"
    run_verify lab1 lab5
    expect_status 1 && expect_line "in GUEST_BLOCKED_ADDRESSES: every probe answers as expected (internet -> yes, expected no"
}

test_fails_when_the_block_takes_more_than_the_address_it_names() {
    fixture allow-blocked "$GATEWAY_ONLY"
    run_verify lab1 lab5
    expect_status 1 && expect_line "internet-control -> no, expected yes"
}

test_the_test_address_is_added_to_what_the_setting_already_blocks() {
    fixture configured-blocked "203.0.113.7,198.51.100.0/24"
    run_verify lab1 lab5
    expect_status 0 || return 1
    grep -q -- '-e GUEST_BLOCKED_ADDRESSES=203.0.113.7,198.51.100.0/24,1.1.1.1 cape' "$STUB_DIR/calls" ||
        { echo "  the configured addresses were not kept"; grep init "$STUB_DIR/calls"; return 1; }
}

test_the_guests_are_down_while_the_firewall_is_applied_because_that_binds_no_port() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local blocking first_destroy
    blocking=$(grep -n -- "$BLOCKING_INIT" "$STUB_DIR/calls" | head -n1 | cut -d: -f1)
    first_destroy=$(grep -n -- "destroy lab5" "$STUB_DIR/calls" | head -n1 | cut -d: -f1)
    [[ -n $blocking && -n $first_destroy && $first_destroy -lt $blocking ]] ||
        { echo "  lab5 was not powered off before the firewall was applied"; return 1; }
    sed -n "$blocking,\$p" "$STUB_DIR/calls" | grep -q "snapshot-revert lab1 tartarus-clean" ||
        { echo "  lab1 was not started again after the firewall was applied"; return 1; }
}

test_the_firewall_is_applied_again_as_configured_when_the_probe_is_done() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    [[ $(calls_matching "$BLOCKING_INIT") -eq 1 && $(calls_matching "$PLAIN_INIT") -ge 1 && ! -e $STUB_DIR/f/blocked ]] ||
        { echo "  the test address was left blocked"; grep init "$STUB_DIR/calls"; return 1; }
}

test_the_firewall_is_applied_again_as_configured_when_the_blocked_probe_fails() {
    fixture allow-blocked "$GATEWAY_ONLY internet internet-control"
    run_verify lab1 lab5
    expect_status 1 || return 1
    [[ ! -e $STUB_DIR/f/blocked ]] || { echo "  the test address was left blocked"; return 1; }
}

test_fails_when_the_firewall_refuses_the_setting() {
    : >"$STUB_DIR/f/firewall-refuses"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] the guest firewall is applied with 1.1.1.1 in GUEST_BLOCKED_ADDRESSES"
}

test_without_the_internet_no_address_is_blocked() {
    : >"$STUB_DIR/f/no-control-1.1.1.1"
    : >"$STUB_DIR/f/no-control-1.0.0.1"
    fixture allow-internet "$GATEWAY_ONLY"
    run_verify lab1 lab5
    expect_status 0 && expect_line "[INFO] GUEST_BLOCKED_ADDRESSES is not probed: the internet does not answer here" &&
        [[ $(calls_matching "guest-firewall init") -eq 0 ]]
}

test_a_guest_that_was_running_before_is_not_cut_off_to_probe_the_blocked_setting() {
    : >"$STUB_DIR/f/running-lab5"
    run_verify lab1 lab5
    expect_status 0 && expect_line "[INFO] GUEST_BLOCKED_ADDRESSES is not probed: a guest was running before" &&
        [[ $(calls_matching "guest-firewall init") -eq 0 ]]
}

# --- the fake LAN -----------------------------------------------------------------------------------

LAN_OPEN='python - open isolation-[0-9a-z-]* lab1 small-office'

test_fails_when_a_fake_host_answers_a_guest_that_has_no_session() {
    fixture allow-raw "$GATEWAY_ONLY lan-200-445"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 on route raw: every probe answers as expected (lan-200-445 -> yes, expected no"
}

test_fails_when_a_fake_address_is_resolved_for_a_guest_that_has_no_session() {
    fixture allow-none "gateway-resultserver lan-216-arp"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 on route none: every probe answers as expected (lan-216-arp -> yes, expected no"
}

test_the_presets_the_control_service_lists_are_what_the_fake_probes_are_built_from() {
    fixture presets "small-office;192.168.150.200;445;smb
small-office;192.168.150.200;389;ldap"
    fixture allow-raw "$GATEWAY_ONLY lan-200-389 lan-200-389-answers"
    run_verify lab1 lab5
    expect_status 1 && expect_line "lan-200-389 -> yes, expected no; lan-200-389-answers -> yes, expected no"
}

test_a_guest_with_a_session_reaches_every_service_of_its_preset_on_the_routes_with_no_internet() {
    run_verify lab1 lab5
    expect_status 0 && expect_no_failure || return 1
    local route
    for route in raw none inetsim; do
        expect_line "[ OK ] lab1 with a small-office LAN session on route $route: every probe answers as expected" || return 1
    done
    expect_line "[INFO] the LAN section skips the internet route" || return 1
    [[ $OUTPUT != *"lab1 with a small-office LAN session on route internet"* ]] || { echo "  the internet route was tried with a session"; return 1; }
}

test_the_session_is_opened_with_a_key_for_the_guest_and_the_preset_through_the_control_service() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    [[ $(calls_matching "$LAN_OPEN") -ge 1 ]] || { echo "  no session was opened for lab1"; grep "python - open" "$STUB_DIR/calls"; return 1; }
    grep -q 'tartarus-backend:latest python - open isolation-[0-9a-z-]* lab5 flat-home' "$STUB_DIR/calls" ||
        { echo "  no session was opened for lab5"; return 1; }
    grep -q -- '-e GUEST_CONTROL_TOKEN ' "$STUB_DIR/calls" && ! grep -q 'test-control-token' "$STUB_DIR/calls" ||
        { echo "  the token must be passed by name, never on the command line"; return 1; }
}

test_a_guest_without_a_session_is_probed_beside_one_that_has_one() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local route
    for route in raw none inetsim; do
        expect_line "[ OK ] lab5 with no LAN session of its own on route $route: every probe answers as expected" || return 1
    done
}

test_fails_when_a_guest_with_a_session_loses_a_service_of_its_preset() {
    fixture deny-$A_IP "lan-200-445"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 with a small-office LAN session on route raw: every probe answers as expected (lan-200-445 -> no, expected yes"
}

test_fails_when_a_guest_with_a_session_loses_ping_with_the_ttl_of_a_windows_host() {
    fixture deny-$A_IP "lan-201-ttl"
    run_verify lab1 lab5
    expect_status 1 && expect_line "lan-201-ttl -> no, expected yes"
}

test_fails_when_a_session_lets_a_guest_reach_a_host_of_another_preset() {
    fixture extra-$A_IP "lan-216-445"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 with a small-office LAN session on route none: every probe answers as expected (lan-216-445 -> yes, expected no"
}

test_fails_when_a_session_lets_a_guest_answer_on_a_port_the_preset_does_not_list() {
    fixture extra-$A_IP "lan-200-closed lan-200-3389-answers"
    run_verify lab1 lab5
    expect_status 1 && expect_line "lan-200-closed -> yes, expected no"
}

test_fails_when_a_session_lets_a_guest_reach_anything_a_guest_must_never_reach() {
    fixture extra-$A_IP "cape-web backend postgres opensearch docker-host lan-host internet guest-control guacd other-guest-agent"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab1 with a small-office LAN session on route inetsim: every probe answers as expected (cape-web -> yes, expected no" &&
        expect_line "other-guest-agent -> yes, expected no"
}

test_fails_when_the_guest_without_a_session_reaches_the_fake_hosts_of_the_other() {
    fixture extra-$B_IP "lan-200-445"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab5 with no LAN session of its own on route raw: every probe answers as expected (lan-200-445 -> yes, expected no"
}

test_two_guests_with_sessions_for_different_presets_reach_exactly_their_own_hosts() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local route
    for route in raw none inetsim; do
        expect_line "[ OK ] lab1 with a small-office session beside a guest with a flat-home session on route $route: every probe answers as expected" &&
            expect_line "[ OK ] lab5 with a flat-home session beside a guest with a small-office session on route $route: every probe answers as expected" || return 1
    done
}

test_fails_when_a_guest_reaches_the_hosts_of_the_preset_of_the_other_one() {
    fixture extra-$B_IP "lan-200-445"
    run_verify lab1 lab5
    expect_status 1 &&
        expect_line "[FAIL] lab5 with a flat-home session beside a guest with a small-office session on route raw: every probe answers as expected (lan-200-445 -> yes, expected no"
}

test_the_tricks_are_repeated_with_a_session_open() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    expect_line "[ OK ] lab1 with a small-office LAN session from an address of its own invention: every probe answers as expected" &&
        expect_line "[ OK ] lab1 with a small-office LAN session claiming the address of lab5: every probe answers as expected" &&
        expect_line "[ OK ] lab1 with a small-office LAN session to lab5 through the gateway on route raw: every probe answers as expected" &&
        expect_line "[ OK ] lab5 with a flat-home LAN session to lab1 through the gateway on route internet: every probe answers as expected"
}

test_fails_when_a_session_lets_an_invented_address_reach_a_fake_host() {
    fixture extra-$A_IP "lan-200-445"
    fixture allow-alternate "$GATEWAY_ONLY lan-200-445"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 with a small-office LAN session from an address of its own invention: every probe answers as expected (lan-200-445 -> yes, expected no"
}

test_a_guest_that_takes_a_fake_address_as_its_own_sends_nothing_from_it() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    expect_line "[ OK ] lab1 with a small-office LAN session taking the fake address 192.168.150.200 as its own: every probe answers as expected" &&
        expect_line "[ OK ] lab1 with a small-office LAN session taking the fake address 192.168.150.216 as its own: every probe answers as expected" || return 1
    grep -q 'netsh interface ipv4 set interface name=Ethernet dadtransmits=0' "$STUB_DIR/calls" &&
        grep -q 'netsh interface ipv4 set interface name=Ethernet dadtransmits=3' "$STUB_DIR/calls" ||
        { echo "  duplicate address detection was not switched off and on again"; return 1; }
}

test_fails_when_a_fake_address_taken_as_its_own_still_reaches_the_gateway() {
    fixture allow-fakeown "gateway-http"
    run_verify lab1 lab5
    expect_status 1 && expect_line "taking the fake address 192.168.150.200 as its own: every probe answers as expected (gateway-http -> yes, expected no"
}

test_the_guest_answering_for_the_fake_address_it_took_is_not_a_leak() {
    fixture allow-fakeown "lan-200-445 lan-200-445-answers lan-200-closed lan-200-ping lan-200-ttl"
    run_verify lab1 lab5
    expect_line "[ OK ] lab1 with a small-office LAN session taking the fake address 192.168.150.200 as its own: every probe answers as expected" &&
        expect_line "[FAIL] lab1 with a small-office LAN session taking the fake address 192.168.150.216 as its own: every probe answers as expected (lan-200-445 -> yes"
}

test_fails_when_a_fake_address_taken_as_its_own_reaches_another_fake_host() {
    fixture allow-fakeown "lan-201-22"
    run_verify lab1 lab5
    expect_status 1 && expect_line "taking the fake address 192.168.150.200 as its own: every probe answers as expected (lan-201-22 -> yes, expected no"
}

test_every_session_is_closed_when_the_section_is_over() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    compgen -G "$STUB_DIR/f/session-*" >/dev/null && { echo "  a session was left open"; return 1; }
    [[ $(calls_matching 'python - open') -eq $(calls_matching 'python - close') ]] || { echo "  opened and closed differ"; return 1; }
}

test_every_session_is_closed_when_a_check_fails() {
    fixture extra-$A_IP "cape-web"
    run_verify lab1 lab5
    expect_status 1 || return 1
    compgen -G "$STUB_DIR/f/session-*" >/dev/null && { echo "  a session was left open"; return 1; }
    return 0
}

test_the_probes_are_back_to_the_no_session_result_when_the_sessions_are_closed() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    local route
    for route in raw none inetsim; do
        expect_line "[ OK ] lab1 after its LAN session closed on route $route: every probe answers as expected" &&
            expect_line "[ OK ] lab5 after its LAN session closed on route $route: every probe answers as expected" || return 1
    done
}

test_fails_when_a_closed_session_still_lets_the_guest_reach_its_fake_hosts() {
    : >"$STUB_DIR/f/leak-on-close"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] lab1 after its LAN session closed on route raw: every probe answers as expected (lan-200-445 -> yes, expected no"
}

test_the_firewall_state_in_the_cape_container_is_compared_with_the_one_before_the_first_session() {
    run_verify lab1 lab5
    expect_status 0 && expect_line "[ OK ] the firewall state of the cape container after the sessions closed is the one from before the first"
}

test_fails_when_closing_the_sessions_leaves_something_in_the_firewall() {
    : >"$STUB_DIR/f/leak-on-close"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] the firewall state of the cape container after the sessions closed is the one from before the first"
}

test_the_state_that_is_compared_has_no_packet_counters() {
    run_verify lab1 lab5
    expect_status 0 || return 1
    grep -q "sed.*counter packets" "$STUB_DIR/calls" || { echo "  counters would make every comparison fail"; return 1; }
}

test_fails_when_the_control_service_refuses_a_session() {
    : >"$STUB_DIR/f/lan-open-refuses"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] a LAN session for lab1 (small-office) is opened through the control service (the fake hosts cannot start)"
}

test_fails_when_the_fake_lan_is_not_ready() {
    fixture lan-health "the fake-host daemon is not running"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] setup: the fake LAN is not ready (the fake-host daemon is not running)"
}

test_fails_when_a_session_was_left_open_before_the_run() {
    echo x >"$STUB_DIR/f/session-key-isolation-old"
    run_verify lab1 lab5
    expect_status 1 && expect_line "[FAIL] setup: a LAN session is open already (isolation-old)"
}

test_the_tables_are_not_touched_unless_the_negative_proof_is_asked_for() {
    run_verify lab1 lab5
    expect_status 0 && [[ $(calls_matching "nft delete table") -eq 0 ]]
}

test_the_negative_proof_deletes_both_tables_after_a_session_opens_and_the_run_fails() {
    ISOLATION_NEGATIVE_PROOF=1 run_verify lab1 lab5
    expect_status 1 || return 1
    grep -q 'exec -T cape nft delete table inet tartarus_guest' "$STUB_DIR/calls" &&
        grep -q 'exec -T cape nft delete table bridge tartarus_guest' "$STUB_DIR/calls" || { echo "  the tables were not deleted"; return 1; }
    expect_line "[INFO] negative proof" &&
        expect_line "[FAIL] lab1 with a small-office LAN session on route raw: every probe answers as expected (" &&
        expect_line "lan-200-445 -> yes, expected no" || return 1
    [[ ! -e $STUB_DIR/f/tables-deleted ]] || { echo "  the tables were not restored"; return 1; }
}

test_the_negative_proof_deletes_the_tables_again_after_the_next_session_restored_them() {
    ISOLATION_NEGATIVE_PROOF=1 run_verify lab1 lab5
    expect_status 1 || return 1
    [[ $(calls_matching "nft delete table inet tartarus_guest") -ge 2 ]] || { echo "  only one session was broken"; return 1; }
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
