#!/usr/bin/env bash
# Proves that a guest on the shared tt-guest bridge reaches nothing but what its route allows, whatever
# it does about it: M9 task 3.0 (two guests cannot reach each other) and the M11 isolation review.
#
#   scripts/verify-isolation.sh GUEST_A GUEST_B
#
# Needs the stack up (make up) and two ready guests (their labels as `make` shows them). Each guest that
# is not running is started by reverting its tartarus-clean snapshot, which also proves that a revert
# binds the new port in the bridge firewall; the guests this script started are powered off again at the
# end. Stop any analysis first: the guests are driven through their agents, not through CAPE.
#
# Every guest is probed from inside, through its agent, on each of four routes: `raw` (no rooter rule,
# as between a revert and the route, during a build or a self-test), `none`, `inetsim` and `internet`.
# The rooter rules of a route are opened with scripts/lib/rooter-route.py, the commands CAPE itself
# sends for a task. A probe connects, sends what the target's protocol needs and demands a marker only
# the real service answers with, because INetSim accepts a connection to any address. Targets:
# the gateway services, the CAPE web interface, guacd and the control service on the cape container's own
# addresses, the backend, Postgres and OpenSearch, a canary on the docker host and on its LAN address, the
# internet, and the other guest. A probe whose target does not answer from the cape container either
# proves nothing and is skipped with an [INFO] line.
#
# Then the tricks a hostile guest has: sending from an address it invented (the rooter's rules are keyed
# on the registered one), from the other guest's address, and to the other guest through the gateway
# (a neighbour entry for the gateway's MAC on both guests, so that routing, not the bridge, carries it).
# Exit 0 when all hold, 1 otherwise, 2 on bad usage.
#
# The negative proof, that the check can fail: while the guests run,
#   docker compose exec -T cape nft delete table inet tartarus_guest
#   docker compose exec -T cape nft delete table bridge tartarus_guest
# and run the script again: it must exit 1 naming what the guests now reach. Restart cape (or run
# `docker compose exec -T cape python3 -I /usr/local/lib/tartarus/guest-firewall init`) to restore them.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO=$PWD

CAPE_IMAGE=tartarus-cape:latest
PROBE_SCRIPT=$REPO/scripts/lib/isolation-probe.ps1
ROUTE_SCRIPT=$REPO/scripts/lib/rooter-route.py
AGENT_TIMEOUT=${ISOLATION_AGENT_TIMEOUT:-300}
PROBE_TIMEOUT=${ISOLATION_PROBE_TIMEOUT:-90}
ADDRESS_TIMEOUT=30
CANARY_PORT=${ISOLATION_CANARY_PORT:-18913}
CANARY_TEXT=tartarus-canary
ROUTES=(raw none inetsim internet)
INVENTED_HOST=250
INTERNET_ADDRESS=1.1.1.1
GUEST_NETMASK=255.255.255.0

failed=0
ok()   { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }
info() { printf '[INFO] %s\n' "$1"; }

