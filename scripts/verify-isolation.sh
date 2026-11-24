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
# the gateway services, the CAPE web process (answers 404 to the probe: only its Server header counts), guacd and the control service on the cape container's own
# addresses, the backend, Postgres and OpenSearch, a canary on the docker host and on its LAN address, the
# internet, and the other guest. A probe whose target does not answer outside a guest either proves
# nothing and is skipped with an [INFO] line.
#
# Then the tricks a hostile guest has: sending from an address it invented (the rooter's rules are keyed
# on the registered one), from the other guest's address, and to the other guest through the gateway
# (a neighbour entry for the gateway's MAC on both guests, so that routing, not the bridge, carries it).
#
# Last, the GUEST_BLOCKED_ADDRESSES setting: the guest firewall is applied again with one internet address
# added to the setting, and a guest on the `internet` route must lose that address and keep its neighbour.
# Applying the firewall binds no port, so both guests are powered off for it and one is started again; that
# is why this part runs only when the script started both guests itself, and only where the internet
# answers. The firewall is applied as configured again afterwards, also when the script is interrupted.
#
# Then the fake local network (docs/features/fake-lan.md). Every check above also probes every service of every
# preset, on the control service's own list of presets: with no session they are as silent as before. The LAN
# section then opens a session through the control service with the backend's own client
# (scripts/lib/lan-session.py), as the backend does before an analysis: one for the first guest (small-office),
# then one for the second (flat-home), and proves on the routes raw, none and inetsim (not internet: the backend
# refuses it with a preset) that
#   - a guest reaches every (host, port) of its preset and gets the fake service's own first answer (SSH banner,
#     WinRM 401, SMB2 negotiate reply, LDAP rootDSE, RDP connection confirm, MSSQL prelogin reply), answers ping
#     with TTL 128 and resolves ARP for the preset's hosts, and nothing else of the catalogue above;
#   - a port the preset does not serve on one of its hosts, and every host of another preset, neither answers
#     nor refuses (a RST would mean the firewall let the packet reach the kernel) and has no ARP entry;
#   - a guest with no session reaches none of the fake hosts, and two guests with sessions for different presets
#     reach exactly their own and never each other;
#   - the tricks above still fail with sessions open, and so does taking a fake address as its own (the guest
#     switches duplicate address detection off): nothing sent from there gets through;
#   - after the sessions are closed every probe is back to its no-session result and the cape container's
#     firewall state (both tartarus_guest tables, iptables rules of tartarus-lan, routes of protocol 77, listening
#     sockets) is what it was before the first session, packet counters aside.
# Sessions are closed, and the guests powered off, also when the script is interrupted.
# Exit 0 when all hold, 1 otherwise, 2 on bad usage.
#
# The negative proof, that the check can fail: with ISOLATION_NEGATIVE_PROOF=1 the LAN section deletes both
# tartarus_guest tables right after each session opens (opening a session applies the whole ruleset again, so
# deleting them beforehand would be undone):
#   ISOLATION_NEGATIVE_PROOF=1 scripts/verify-isolation.sh GUEST_A GUEST_B
# It must exit 1 naming what the guests now reach. The sessions die with the firewall's next `init`, which
# the script runs when it ends (and which restores the tables); by hand, while the guests run,
#   docker compose exec -T cape nft delete table inet tartarus_guest
#   docker compose exec -T cape nft delete table bridge tartarus_guest
# and `docker compose exec -T cape python3 -I /usr/local/lib/tartarus/guest-firewall init` restores them.
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
INTERNET_CONTROL_ADDRESS=1.0.0.1
APPLY_FIREWALL=(python3 -I /usr/local/lib/tartarus/guest-firewall init)
GUEST_NETMASK=255.255.255.0
BACKEND_IMAGE=tartarus-backend:latest
LAN_SESSION_SCRIPT=$REPO/scripts/lib/lan-session.py
LAN_ROUTES=(raw none inetsim)
LAN_PRESET_A=${ISOLATION_LAN_PRESET_A:-small-office}
LAN_PRESET_B=${ISOLATION_LAN_PRESET_B:-flat-home}
LAN_KEY_PREFIX=isolation-$$
NEGATIVE_PROOF=${ISOLATION_NEGATIVE_PROOF:-}
# A port no preset serves, to see whether a firewall opens a whole fake host or only its services.
LAN_CLOSED_PORT=8080
FAKE_HOST_TTL_MARKER='TTL=128'
DEFAULT_DAD_TRANSMITS=3

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
TEST_ADDRESS_BLOCKED=""
LAN_SERVICES=""
LAN_SESSIONS=()
LAN_SEQUENCE=0
FIREWALL_BASELINE=""
DAD_SWITCHED_OFF=()
TABLES_DELETED=""

