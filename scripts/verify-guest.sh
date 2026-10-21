#!/usr/bin/env bash
# Proves acceptance checks 8-12 of docs/plans/m0-cape-spike.md against the Windows guest that
# scripts/build-guest.sh produced and registered. Assumes the guest exists; it does not build it.
# Submits a benign sample (built here with mingw-w64) through apiv2, routes it to INetSim, and
# confirms capemon's live logs, the final report and the callback. Leaves the guest powered off.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO=$PWD

LABEL=${GUEST_LABEL:-win}
GUEST_IP="" GATEWAY_IP="" AGENT=""
CAPE_IMAGE=tartarus-cape:latest
CALLBACK=tt-callback
CALLBACK_PORT=8080
SAMPLE_SRC=$REPO/guest/profiles/windows/selftest/benign.c
SAMPLE_DIR=${TMPDIR:-/tmp}/tt-guest-verify
AGENT_TIMEOUT=${GUEST_AGENT_TIMEOUT:-300}
ANALYSIS_TIMEOUT=${GUEST_ANALYSIS_TIMEOUT:-900}
REGISTRATION_TIMEOUT=${GUEST_REGISTRATION_TIMEOUT:-180}

source "$REPO/scripts/lib/benign-sample.sh"

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

# The subnet the running container was started with, as scripts/verify-cape.sh reads it.
guest_addresses() {
    local subnet
    subnet=$(in_cape printenv GUEST_SUBNET 2>/dev/null)
    subnet=${subnet:-192.168.150.0/24}
    GUEST_IP=${subnet%.0/24}.10
    GATEWAY_IP=${subnet%.0/24}.1
    AGENT=http://$GUEST_IP:8000
}

wait_until() {
    local deadline=$((SECONDS + $1)); shift
    until "$@"; do ((SECONDS < deadline)) || return 1; sleep 5; done
}

# --- sample and callback listener -------------------------------------------

start_callback_listener() {
    docker rm -f "$CALLBACK" >/dev/null 2>&1
    docker run -d --name "$CALLBACK" --network tartarus-internal --entrypoint "" "$CAPE_IMAGE" \
        python3 -I -c '
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        print("CALLBACK " + body.decode("utf-8", "replace"), flush=True)
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(("0.0.0.0", '"$CALLBACK_PORT"'), H).serve_forever()
' >/dev/null
}

configure_callback() {
    in_cape sh -c "mkdir -p /opt/CAPEv2/custom/conf/reporting.conf.d &&
        printf '[callback]\nenabled = yes\nurl = http://%s:%s/callback\n' '$CALLBACK' '$CALLBACK_PORT' \
        > /opt/CAPEv2/custom/conf/reporting.conf.d/callback.conf"
    in_cape supervisorctl restart cape-processor >/dev/null
}

cleanup() {
    docker rm -f "$CALLBACK" >/dev/null 2>&1
    in_cape rm -f /opt/CAPEv2/custom/conf/reporting.conf.d/callback.conf >/dev/null 2>&1
    in_cape supervisorctl restart cape-processor >/dev/null 2>&1
    virsh_cape destroy "$LABEL" >/dev/null 2>&1
}

# --- checks -----------------------------------------------------------------

snapshot_exists() { virsh_cape snapshot-list "$LABEL" --name 2>/dev/null | grep -qx tartarus-clean; }

restore_snapshot_and_reach_agent() {
    virsh_cape snapshot-revert "$LABEL" tartarus-clean >/dev/null 2>&1 || { echo "snapshot-revert failed"; return 1; }
    local deadline=$((SECONDS + AGENT_TIMEOUT)) code
    until code=$(in_cape curl -s -o /dev/null -w '%{http_code}' -m 5 "$AGENT/" 2>/dev/null); [[ $code == 200 ]]; do
        ((SECONDS < deadline)) || { echo "agent did not answer at $GUEST_IP:8000"; return 1; }
        sleep 5
    done
    echo "agent answered HTTP 200 at $GUEST_IP:8000"
}

# Information only: what the guest reports about itself, and how each provisioning step ended,
# read through CAPE's own agent (/store, /execute, /retrieve) on the restored guest.
GUEST_FACTS=$REPO/guest/profiles/windows/selftest/guest-facts.ps1
GUEST_DESKTOP_APPS=$REPO/guest/profiles/windows/desktop-apps.ps1