check() {
    local description=$1 detail
    shift
    if detail=$("$@" 2>&1); then ok "$description${detail:+ ($detail)}"
    else detail=${detail//$'\n'/; }; fail "$description${detail:+ ($detail)}"; return 1; fi
}

compose() { docker compose "$@"; }
# stdin from /dev/null: `compose exec -T` would otherwise read the input of the loop that calls it.
in_cape() { compose exec -T cape "$@" </dev/null; }
virsh_cape() { in_cape virsh -c qemu:///system "$@"; }
on_internal() { docker run --rm -i -e CAPE_API_TOKEN --network tartarus-internal --entrypoint "" "$CAPE_IMAGE" "$@"; }

STARTED=()
OPEN_ROUTES=()
ADDED_ADDRESSES=()
ADDED_NEIGHBORS=()
CANARY_PID=""
CANARY_DIR=""

cleanup() {
    local entry
    for entry in "${OPEN_ROUTES[@]}"; do close_route ${entry}; done
    for entry in "${ADDED_NEIGHBORS[@]}"; do remove_neighbor ${entry}; done
    for entry in "${ADDED_ADDRESSES[@]}"; do remove_address ${entry}; done
    [[ -z $CANARY_PID ]] || kill "$CANARY_PID" 2>/dev/null
    [[ -z $CANARY_DIR ]] || rm -rf "$CANARY_DIR"
    for entry in "${STARTED[@]}"; do virsh_cape destroy "$entry" >/dev/null 2>&1; done
}

# --- what the stack looks like ----------------------------------------------------------------------

discover_gateway() {
    local subnet
    subnet=$(in_cape printenv GUEST_SUBNET 2>/dev/null)
    subnet=${subnet:-192.168.150.0/24}
    GATEWAY_IP=${subnet%.0/24}.1
    INVENTED_IP=${subnet%.0/24}.$INVENTED_HOST
    GATEWAY_MAC=$(in_cape cat /sys/class/net/tt-guest/address 2>/dev/null | tr -d '\r' | tr ':' '-')
}

container_address() { # service network
    docker inspect -f "{{(index .NetworkSettings.Networks \"$2\").IPAddress}}" "tartarus-$1" 2>/dev/null
}

own_address() { in_cape getent ahostsv4 "$1" 2>/dev/null | awk 'NR == 1 {print $1}'; }

lan_address() { ip -4 route get "$INTERNET_ADDRESS" 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}'; }

discover_targets() {
    CAPE_INTERNAL_IP=$(own_address cape-internal)
    CAPE_CONTROL_IP=$(own_address cape-control)
    BACKEND_IP=$(container_address backend tartarus-internal)
    POSTGRES_IP=$(container_address postgres tartarus-cape-db)
    OPENSEARCH_IP=$(container_address opensearch tartarus-search)
    DOCKER_HOST_IP=$(docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' tartarus-internal 2>/dev/null)
    LAN_IP=${ISOLATION_LAN_ADDRESS:-$(lan_address)}
}

# The host answers on 0.0.0.0 for as long as this script runs, with one file in an otherwise empty directory.
start_host_canary() {
    CANARY_DIR=$(mktemp -d)
    printf '%s\n' "$CANARY_TEXT" >"$CANARY_DIR/index.html"
    python3 -I -m http.server "$CANARY_PORT" --bind 0.0.0.0 --directory "$CANARY_DIR" >/dev/null 2>&1 &
    CANARY_PID=$!
}

# --- the probes -------------------------------------------------------------------------------------

payload_for() {
    case $1 in
        get) printf 'GET / HTTP/1.0\r\nHost: probe\r\n\r\n' | base64 -w0 ;;
        postgres) printf '\x00\x00\x00\x23\x00\x03\x00\x00user\x00probe\x00database\x00probe\x00\x00' | base64 -w0 ;;
        guacd) printf '6.select,3.vnc;' | base64 -w0 ;;
    esac
}

# name;target;port;payload kind;marker (extended regex);scenarios in which the target is reachable
# A scenario is a route (raw none inetsim internet), `invented` (a guest sending from an address of its own
# invention) or `claimed` (a guest that took the other guest's address, which is then its own: it reaches
# itself). The gateway services are the only thing a guest reaches whatever it does: they run on the
# address it is given, and INetSim's DNS and HTTP are what the inetsim route is for.
catalogue() { # other-guest-address
    cat <<EOF
gateway-dns;$GATEWAY_IP;53;;;raw inetsim internet invented
gateway-http;$GATEWAY_IP;80;get;INetSim;raw inetsim internet invented
gateway-resultserver;$GATEWAY_IP;2042;;;raw none inetsim internet invented
cape-web;$CAPE_INTERNAL_IP;8000;get;X-Cuckoo-Version;
guacd;$CAPE_INTERNAL_IP;4822;guacd;4\.args;
guest-control;$CAPE_CONTROL_IP;8002;get;unauthorized;
backend;$BACKEND_IP;8000;get;uvicorn;
postgres;$POSTGRES_IP;5432;postgres;SCRAM|FATAL;
opensearch;$OPENSEARCH_IP;9200;get;cluster_name;
docker-host;$DOCKER_HOST_IP;$CANARY_PORT;get;$CANARY_TEXT;
lan-host;$LAN_IP;$CANARY_PORT;get;$CANARY_TEXT;
internet;$INTERNET_ADDRESS;80;get;HTTP/1\.[01] (301|400|403);internet
other-guest-agent;$1;8000;get;CAPE Agent;claimed
other-guest-ping;$1;icmp;;;claimed
EOF
}

SKIPPED=" "
is_skipped() { [[ $SKIPPED == *" $1 "* ]]; }

