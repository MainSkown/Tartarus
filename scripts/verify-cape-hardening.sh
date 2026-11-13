#!/usr/bin/env bash
# Proves, against the running cape container, what docs/history/m11-notes/G2-notes.md fixed:
# the `cape` user cannot open the host's block devices or run anything as root, no program holds a secret it
# does not read, CAPE's web process serves the REST API only, and root-run code is not writable by `cape`.
# It also proves libvirt's access policy (cape/libvirt/polkit): `cape` reads the registered guests but is
# refused every write, reverting, stopping and dumping a guest included; those three it gets from the
# root machine broker, which serves `cape` and root only and only for a registered guest. Calls that
# must be refused are made against throwaway names and undone as root should one be allowed.
# It also proves what the 2026-11-12 audit fixed: the container is not privileged, `cape` and
# `libvirt-qemu` open no device beyond a guest's, no program runs with a gid a host group could share,
# and `cape` connects to its database and nowhere else.
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

container_is_not_privileged() {
    local capabilities
    [[ $(docker inspect -f '{{.HostConfig.Privileged}}' "$(docker compose ps -q cape)") == false ]] || { echo "privileged"; return 1; }
    capabilities=$(in_cape awk '/^CapBnd/ {print $2}' /proc/1/status)
    # Bits 16 and 17: SYS_MODULE and SYS_RAWIO, the two that load code into or read the host kernel.
    (((0x$capabilities >> 16 & 3) == 0)) || { echo "the bounding set $capabilities holds SYS_MODULE or SYS_RAWIO"; return 1; }
    in_cape sh -c '! test -w /proc/sys/kernel/core_pattern' || { echo "kernel.core_pattern is writable"; return 1; }
}

# Opened for real, read-only and append, without reading or writing a byte: the device cgroup and the
# node's group both decide, and only an open asks both.
unprivileged_users_open_only_the_devices_they_need() {
    in_cape bash -c '
        opened=0
        for user in cape libvirt-qemu; do
            while read -r node; do
                case $node in
                    /dev/null | /dev/zero | /dev/full | /dev/random | /dev/urandom | /dev/tty | /dev/ptmx) continue ;;
                    /dev/kvm | /dev/net/tun | /dev/vhost-net) continue ;;
                esac
                if runuser -u "$user" -- bash -c ": <\"\$1\" || : >>\"\$1\"" _ "$node" 2>/dev/null; then
                    echo "$user opens $node"
                    opened=1
                fi
            done < <(find /dev -xdev \( -type c -o -type b \))
        done
        exit $opened'
}

# A device node keeps its host gid, so a program must not run with a gid a host group could share:
# the image keeps its groups at 64000 and above. The exceptions are the group of /dev/kvm itself and
# gid 0, which three INetSim services keep after dropping their uid and which is root's on both sides.
no_program_runs_with_a_gid_a_host_group_could_share() {
    in_cape sh -c '
        kvm_gid=$(stat -c %g /dev/kvm)
        bad=0
        for status in /proc/[0-9]*/status; do
            [ "$(awk "/^Uid:/ {print \$2}" "$status" 2>/dev/null)" = 0 ] && continue
            for gid in $(awk "/^Gid:/ {print \$2} /^Groups:/ {\$1=\"\"; print}" "$status" 2>/dev/null); do
                [ "$gid" -ge 64000 ] || [ "$gid" = "$kvm_gid" ] || [ "$gid" = 0 ] && continue
                echo "$(awk "/^Name:/ {print \$2}" "$status") runs with gid $gid"
                bad=1
            done
        done
        exit $bad'
}

cape_connects() { in_cape runuser -u cape -- timeout 5 bash -c ": </dev/tcp/$1/$2" 2>/dev/null; }

cape_reaches_only_its_database() {
    local host_gateway target
    host_gateway=$(in_cape sh -c "ip -4 route show default | awk '{print \$3; exit}'")
    cape_connects postgres 5432 || { echo "cape cannot reach its database"; return 1; }
    for target in "backend 8000" "$host_gateway 22" "$host_gateway 80" "1.1.1.1 443" "1.1.1.1 53"; do
        # shellcheck disable=SC2086  # host and port are two words on purpose
        ! cape_connects $target || { echo "cape reaches $target"; return 1; }
    done
}

PROBE_FILE=/tmp/tt-acl-probe.xml
PROBE_DOMAIN='<domain type="kvm"><name>tt-acl-probe</name><memory unit="MiB">16</memory><os><type arch="x86_64">hvm</type></os></domain>'
PROBE_NETWORK='<network><name>tt-acl-probe</name><bridge name="tt-acl0"/></network>'
PROBE_POOL_TARGET=/tmp/tt-acl-pool