agent_stdout() {
    python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("stdout") or "")
except ValueError: pass'
}

report_guest_facts() {
    compose cp "$GUEST_FACTS" cape:/tmp/guest-facts.ps1 >/dev/null 2>&1 || return 0
    compose cp "$GUEST_DESKTOP_APPS" cape:/tmp/desktop-apps.ps1 >/dev/null 2>&1 || return 0
    in_cape curl -s -m 20 -F filepath='C:\tartarus\guest-facts.ps1' -F file=@/tmp/guest-facts.ps1 "$AGENT/store" >/dev/null
    in_cape curl -s -m 20 -F filepath='C:\tartarus\desktop-apps.ps1' -F file=@/tmp/desktop-apps.ps1 "$AGENT/store" >/dev/null
    # The agent shlex-splits the command POSIX-style, which would eat backslashes in the path.
    in_cape curl -s -m 120 -F 'command=powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/tartarus/guest-facts.ps1' \
        "$AGENT/execute" | agent_stdout | tr -d '\r' | sed -n 's/^FACT /guest: /p' | while read -r line; do info "$line"; done
    in_cape curl -s -m 20 -F filepath='C:\tartarus\provision.log' "$AGENT/retrieve" | tr -d '\r' |
        grep -E 'STEP|  ok|FAILED' | sed 's/^[0-9-]* [0-9:]*  //' | while read -r line; do info "provision: $line"; done
}

machines_list_has_guest() {
    local body
    body=$(on_internal sh -c 'curl -s -m10 -H "Authorization: Token $CAPE_API_TOKEN" http://cape:8000/apiv2/machines/list/')
    grep -q "\"$LABEL\"" <<<"$body" || { echo "machines/list: ${body:0:200}"; return 1; }
}

resultserver_bound() {
    in_cape ss -Hltn "sport = :2042" | grep -qF "$GATEWAY_IP:2042" || { echo "nothing on $GATEWAY_IP:2042"; return 1; }
}

# submit_sample and follow_task run in the main shell, not under check: check captures output
# in a subshell, which would drop TASK_ID and what the polling observed.
TASK_ID="" SUBMIT_RESPONSE="" FINAL_STATUS="" LIVE_BSON_SEEN=no

submit_sample() {
    SUBMIT_RESPONSE=$(docker run --rm -i -e CAPE_API_TOKEN -v "$SAMPLE_DIR/benign.exe:/benign.exe:ro" \
        --network tartarus-internal --entrypoint "" "$CAPE_IMAGE" \
        sh -c 'curl -s -m30 -H "Authorization: Token $CAPE_API_TOKEN" \
            -F file=@/benign.exe -F machine='"$LABEL"' -F route=inetsim -F timeout=120 -F package=exe \
            http://cape:8000/apiv2/tasks/create/file/')
    TASK_ID=$(python3 -I -c 'import json,sys
d=json.load(sys.stdin).get("data",{})
print((d.get("task_ids") or [d.get("task_id")])[0] or "")' <<<"$SUBMIT_RESPONSE" 2>/dev/null)
}

task_was_accepted() {
    [[ $TASK_ID =~ ^[0-9]+$ ]] || { echo "submit response: ${SUBMIT_RESPONSE:0:200}"; return 1; }
    echo "task $TASK_ID"
}

task_status() {
    on_internal sh -c "curl -s -m10 -H \"Authorization: Token \$CAPE_API_TOKEN\" http://cape:8000/apiv2/tasks/status/$TASK_ID/" |
        python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("data",""))
except Exception: print("")'
}

bson_logs_present() { in_cape sh -c "ls /opt/CAPEv2/storage/analyses/$TASK_ID/logs/*.bson >/dev/null 2>&1"; }
report_present()     { in_cape sh -c "test -f /opt/CAPEv2/storage/analyses/$TASK_ID/reports/report.json"; }