cleanup() {
    local entry
    for entry in "${OPEN_ROUTES[@]}"; do close_route ${entry}; done
    for entry in "${ADDED_NEIGHBORS[@]}"; do remove_neighbor ${entry}; done
    for entry in "${ADDED_ADDRESSES[@]}"; do remove_address ${entry}; done
    for entry in "${DAD_SWITCHED_OFF[@]}"; do set_duplicate_detection "$entry" "$DEFAULT_DAD_TRANSMITS"; done
    for entry in "${LAN_SESSIONS[@]}"; do lan_control close "$entry" >/dev/null 2>&1; done
    [[ -z $TABLES_DELETED ]] || apply_firewall_as_configured
    [[ -z $CANARY_PID ]] || kill "$CANARY_PID" 2>/dev/null
    [[ -z $CANARY_DIR ]] || rm -rf "$CANARY_DIR"
    for entry in "${STARTED[@]}"; do virsh_cape destroy "$entry" >/dev/null 2>&1; done
    [[ -z $TEST_ADDRESS_BLOCKED ]] || apply_firewall_as_configured
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
        winrm) printf 'POST /wsman HTTP/1.1\r\nHost: probe\r\nContent-Length: 0\r\nConnection: close\r\n\r\n' | base64 -w0 ;;
        smb) smb2_negotiate | base64 -w0 ;;
        ldap) printf '\x30\x25\x02\x01\x01\x63\x20\x04\x00\x0a\x01\x00\x0a\x01\x00\x02\x01\x00\x02\x01\x00\x01\x01\x00\x87\x0bobjectClass\x30\x00' | base64 -w0 ;;
        rdp) printf '\x03\x00\x00\x13\x0e\xe0\x00\x00\x00\x00\x00\x01\x00\x08\x00\x03\x00\x00\x00' | base64 -w0 ;;
        mssql) printf '\x12\x01\x00\x1a\x00\x00\x01\x00\x00\x00\x0b\x00\x06\x01\x00\x11\x00\x01\xff\x0e\x00\x0c\x53\x00\x00\x00' | base64 -w0 ;;
    esac
}

# An SMB2 NEGOTIATE offering dialect 2.1 behind a NetBIOS header: 64 bytes of header, 36 of body, one dialect.
smb2_negotiate() {
    printf '\x00\x00\x00\x66\xfeSMB\x40\x00'
    head -c 8 /dev/zero
    printf '\x01\x00'
    head -c 48 /dev/zero
    printf '\x24\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00\x00'
    head -c 24 /dev/zero
    printf '\x10\x02'
}

