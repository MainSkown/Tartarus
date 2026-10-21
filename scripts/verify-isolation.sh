#!/usr/bin/env bash
# Proves task 3.0 of docs/plans/m9-beyond-one-run.md: two guests on the shared tt-guest bridge cannot
# reach each other, and both still reach the gateway services.
#
#   scripts/verify-isolation.sh GUEST_A GUEST_B
#
# Needs the stack up (make up) and two ready guests (their labels as `make` shows them). Each guest that
# is not running is started by reverting its tartarus-clean snapshot, which also proves that a revert
# re-applies the isolated port; the guests this script started are powered off again at the end. Stop any
# analysis first: the guests are driven through their agents, not through CAPE.
#
# From inside guest A (and the other way round) it probes B on tcp/8000 (the CAPE agent), tcp/445 (SMB)
# and ping, expecting every one to fail, and from each guest the gateway on tcp/2042 (ResultServer) and
# tcp/80 (INetSim), expecting both to connect. Exit 0 when all hold, 1 otherwise, 2 on bad usage.
#
# The negative proof, that the check can fail: while both guests run (start them first with
#   docker compose exec -T cape virsh -c qemu:///system snapshot-revert GUEST tartarus-clean),
# find A's tap and switch the flag off in the cape container's network namespace
#   docker compose exec -T cape virsh -c qemu:///system domiflist GUEST_A        # the vnetN column
#   docker compose exec -T cape bridge link set dev vnetN isolated off
# then run the script again: it must exit 1 with the [FAIL] lines naming what A reached. The tap is
# recreated at every start, so a revert restores `isolated on` from the domain.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO=$PWD

CAPE_IMAGE=tartarus-cape:latest
PROBE_SCRIPT=$REPO/scripts/lib/isolation-probe.ps1
GUEST_PORTS=8000,445
GATEWAY_PORTS=2042,80
AGENT_TIMEOUT=${ISOLATION_AGENT_TIMEOUT:-300}
PROBE_TIMEOUT=${ISOLATION_PROBE_TIMEOUT:-90}

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
in_cape() { compose exec -T cape "$@"; }
virsh_cape() { in_cape virsh -c qemu:///system "$@"; }
on_internal() { docker run --rm -i -e CAPE_API_TOKEN --network tartarus-internal --entrypoint "" "$CAPE_IMAGE" "$@"; }

STARTED=()
cleanup() {
    local guest
    for guest in "${STARTED[@]}"; do virsh_cape destroy "$guest" >/dev/null 2>&1; done
}

gateway_address() {
    local subnet
    subnet=$(in_cape printenv GUEST_SUBNET 2>/dev/null)
    subnet=${subnet:-192.168.150.0/24}
    GATEWAY_IP=${subnet%.0/24}.1
}

# The address CAPE has registered for a guest label.
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

store_probe_on() { # ip...
    local ip
    compose cp "$PROBE_SCRIPT" cape:/tmp/isolation-probe.ps1 >/dev/null 2>&1 || return 1
    for ip in "$@"; do
        in_cape curl -s -m 20 -F filepath='C:\tartarus\isolation-probe.ps1' -F file=@/tmp/isolation-probe.ps1 \
            "http://$ip:8000/store" >/dev/null || return 1
    done
}

# Runs the probe inside the guest at `from_ip` against `target_ip` and prints what the guest printed.
probe_from() { # from_ip target_ip ports [-Ping]
    local from=$1 target=$2 ports=$3 ping=${4:-}
    # The agent shlex-splits the command POSIX-style, which would eat backslashes in the path.
    in_cape curl -s -m "$PROBE_TIMEOUT" \
        -F "command=powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/tartarus/isolation-probe.ps1 -Target $target -Ports $ports $ping" \
        "http://$from:8000/execute" |
        python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("stdout") or "")
except ValueError: pass' | tr -d '\r'
}

reach() { # probe-output probe-name -> yes, no, or nothing when the probe did not report it
    sed -n "s|^REACH $2 ||p" <<<"$1" | head -n1
}

expect_reach() { # probe-output probe-name expected
    local answer
    answer=$(reach "$1" "$2")
    [[ $answer == "$3" ]] && { echo "$2 -> $answer"; return 0; }
    echo "$2 -> ${answer:-no report}, expected $3"
    return 1
}

probe_completed() { grep -qx 'DONE' <<<"$1" || { echo "the probe did not finish; output: ${1:0:200}"; return 1; }; }

verify_pair() { # from_label from_ip to_label to_ip
    local output
    output=$(probe_from "$2" "$4" "$GUEST_PORTS" -Ping)
    check "$1 -> $3: the probe ran to the end" probe_completed "$output"
    check "$1 cannot reach $3 on the CAPE agent (tcp/8000)" expect_reach "$output" tcp/8000 no
    check "$1 cannot reach $3 on SMB (tcp/445)" expect_reach "$output" tcp/445 no
    check "$1 cannot ping $3" expect_reach "$output" icmp no
}

verify_gateway() { # label ip
    local output
    output=$(probe_from "$2" "$GATEWAY_IP" "$GATEWAY_PORTS")
    check "$1 -> gateway: the probe ran to the end" probe_completed "$output"
    check "$1 reaches ResultServer ($GATEWAY_IP:2042)" expect_reach "$output" tcp/2042 yes
    check "$1 reaches INetSim ($GATEWAY_IP:80)" expect_reach "$output" tcp/80 yes
}

main() {
    local a=$1 b=$2 a_ip b_ip
    trap cleanup EXIT
    compose up -d --wait cape >/dev/null 2>&1 || { fail "setup: cape unhealthy"; exit 1; }
    export CAPE_API_TOKEN=${CAPE_API_TOKEN:-$(in_cape printenv CAPE_API_TOKEN)}
    gateway_address
    a_ip=$(guest_address "$a")
    b_ip=$(guest_address "$b")
    [[ -n $a_ip && -n $b_ip ]] || { fail "setup: CAPE does not list both '$a' and '$b' (ready guests?)"; exit 1; }

    # Recorded here, not inside start_guest: `check` runs it in a subshell, where STARTED would be lost.
    is_running "$a" || STARTED+=("$a")
    is_running "$b" || STARTED+=("$b")
    check "$a starts and its agent answers at $a_ip:8000" start_guest "$a" "$a_ip" || exit 1
    check "$b starts and its agent answers at $b_ip:8000" start_guest "$b" "$b_ip" || exit 1
    check "the probe is stored on $a and $b" store_probe_on "$a_ip" "$b_ip" || exit 1

    verify_pair "$a" "$a_ip" "$b" "$b_ip"
    verify_pair "$b" "$b_ip" "$a" "$a_ip"
    verify_gateway "$a" "$a_ip"
    verify_gateway "$b" "$b_ip"
}

[[ $# -eq 2 && $1 != "$2" ]] || { echo "usage: verify-isolation.sh GUEST_A GUEST_B   (two different ready guests)" >&2; exit 2; }
main "$1" "$2"

exit "$failed"