# Polls the task until it is reported or fails, noting whether capemon's .bson logs exist while
# it is still 'running': that is what the backend's live collector will tail in M1.
follow_task() {
    local deadline=$((SECONDS + ANALYSIS_TIMEOUT))
    while ((SECONDS < deadline)); do
        FINAL_STATUS=$(task_status)
        [[ $FINAL_STATUS == running && $LIVE_BSON_SEEN == no ]] && bson_logs_present && LIVE_BSON_SEEN=yes
        case $FINAL_STATUS in reported | failed_*) return ;; esac
        sleep 3
    done
}

task_reported() {
    [[ $FINAL_STATUS == reported ]] || { echo "task $TASK_ID ended at '${FINAL_STATUS:-no status}'"; return 1; }
    echo "task $TASK_ID reached 'reported'"
}

live_bson_was_seen() { [[ $LIVE_BSON_SEEN == yes ]] || { echo "no .bson appeared in logs/ while running"; return 1; }; }

callback_was_received() {
    local hits
    hits=$(docker logs "$CALLBACK" 2>&1 | grep -c "CALLBACK")
    ((hits > 0)) || { echo "listener received no callback"; return 1; }
    echo "$(docker logs "$CALLBACK" 2>&1 | grep CALLBACK | tail -n1)"
}

inetsim_dns_in_report() {
    in_cape sh -c "grep -oiE 'tartarus-selftest\\.example|\"domain\"' /opt/CAPEv2/storage/analyses/$TASK_ID/reports/report.json | head -n1" |
        grep -qi tartarus-selftest || { echo "sample's DNS lookup not in the report"; return 1; }
}

# Check 12: recreate the container, volumes intact, and confirm the guest survived.
recreate_preserves_guest() {
    compose up -d --wait --force-recreate cape >/dev/null 2>&1 || { echo "cape did not come back healthy"; return 1; }
    virsh_cape dominfo "$LABEL" >/dev/null 2>&1 || { echo "domain gone"; return 1; }
    snapshot_exists || { echo "snapshot gone"; return 1; }
    wait_until "$REGISTRATION_TIMEOUT" machines_list_has_guest || { echo "registration gone from machines/list"; return 1; }
    echo "domain, tartarus-clean and registration all survived"
}

main() {
    trap cleanup EXIT
    compose up -d --wait postgres >/dev/null 2>&1 || { fail "setup: postgres unhealthy"; exit 1; }
    compose up -d --wait cape >/dev/null 2>&1 || { fail "setup: cape unhealthy"; exit 1; }
    export CAPE_API_TOKEN=${CAPE_API_TOKEN:-$(in_cape printenv CAPE_API_TOKEN)}
    guest_addresses

    virsh_cape dominfo "$LABEL" >/dev/null 2>&1 || { fail "no '$LABEL' domain; run scripts/build-guest.sh first"; exit 1; }

    check "9 snapshot: tartarus-clean exists" snapshot_exists
    check "9 registration: apiv2/machines/list shows $LABEL" machines_list_has_guest
    check "11 resultserver: listens on $GATEWAY_IP:2042 while a guest is registered" resultserver_bound
    check "8 guest: snapshot restores and the agent answers on $GUEST_IP:8000" restore_snapshot_and_reach_agent &&
        report_guest_facts
    virsh_cape destroy "$LABEL" >/dev/null 2>&1

    if build_sample; then
        ok "sample: benign.exe built with mingw-w64"
        start_callback_listener
        configure_callback
        submit_sample
        if check "10 submit: apiv2 accepted the sample" task_was_accepted; then
            follow_task
            check "10 analysis: the task runs to 'reported'" task_reported
            check "10 live: capemon .bson logs appeared in logs/ while running" live_bson_was_seen
            check "10 final: report.json exists after the run" report_present
            check "10 inetsim: the sample's name resolution is in the report" inetsim_dns_in_report
            check "10 callback: the reporting callback reached the internal listener" callback_was_received
        fi
    else
        fail "sample: could not build benign.exe with mingw-w64"
    fi

    check "12 persist: recreating the container keeps domain, snapshot and registration" recreate_preserves_guest
}

case "${1:-}" in
    "") main ;;
    *) echo "usage: verify-guest.sh   (no arguments; needs a guest built by build-guest.sh)" >&2; exit 2 ;;
esac

exit "$failed"