# name;target;port;payload kind;marker (extended regex);scenarios in which the target is reachable
# A scenario is a route (raw none inetsim internet), `invented` (a guest sending from an address of its own
# invention), `claimed` (a guest that took the other guest's address, which is then its own: it reaches
# itself), `blocked` (the internet route with $INTERNET_ADDRESS in GUEST_BLOCKED_ADDRESSES), `fakeown` (a guest
# that took an address of the fake LAN as its own: nothing is reachable) or `preset-<id>` (a session for that
# preset is open, on top of the route). The gateway services are the only thing a guest reaches whatever it
# does: they run on the address it is given, and INetSim's DNS and HTTP are what the inetsim route is for.
catalogue() { # other-guest-address
    cat <<EOF
gateway-dns;$GATEWAY_IP;53;;;raw inetsim internet invented
gateway-http;$GATEWAY_IP;80;get;INetSim;raw inetsim internet invented
gateway-resultserver;$GATEWAY_IP;2042;;;raw none inetsim internet invented
cape-web;$CAPE_INTERNAL_IP;8000;get;Server: gunicorn;
guacd;$CAPE_INTERNAL_IP;4822;guacd;4\.args;
guest-control;$CAPE_CONTROL_IP;8002;get;unauthorized;
backend;$BACKEND_IP;8000;get;uvicorn;
postgres;$POSTGRES_IP;5432;postgres;SCRAM|FATAL;
opensearch;$OPENSEARCH_IP;9200;get;cluster_name;
docker-host;$DOCKER_HOST_IP;$CANARY_PORT;get;$CANARY_TEXT;
lan-host;$LAN_IP;$CANARY_PORT;get;$CANARY_TEXT;
internet;$INTERNET_ADDRESS;80;get;HTTP/1\.[01] (301|400|403);internet
internet-control;$INTERNET_CONTROL_ADDRESS;80;get;HTTP/1\.[01] (301|400|403);internet blocked
other-guest-agent;$1;8000;get;CAPE Agent;claimed
other-guest-ping;$1;icmp;;;claimed
EOF
    lan_catalogue
}

# What a fake service answers first, as `payload kind;marker`: the daemon's own greeting, which neither
# INetSim (it accepts anything and says HELLO) nor a bare connect can fake.
lan_probe_kind() { # service-kind
    case $1 in
        ssh) echo ';SSH-2\.0-OpenSSH_' ;;
        winrm) echo 'winrm;(?s)HTTP/1\.[01] 401.*WWW-Authenticate' ;;
        smb) echo 'smb;^\x00[\s\S]{3}\xfeSMB' ;;
        ldap) echo 'ldap;namingContexts' ;;
        rdp) echo 'rdp;^\x03\x00\x00[\s\S]\x0e\xd0' ;;
        mssql) echo 'mssql;^\x04\x01' ;;
        *) return 1 ;;
    esac
}

# Every service and host of every preset, reachable only in the scenario `preset-<id>`: the service's own
# answer, whether anything answers on that port at all, and per host a port no preset serves, ping, a ping
# that must come back with a Windows host's TTL, and an ARP entry. Names are lan-<last octet>-<what>.
lan_catalogue() {
    local preset address port kind octet payload marker hosts=" "
    while IFS=';' read -r preset address port kind; do
        [[ -n $address ]] || continue
        octet=${address##*.}
        IFS=';' read -r payload marker <<<"$(lan_probe_kind "$kind")"
        printf 'lan-%s-%s;%s;%s;%s;%s;preset-%s\n' "$octet" "$port" "$address" "$port" "$payload" "$marker" "$preset"
        printf 'lan-%s-%s-answers;%s;any:%s;;;preset-%s\n' "$octet" "$port" "$address" "$port" "$preset"
        [[ $hosts != *" $address "* ]] || continue
        hosts+="$address "
        printf 'lan-%s-closed;%s;any:%s;;;\n' "$octet" "$address" "$LAN_CLOSED_PORT"
        printf 'lan-%s-ping;%s;icmp;;;preset-%s\n' "$octet" "$address" "$preset"
        printf 'lan-%s-ttl;%s;icmp;;%s;preset-%s\n' "$octet" "$address" "$FAKE_HOST_TTL_MARKER" "$preset"
        printf 'lan-%s-arp;%s;arp;;;preset-%s\n' "$octet" "$address" "$preset"
    done <<<"$LAN_SERVICES"
}

SKIPPED=" "
is_skipped() { [[ $SKIPPED == *" $1 "* ]]; }

# The container's own programs have no route out (guest_engine/egress.py), so a target outside it is
# tried from a throwaway container on the same two networks, which sees what cape's namespace forwards
# to. The container's own listeners are tried from inside it.
beside_cape() {
    docker run --rm -i --network tartarus-internal --network tartarus-cape-db --entrypoint "" "$CAPE_IMAGE" "$@" </dev/null
}

answers_outside_a_guest() { # name target port payload-kind marker
    local from=beside_cape
    case $1 in cape-web | guacd | guest-control) from=in_cape ;; esac
    "$from" bash -c 'exec 3<>"/dev/tcp/$0/$1" || exit 1; printf %s "$2" | base64 -d >&3; timeout 3 cat <&3 | head -c 4096' \
        "$2" "$3" "$(payload_for "$4")" 2>/dev/null | grep -Eaq -- "$5"
}