answers_from_cape() { # target port payload-kind marker
    in_cape bash -c 'exec 3<>"/dev/tcp/$0/$1" || exit 1; printf %s "$2" | base64 -d >&3; timeout 3 cat <&3 | head -c 4096' \
        "$1" "$2" "$(payload_for "$3")" 2>/dev/null | grep -Eaq -- "$4"
}

# A target that the cape container cannot reach either would also look blocked to a guest for a reason
# that has nothing to do with isolation.
skip_what_nothing_reaches() {
    local name target port payload marker _
    while IFS=';' read -r name target port payload marker _; do
        case $name in gateway-* | other-guest-*) continue ;; esac
        if [[ -z $target ]]; then info "$name has no address here: not probed"; SKIPPED+="$name "
        elif ! answers_from_cape "$target" "$port" "$payload" "$marker"; then
            info "$name does not answer from the cape container either: not probed from the guests"
            SKIPPED+="$name "
        fi
    done < <(catalogue "")
}

probe_spec() { # other-guest-address source names...
    local other=$1 source=$2 name target port payload marker _
    shift 2
    while IFS=';' read -r name target port payload marker _; do
        [[ -n $target ]] && ! is_skipped "$name" || continue
        (($# == 0)) || [[ " $* " == *" $name "* ]] || continue
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$target" "$port" "$(payload_for "$payload")" "$marker" "$source"
    done < <(catalogue "$other")
}

# --- guests -----------------------------------------------------------------------------------------

guest_address() { # label
    on_internal sh -c 'curl -s -m10 -H "Authorization: Token $CAPE_API_TOKEN" http://cape:8000/apiv2/machines/list/' |
        python3 -I -c 'import json,sys
label = sys.argv[1]
for machine in json.load(sys.stdin).get("data", []):
    if label in (machine.get("label"), machine.get("name")):
        print(machine.get("ip", ""))
        break' "$1"
}

is_running() { virsh_cape domstate "$1" 2>/dev/null | grep -q '^running'; }

agent_answers() { # ip
    [[ $(in_cape curl -s -o /dev/null -w '%{http_code}' -m 5 "http://$1:8000/" 2>/dev/null) == 200 ]]
}

start_guest() { # label ip
    if ! is_running "$1"; then
        virsh_cape snapshot-revert "$1" tartarus-clean >/dev/null 2>&1 || { echo "snapshot-revert of $1 failed"; return 1; }
    fi
    local deadline=$((SECONDS + AGENT_TIMEOUT))
    until agent_answers "$2"; do
        ((SECONDS < deadline)) || { echo "the agent of $1 did not answer at $2:8000"; return 1; }
        sleep 5
    done
}

store_on_guest() { # ip local-file guest-path
    in_cape curl -s -m 20 -F filepath="$3" -F file=@"$2" "http://$1:8000/store" >/dev/null
}

store_probe_on() { # ip...
    local ip
    compose cp "$PROBE_SCRIPT" cape:/tmp/isolation-probe.ps1 >/dev/null 2>&1 || return 1
    for ip in "$@"; do store_on_guest "$ip" /tmp/isolation-probe.ps1 'C:\tartarus\isolation-probe.ps1' || return 1; done
}

# What the guest at `ip` printed for `command`, run through its agent.
guest_output() { # ip command
    # The agent shlex-splits the command POSIX-style, which would eat backslashes in a Windows path.
    in_cape curl -s -m "$PROBE_TIMEOUT" -F "command=$2" "http://$1:8000/execute" |
        python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("stdout") or "")
except ValueError: pass' | tr -d '\r'
}

adapter_of() { # ip
    guest_output "$1" 'powershell.exe -NoProfile -Command "(Get-NetAdapter | Where-Object Status -eq Up | Select-Object -First 1).Name"' |
        head -n1
}

# Runs the probes from the guest at `from`: from `source` (empty: its own address), the names given (empty: all).
probe_from() { # from-ip other-guest-address source names...
    local from=$1 other=$2 source=$3 spec
    shift 3
    spec=$(mktemp)
    probe_spec "$other" "$source" "$@" >"$spec"
    compose cp "$spec" cape:/tmp/isolation-spec.tsv >/dev/null 2>&1
    rm -f "$spec"
    store_on_guest "$from" /tmp/isolation-spec.tsv 'C:\tartarus\isolation-spec.tsv' || return 1
    guest_output "$from" "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/tartarus/isolation-probe.ps1 -SpecFile C:/tartarus/isolation-spec.tsv"
}

# --- what is set up on a guest, and taken down again ---------------------------------------------------

rooter_route() { # enable|disable route ip
    compose exec -T -u cape -w /opt/CAPEv2 cape /opt/CAPEv2/.venv/bin/python - "$@" <"$ROUTE_SCRIPT" >/dev/null 2>&1
}

open_route() { # ip route
    [[ $2 == raw ]] && return 0
    OPEN_ROUTES+=("$1 $2")
    rooter_route enable "$2" "$1"
}

close_route() { # ip route
    [[ $2 == raw ]] && return 0
    rooter_route disable "$2" "$1"
    local kept=() entry
    for entry in "${OPEN_ROUTES[@]}"; do [[ $entry == "$1 $2" ]] || kept+=("$entry"); done
    OPEN_ROUTES=("${kept[@]}")
}

address_is_usable() { # guest-ip address
    [[ $(guest_output "$1" "powershell.exe -NoProfile -Command \"(Get-NetIPAddress -IPAddress $2).AddressState\"") == Preferred ]]
}

# Windows does not send from a new address until its duplicate address detection is over.
add_address() { # guest-ip address
    ADDED_ADDRESSES+=("$1 $2")
    guest_output "$1" "netsh interface ipv4 add address name=$(adapter_of "$1") address=$2 mask=$GUEST_NETMASK" >/dev/null
    local deadline=$((SECONDS + ADDRESS_TIMEOUT))
    until address_is_usable "$1" "$2"; do
        ((SECONDS < deadline)) || { fail "$2 on $1 is still not usable after ${ADDRESS_TIMEOUT}s"; return 1; }
        sleep 2
    done
}

remove_address() { # guest-ip address
    guest_output "$1" "netsh interface ipv4 delete address name=$(adapter_of "$1") address=$2" >/dev/null
    local kept=() entry
    for entry in "${ADDED_ADDRESSES[@]}"; do [[ $entry == "$1 $2" ]] || kept+=("$entry"); done
    ADDED_ADDRESSES=("${kept[@]}")
}

# A neighbour entry that sends `peer` over the gateway's MAC, so the packets are routed, not bridged.
add_neighbor() { # guest-ip peer-ip
    ADDED_NEIGHBORS+=("$1 $2")
    guest_output "$1" "netsh interface ipv4 add neighbors $(adapter_of "$1") $2 $GATEWAY_MAC" >/dev/null
}

remove_neighbor() { # guest-ip peer-ip
    guest_output "$1" "netsh interface ipv4 delete neighbors $(adapter_of "$1") $2" >/dev/null
    local kept=() entry
    for entry in "${ADDED_NEIGHBORS[@]}"; do [[ $entry == "$1 $2" ]] || kept+=("$entry"); done
    ADDED_NEIGHBORS=("${kept[@]}")
}

# --- verdicts ---------------------------------------------------------------------------------------

reach() { # probe-output probe-name -> yes, no, or nothing when the probe did not report it
    sed -n "s|^REACH $2 ||p" <<<"$1" | head -n1
}

# Compares what the probe reported with what the scenario allows; prints every probe that differs.
verdict() { # probe-output scenario other-guest-address names...
    local output=$1 scenario=$2 other=$3 name target port payload marker scenarios answer wanted joined
    local problems=() count=0
    shift 3
    grep -qx 'DONE' <<<"$output" || { echo "the probe did not finish; output: ${output:0:200}"; return 1; }
    while IFS=';' read -r name target port payload marker scenarios; do
        [[ -n $target ]] && ! is_skipped "$name" || continue
        (($# == 0)) || [[ " $* " == *" $name "* ]] || continue
        answer=$(reach "$output" "$name")
        [[ " $scenarios " == *" $scenario "* ]] && wanted=yes || wanted=no
        count=$((count + 1))
        [[ $answer == "$wanted" ]] || problems+=("$name -> ${answer:-no report}, expected $wanted")
    done < <(catalogue "$other")
    if ((${#problems[@]} == 0)); then echo "$count probes"; return 0; fi
    printf -v joined '%s; ' "${problems[@]}"
    echo "${joined%; }"
    return 1
}

verify_route() { # label ip other-ip route
    local label=$1 ip=$2 other_ip=$3 route=$4 output
    open_route "$ip" "$route"
    output=$(probe_from "$ip" "$other_ip" "")
    check "$label on route $route: every probe answers as expected" verdict "$output" "$route" "$other_ip"
    close_route "$ip" "$route"
}

verify_invented_address() { # label ip other-ip
    local label=$1 ip=$2 other_ip=$3 output
    add_address "$ip" "$INVENTED_IP" || { remove_address "$ip" "$INVENTED_IP"; return; }
    open_route "$ip" internet
    output=$(probe_from "$ip" "$other_ip" "$INVENTED_IP")
    check "$label from an address of its own invention: every probe answers as expected" \
        verdict "$output" invented "$other_ip"
    close_route "$ip" internet
    remove_address "$ip" "$INVENTED_IP"
}

# The other guest's address is the one the rooter may have opened a route for.
verify_claimed_address() { # label ip other-label other-ip
    local label=$1 ip=$2 other=$3 other_ip=$4 output
    add_address "$ip" "$other_ip" || { remove_address "$ip" "$other_ip"; return; }
    open_route "$ip" internet
    open_route "$other_ip" internet
    output=$(probe_from "$ip" "$other_ip" "$other_ip")
    check "$label claiming the address of $other: every probe answers as expected" verdict "$output" claimed "$other_ip"
    close_route "$other_ip" internet
    close_route "$ip" internet
    remove_address "$ip" "$other_ip"
}

verify_hairpin() { # from-label from-ip to-label to-ip route
    local from=$1 from_ip=$2 to=$3 to_ip=$4 route=$5 output
    output=$(probe_from "$from_ip" "$to_ip" "" other-guest-agent other-guest-ping)
    check "$from to $to through the gateway on route $route: every probe answers as expected" \
        verdict "$output" hairpin "$to_ip" other-guest-agent other-guest-ping
}

verify_hairpins() { # a a-ip b b-ip
    local route
    for route in raw internet; do
        open_route "$2" "$route"
        open_route "$4" "$route"
        add_neighbor "$2" "$4"
        add_neighbor "$4" "$2"
        verify_hairpin "$1" "$2" "$3" "$4" "$route"
        verify_hairpin "$3" "$4" "$1" "$2" "$route"
        remove_neighbor "$4" "$2"
        remove_neighbor "$2" "$4"
        close_route "$4" "$route"
        close_route "$2" "$route"
    done
}

main() {
    local a=$1 b=$2 a_ip b_ip route
    trap cleanup EXIT
    compose up -d --wait cape >/dev/null 2>&1 || { fail "setup: cape unhealthy"; exit 1; }
    export CAPE_API_TOKEN=${CAPE_API_TOKEN:-$(in_cape printenv CAPE_API_TOKEN)}
    discover_gateway
    a_ip=$(guest_address "$a")
    b_ip=$(guest_address "$b")
    [[ -n $a_ip && -n $b_ip ]] || { fail "setup: CAPE does not list both '$a' and '$b' (ready guests?)"; exit 1; }

    # Recorded here, not inside start_guest: `check` runs it in a subshell, where STARTED would be lost.
    is_running "$a" || STARTED+=("$a")
    is_running "$b" || STARTED+=("$b")
    check "$a starts and its agent answers at $a_ip:8000" start_guest "$a" "$a_ip" || exit 1
    check "$b starts and its agent answers at $b_ip:8000" start_guest "$b" "$b_ip" || exit 1
    check "the probe is stored on $a and $b" store_probe_on "$a_ip" "$b_ip" || exit 1

    discover_targets
    start_host_canary
    skip_what_nothing_reaches

    for route in "${ROUTES[@]}"; do
        verify_route "$a" "$a_ip" "$b_ip" "$route"
        verify_route "$b" "$b_ip" "$a_ip" "$route"
    done
    verify_invented_address "$a" "$a_ip" "$b_ip"
    verify_invented_address "$b" "$b_ip" "$a_ip"
    verify_claimed_address "$a" "$a_ip" "$b" "$b_ip"
    verify_claimed_address "$b" "$b_ip" "$a" "$a_ip"
    verify_hairpins "$a" "$a_ip" "$b" "$b_ip"
}

[[ $# -eq 2 && $1 != "$2" ]] || { echo "usage: verify-isolation.sh GUEST_A GUEST_B   (two different ready guests)" >&2; exit 2; }
main "$1" "$2"

exit "$failed"