root_virsh() { in_cape virsh -q -c qemu:///system "$@"; }
cape_virsh() { in_cape runuser -u cape -- virsh -q -c qemu:///system "$@"; }

first_registered_guest() { root_virsh list --all --name | awk 'NF {print; exit}'; }

# A succeeded call is undone (as root, with $cleanup) before the check fails.
refused_with_access_denied() {
    local cleanup=$1 output
    shift
    if output=$(cape_virsh "$@" 2>&1); then
        in_cape sh -c "$cleanup" >/dev/null 2>&1
        echo "cape was allowed: virsh $*"
        return 1
    fi
    [[ $output == *"access denied"* ]] || { echo "virsh $* failed, but not by the access policy: $output"; return 1; }
}

with_probe_file() {
    local xml=$1 status
    shift
    in_cape sh -c "cat >$PROBE_FILE && chmod 0644 $PROBE_FILE" <<<"$xml"
    "$@"
    status=$?
    in_cape rm -f "$PROBE_FILE"
    return "$status"
}

cape_sees_the_guests_root_sees() {
    [[ $(cape_virsh list --all --name | sort) == "$(root_virsh list --all --name | sort)" ]]
}

cape_can_read_a_registered_guest() {
    local guest
    guest=$(first_registered_guest)
    [[ -z $guest ]] || { cape_virsh domstate "$guest" && cape_virsh dumpxml "$guest" >/dev/null; }
}

cape_cannot_define_a_domain() {
    with_probe_file "$PROBE_DOMAIN" \
        refused_with_access_denied 'virsh -c qemu:///system undefine tt-acl-probe' define "$PROBE_FILE"
}

cape_cannot_undefine_or_edit_a_domain() {
    local status
    root_virsh define /dev/stdin <<<"$PROBE_DOMAIN" >/dev/null || return 1
    refused_with_access_denied 'true' undefine tt-acl-probe &&
        refused_with_access_denied 'true' desc tt-acl-probe --new-desc edited --config
    status=$?
    root_virsh undefine tt-acl-probe >/dev/null 2>&1
    return "$status"
}

cape_cannot_define_a_network() {
    with_probe_file "$PROBE_NETWORK" \
        refused_with_access_denied 'virsh -c qemu:///system net-undefine tt-acl-probe' net-define "$PROBE_FILE"
}

cape_cannot_make_a_storage_pool() {
    local pool_cleanup="virsh -c qemu:///system pool-destroy tt-acl-pool; virsh -c qemu:///system pool-undefine tt-acl-pool; rm -rf $PROBE_POOL_TARGET"
    refused_with_access_denied "$pool_cleanup" pool-define-as tt-acl-pool dir --target "$PROBE_POOL_TARGET" &&
        refused_with_access_denied "$pool_cleanup" pool-create-as tt-acl-pool dir --target "$PROBE_POOL_TARGET"
}

cape_cannot_list_networks_or_pools() {
    refused_with_access_denied 'true' net-list --all && refused_with_access_denied 'true' pool-list --all
}

check "cape cannot open the host's block devices" cape_cannot_open_a_host_block_device
check "the cape container is not privileged and cannot write kernel.* sysctls" container_is_not_privileged
check "cape and libvirt-qemu open no device beyond the ones a guest needs" unprivileged_users_open_only_the_devices_they_need
check "no unprivileged program runs with a gid a host group could share" no_program_runs_with_a_gid_a_host_group_could_share
check "cape opens connections to its database and nowhere else" cape_reaches_only_its_database
check "cape has no sudo rule" cape_has_no_sudo_rule
check "tcpdump has file capabilities and is closed to other users" tcpdump_has_file_capabilities_and_no_world_access
check "no program holds a secret it does not read" secrets_by_program
check "CAPE's web process serves the REST API only (404 elsewhere, 401 without a token)" web_serves_only_the_api
check "no file the rooter imports is writable by cape" root_run_code_is_not_writable_by_cape
cape_cannot_revert_stop_or_dump_a_guest_through_libvirt() {
    local guest
    guest=$(first_registered_guest)
    [[ -n $guest ]] || return 0
    refused_with_access_denied "virsh -c qemu:///system destroy $guest" snapshot-revert "$guest" tartarus-clean &&
        refused_with_access_denied 'true' destroy "$guest" &&
        refused_with_access_denied 'rm -f /tmp/tt-acl-dump' dump --memory-only "$guest" /tmp/tt-acl-dump
}

# Prints the broker's answer to `stop` of a guest that does not exist, asked as the given user.
ask_broker_as() {
    in_cape runuser -u "$1" -- python3 -I -c '
import sys
sys.path.insert(0, "/usr/local/lib/tartarus")
import machine_broker_client as broker
try:
    broker.ask(broker.STOP, "tt-no-such-guest", timeout=10)
    print("done")
except broker.MachineBrokerError as error:
    print(error)'
}

broker_serves_cape_only_for_a_registered_guest() {
    local answer
    answer=$(ask_broker_as cape)
    [[ $answer == *"not a registered guest"* ]] || { echo "the broker answered cape: $answer"; return 1; }
}

broker_turns_other_users_away() {
    local answer
    answer=$(ask_broker_as inetsim)
    [[ $answer == *"cannot be reached"* ]] || { echo "the broker answered inetsim: $answer"; return 1; }
}

check "libvirt shows cape the same guests it shows root" cape_sees_the_guests_root_sees
check "cape can read a registered guest's state and definition" cape_can_read_a_registered_guest
check "libvirt refuses cape defining a domain" cape_cannot_define_a_domain
check "libvirt refuses cape undefining or editing a domain" cape_cannot_undefine_or_edit_a_domain
check "libvirt refuses cape defining a network" cape_cannot_define_a_network
check "libvirt refuses cape making a storage pool" cape_cannot_make_a_storage_pool
check "libvirt refuses cape listing networks and storage pools" cape_cannot_list_networks_or_pools
check "libvirt refuses cape reverting, stopping and dumping a guest" cape_cannot_revert_stop_or_dump_a_guest_through_libvirt
check "the machine broker serves cape only for a registered guest" broker_serves_cape_only_for_a_registered_guest
check "the machine broker turns other users away" broker_turns_other_users_away

exit "$failed"