# A target that nothing outside a guest reaches either would also look blocked to a guest for a reason
# that has nothing to do with isolation.
skip_what_nothing_reaches() {
    local name target port payload marker _
    while IFS=';' read -r name target port payload marker _; do
        case $name in gateway-* | other-guest-* | lan-*) continue ;; esac
        if [[ -z $target ]]; then info "$name has no address here: not probed"; SKIPPED+="$name "
        elif ! answers_outside_a_guest "$name" "$target" "$port" "$payload" "$marker"; then
            info "$name does not answer outside a guest either: not probed from the guests"
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

# A scenario may be several words (a route and the preset a session was opened for): a probe is wanted when
# its list holds any of them.
scenario_allows() { # scenarios-of-the-probe scenario-words
    local word
    for word in $2; do [[ " $1 " == *" $word "* ]] && return 0; done
    return 1
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
        scenario_allows "$scenarios" "$scenario" && wanted=yes || wanted=no
        count=$((count + 1))
        [[ $answer == "$wanted" ]] || problems+=("$name -> ${answer:-no report}, expected $wanted")
    done < <(catalogue "$other")
    if ((${#problems[@]} == 0)); then echo "$count probes"; return 0; fi
    printf -v joined '%s; ' "${problems[@]}"
    echo "${joined%; }"
    return 1
}

verify_route() { # label ip other-ip route [scenario words of a session]
    local label=$1 ip=$2 other_ip=$3 route=$4 session=${5:-} output
    open_route "$ip" "$route"
    output=$(probe_from "$ip" "$other_ip" "")
    check "$label on route $route: every probe answers as expected" verdict "$output" "$route${session:+ $session}" "$other_ip"
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

verify_hairpin() { # from-description from-ip to-label to-ip route
    local from=$1 from_ip=$2 to=$3 to_ip=$4 route=$5 output
    output=$(probe_from "$from_ip" "$to_ip" "" other-guest-agent other-guest-ping)
    check "$from to $to through the gateway on route $route: every probe answers as expected" \
        verdict "$output" hairpin "$to_ip" other-guest-agent other-guest-ping
}

verify_hairpins() { # a a-ip b b-ip [a-description b-description]
    local route a_description=${5:-$1} b_description=${6:-$3}
    for route in raw internet; do
        open_route "$2" "$route"
        open_route "$4" "$route"
        add_neighbor "$2" "$4"
        add_neighbor "$4" "$2"
        verify_hairpin "$a_description" "$2" "$3" "$4" "$route"
        verify_hairpin "$b_description" "$4" "$1" "$2" "$route"
        remove_neighbor "$4" "$2"
        remove_neighbor "$2" "$4"
        close_route "$4" "$route"
        close_route "$2" "$route"
    done
}

# --- the fake LAN -----------------------------------------------------------------------------------

# The backend's own client, in a throwaway container of its image on the control network with the working
# tree's backend/app over the image's copy: the request is the one the backend sends, whatever the image is.
lan_control() { # health | presets | list | open key guest preset | close key
    docker run --rm -i --network tartarus-control -e GUEST_CONTROL_URL=http://cape-control:8002 -e GUEST_CONTROL_TOKEN \
        -v "$REPO/backend/app:/app/app:ro" -w /app --entrypoint "" "$BACKEND_IMAGE" python - "$@" <"$LAN_SESSION_SCRIPT"
}

# Fails the run when the fake LAN cannot be probed, and reads the presets every check is built from.
discover_fake_lan() {
    local state held kinds kind
    state=$(lan_control health 2>&1)
    [[ $state == ready ]] || { fail "setup: the fake LAN is not ready (${state//$'\n'/; })"; return 1; }
    held=$(lan_control list 2>&1 | paste -sd, -)
    [[ -z $held ]] || { fail "setup: a LAN session is open already (${held//,/, })"; return 1; }
    LAN_SERVICES=$(lan_control presets 2>&1)
    [[ -n $LAN_SERVICES ]] || { fail "setup: the control service lists no LAN preset"; return 1; }
    kinds=$(cut -d';' -f4 <<<"$LAN_SERVICES" | sort -u)
    for kind in $kinds; do
        lan_probe_kind "$kind" >/dev/null || { fail "setup: the probe knows no first request for the fake $kind service"; return 1; }
    done
}

preset_address() { # preset -> the first host's address
    awk -F';' -v preset="$1" '$1 == preset {print $2; exit}' <<<"$LAN_SERVICES"
}

open_lan_session() { # guest-label preset
    LAN_SEQUENCE=$((LAN_SEQUENCE + 1))
    local key=$LAN_KEY_PREFIX-$LAN_SEQUENCE
    LAN_SESSIONS+=("$key")
    check "a LAN session for $1 ($2) is opened through the control service" lan_control open "$key" "$1" "$2" || return 1
    [[ -z $NEGATIVE_PROOF ]] || delete_guest_tables
}

close_lan_sessions() {
    local key
    for key in "${LAN_SESSIONS[@]}"; do
        check "the LAN session $key is closed" lan_control close "$key" || return 1
    done
    LAN_SESSIONS=()
}

# The negative proof: what the guest firewall would be without its tables. Opening a session applies the
# whole ruleset again, so every session is followed by this.
delete_guest_tables() {
    TABLES_DELETED=yes
    in_cape nft delete table inet tartarus_guest
    in_cape nft delete table bridge tartarus_guest
}

# Everything a session adds to the cape container's network state and must take away again. Packet
# counters are stripped: they count what the probes sent.
cape_firewall_state() {
    in_cape sh -c '{
        nft list table inet tartarus_guest 2>&1
        nft list table bridge tartarus_guest 2>&1
        nft list tables | sort
        iptables-save | grep tartarus-lan
        ip -4 route show table local proto 77
        ss -ltnH | awk "{print \$4}" | sort
    } | sed -E "s/counter packets [0-9]+ bytes [0-9]+/counter/"; true'
}

firewall_state_is_the_baseline() {
    local now
    now=$(cape_firewall_state)
    [[ $now == "$FIREWALL_BASELINE" ]] && return 0
    diff <(echo "$FIREWALL_BASELINE") <(echo "$now") | grep '^[<>]' | head -n 10
    return 1
}

set_duplicate_detection() { # guest-ip transmits
    guest_output "$1" "netsh interface ipv4 set interface name=$(adapter_of "$1") dadtransmits=$2" >/dev/null
}

# A hostile guest may take an address of the fake LAN as its own, with duplicate address detection off so the
# fake host's ARP answer does not stop it; whatever it sends from there must be dropped, the gateway's
# services included.
verify_fake_address() { # label ip other-ip fake-address
    local label=$1 ip=$2 other_ip=$3 fake=$4 output
    DAD_SWITCHED_OFF+=("$ip")
    set_duplicate_detection "$ip" 0
    if add_address "$ip" "$fake"; then
        open_route "$ip" internet
        # What the guest sends to the address it took never leaves it: its own stack answers (its SMB service,
        # a refusal from a closed port, ping), so those probes judge the guest, not the firewall.
        names=$(catalogue "$other_ip" | awk -F';' -v taken="$fake" '$2 != "" && $2 != taken {print $1}')
        output=$(probe_from "$ip" "$other_ip" "$fake" $names)
        check "$label taking the fake address $fake as its own: every probe answers as expected" \
            verdict "$output" fakeown "$other_ip" $names
        close_route "$ip" internet
    fi
    remove_address "$ip" "$fake"
    set_duplicate_detection "$ip" "$DEFAULT_DAD_TRANSMITS"
    DAD_SWITCHED_OFF=()
}

verify_lan_routes() { # a-label a-ip a-scenario b-label b-ip b-scenario
    local route
    for route in "${LAN_ROUTES[@]}"; do
        verify_route "$1" "$2" "$5" "$route" "$3"
        verify_route "$4" "$5" "$2" "$route" "$6"
    done
}

verify_lan() { # a a-ip b b-ip
    local a=$1 a_ip=$2 b=$3 b_ip=$4
    local a_held="$a with a $LAN_PRESET_A LAN session" b_held="$b with a $LAN_PRESET_B LAN session"
    info "the LAN section skips the internet route: the backend refuses it together with a preset"
    [[ -z $NEGATIVE_PROOF ]] || info "negative proof: every LAN session is followed by deleting the two tartarus_guest tables, so this run must fail"
    FIREWALL_BASELINE=$(cape_firewall_state)

    open_lan_session "$a" "$LAN_PRESET_A" || return
    verify_lan_routes "$a_held" "$a_ip" "preset-$LAN_PRESET_A" "$b with no LAN session of its own" "$b_ip" ""

    open_lan_session "$b" "$LAN_PRESET_B" || return
    verify_lan_routes "$a with a $LAN_PRESET_A session beside a guest with a $LAN_PRESET_B session" "$a_ip" "preset-$LAN_PRESET_A" \
        "$b with a $LAN_PRESET_B session beside a guest with a $LAN_PRESET_A session" "$b_ip" "preset-$LAN_PRESET_B"

    verify_invented_address "$a_held" "$a_ip" "$b_ip"
    verify_invented_address "$b_held" "$b_ip" "$a_ip"
    verify_claimed_address "$a_held" "$a_ip" "$b" "$b_ip"
    verify_claimed_address "$b_held" "$b_ip" "$a" "$a_ip"
    verify_hairpins "$a" "$a_ip" "$b" "$b_ip" "$a_held" "$b_held"
    verify_fake_address "$a_held" "$a_ip" "$b_ip" "$(preset_address "$LAN_PRESET_A")"
    verify_fake_address "$a_held" "$a_ip" "$b_ip" "$(preset_address "$LAN_PRESET_B")"

    close_lan_sessions || return
    check "the firewall state of the cape container after the sessions closed is the one from before the first session" \
        firewall_state_is_the_baseline
    verify_lan_routes "$a after its LAN session closed" "$a_ip" "" "$b after its LAN session closed" "$b_ip" ""
}

# --- GUEST_BLOCKED_ADDRESSES ------------------------------------------------------------------------------

apply_firewall_as_configured() { in_cape "${APPLY_FIREWALL[@]}"; }

apply_firewall_blocking() { # address
    local configured
    configured=$(in_cape printenv GUEST_BLOCKED_ADDRESSES)
    compose exec -T -e "GUEST_BLOCKED_ADDRESSES=${configured:+$configured,}$1" cape "${APPLY_FIREWALL[@]}" </dev/null
}

probe_blocked_address() { # label ip other-ip
    local label=$1 ip=$2 other_ip=$3 output
    check "$label starts again and its agent answers at $ip:8000" start_guest "$label" "$ip" || return 1
    check "the probe is stored on $label again" store_probe_on "$ip" || return 1
    open_route "$ip" internet
    output=$(probe_from "$ip" "$other_ip" "" internet internet-control)
    check "$label on route internet with $INTERNET_ADDRESS in GUEST_BLOCKED_ADDRESSES: every probe answers as expected" \
        verdict "$output" blocked "$other_ip" internet internet-control
    close_route "$ip" internet
}

verify_blocked_setting() { # a a-ip b b-ip
    local a=$1 a_ip=$2 b=$3 b_ip=$4
    if is_skipped internet || is_skipped internet-control; then
        info "GUEST_BLOCKED_ADDRESSES is not probed: the internet does not answer here"
        return
    fi
    if [[ " ${STARTED[*]} " != *" $a "* || " ${STARTED[*]} " != *" $b "* ]]; then
        info "GUEST_BLOCKED_ADDRESSES is not probed: a guest was running before, and applying the firewall again would cut it off"
        return
    fi
    virsh_cape destroy "$a" >/dev/null 2>&1
    virsh_cape destroy "$b" >/dev/null 2>&1
    # Set here, not inside the check: `check` runs its command in a subshell.
    TEST_ADDRESS_BLOCKED=yes
    if check "the guest firewall is applied with $INTERNET_ADDRESS in GUEST_BLOCKED_ADDRESSES" apply_firewall_blocking "$INTERNET_ADDRESS"; then
        probe_blocked_address "$a" "$a_ip" "$b_ip"
        virsh_cape destroy "$a" >/dev/null 2>&1
    fi
    check "the guest firewall is applied as configured again" apply_firewall_as_configured && TEST_ADDRESS_BLOCKED=""
}

main() {
    local a=$1 b=$2 a_ip b_ip route
    trap cleanup EXIT
    trap 'exit 130' INT TERM
    compose up -d --wait cape >/dev/null 2>&1 || { fail "setup: cape unhealthy"; exit 1; }
    export CAPE_API_TOKEN=${CAPE_API_TOKEN:-$(in_cape printenv CAPE_API_TOKEN)}
    discover_gateway
    a_ip=$(guest_address "$a")
    b_ip=$(guest_address "$b")
    [[ -n $a_ip && -n $b_ip ]] || { fail "setup: CAPE does not list both '$a' and '$b' (ready guests?)"; exit 1; }
    export GUEST_CONTROL_TOKEN=${GUEST_CONTROL_TOKEN:-$(in_cape printenv GUEST_CONTROL_TOKEN)}
    discover_fake_lan || exit 1

    # Recorded here, not inside start_guest: `check` runs it in a subshell, where STARTED would be lost.
    is_running "$a" || STARTED+=("$a")
    is_running "$b" || STARTED+=("$b")
    check "$a starts and its agent answers at $a_ip:8000" start_guest "$a" "$a_ip" || exit 1
    check "$b starts and its agent answers at $b_ip:8000" start_guest "$b" "$b_ip" || exit 1
    check "the probe is stored on $a and $b" store_probe_on "$a_ip" "$b_ip" || exit 1

    discover_targets
    start_host_canary
    skip_what_nothing_reaches
    info "the fake LAN's $(grep -c . <<<"$LAN_SERVICES") services are probed in every check below, and are silent without a session"

    for route in "${ROUTES[@]}"; do
        verify_route "$a" "$a_ip" "$b_ip" "$route"
        verify_route "$b" "$b_ip" "$a_ip" "$route"
    done
    verify_invented_address "$a" "$a_ip" "$b_ip"
    verify_invented_address "$b" "$b_ip" "$a_ip"
    verify_claimed_address "$a" "$a_ip" "$b" "$b_ip"
    verify_claimed_address "$b" "$b_ip" "$a" "$a_ip"
    verify_hairpins "$a" "$a_ip" "$b" "$b_ip"
    verify_lan "$a" "$a_ip" "$b" "$b_ip"
    verify_blocked_setting "$a" "$a_ip" "$b" "$b_ip"
}

[[ $# -eq 2 && $1 != "$2" ]] || { echo "usage: verify-isolation.sh GUEST_A GUEST_B   (two different ready guests)" >&2; exit 2; }
main "$1" "$2"

exit "$failed"
