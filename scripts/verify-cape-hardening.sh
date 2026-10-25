#!/usr/bin/env bash
# Proves, against the running cape container, what docs/plans/m11-notes/G2-notes.md fixed:
# the `cape` user cannot open the host's block devices or run anything as root, no program holds a secret it
# does not read, CAPE's web process serves the REST API only, and root-run code is not writable by `cape`.
#
#   scripts/verify-cape-hardening.sh        (needs the stack up; starts no guest)
# Exit 0 when all hold, 1 otherwise.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

failed=0
ok() { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }

check() {
    local description=$1 detail
    shift
    if detail=$("$@" 2>&1); then ok "$description"; else fail "$description${detail:+ ($(tr '\n' ';' <<<"$detail"))}"; fi
}

in_cape() { docker compose exec -T cape "$@"; }

cape_cannot_open_a_host_block_device() {
    local device
    for device in $(in_cape sh -c 'ls /dev/nvme*n*p* /dev/sd[a-z] /dev/vd[a-z] 2>/dev/null' || true); do
        in_cape runuser -u cape -- sh -c "test -r $device || test -w $device" && { echo "cape opens $device"; return 1; }
    done
    return 0
}

cape_has_no_sudo_rule() {
    local rules
    rules=$(in_cape sh -c 'cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v "^#" | grep -i cape' || true)
    [[ -z $rules ]] || { echo "$rules"; return 1; }
}

tcpdump_has_file_capabilities_and_no_world_access() {
    in_cape getcap /usr/bin/tcpdump | grep -q 'cap_net_admin,cap_net_raw=eip' &&
        [[ $(in_cape stat -c %a /usr/bin/tcpdump) == 750 ]]
}

secrets_by_program() {
    local listing
    listing=$(in_cape sh -c 'for pid in $(ls /proc | grep -E "^[0-9]+$"); do
        [ -r /proc/$pid/environ ] || continue
        names=$(tr "\0" "\n" </proc/$pid/environ 2>/dev/null | grep -oE "^(CAPE_API_TOKEN|CAPE_DB_PASSWORD|GUEST_CONTROL_TOKEN)" | sort | tr "\n" " ")
        [ -n "$names" ] && echo "$(tr "\0" " " </proc/$pid/cmdline | cut -c1-90)|$names"
    done' | grep -v 'supervisord\|sh -c\|^ *|')
    # supervisord itself (pid 1, root) holds all three; every other process may hold only its program's.
    local line bad=0
    while IFS='|' read -r command names; do
        case $command in
            *guest-control*) [[ $names == "CAPE_API_TOKEN GUEST_CONTROL_TOKEN " ]] || bad=1 ;;
            *cuckoo.py*) [[ $names == "CAPE_DB_PASSWORD " ]] || bad=1 ;;
            '') ;;
            *) bad=1 ;;
        esac
        [[ $bad == 0 ]] || { echo "$command holds $names"; return 1; }
    done <<<"$listing"
}

web_serves_only_the_api() {
    local path code
    for path in / /submit/ /analysis/ /admin/ /accounts/login/; do
        code=$(in_cape curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:8000$path")
        [[ $code == 404 ]] || { echo "GET $path answers $code"; return 1; }
    done
    [[ $(in_cape curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/apiv2/cuckoo/status/) == 401 ]]
}

root_run_code_is_not_writable_by_cape() {
    in_cape sh -c 'cd /opt/CAPEv2/utils && ../.venv/bin/python - <<PY > /tmp/rooter-files
import os, sys
sys.path.insert(0, "/opt/CAPEv2")
import rooter
seen = set()
for module in list(sys.modules.values()):
    path = getattr(module, "__file__", None)
    if path and os.path.exists(path):
        seen |= {os.path.realpath(path), os.path.dirname(os.path.realpath(path))}
print("\n".join(sorted(seen)))
PY
        bad=0
        while read -r path; do
            runuser -u cape -- test -w "$path" && { echo "cape can write $path"; bad=1; }
        done </tmp/rooter-files
        rm -f /tmp/rooter-files
        exit $bad'
}

check "cape cannot open the host's block devices" cape_cannot_open_a_host_block_device
check "cape has no sudo rule" cape_has_no_sudo_rule
check "tcpdump has file capabilities and is closed to other users" tcpdump_has_file_capabilities_and_no_world_access
check "no program holds a secret it does not read" secrets_by_program
check "CAPE's web process serves the REST API only (404 elsewhere, 401 without a token)" web_serves_only_the_api
check "no file the rooter imports is writable by cape" root_run_code_is_not_writable_by_cape

exit "$failed"
