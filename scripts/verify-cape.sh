#!/usr/bin/env bash
# Proves the M0a acceptance checks of docs/plans/m0-cape-spike.md against the real cape container,
# with a throwaway Cirros guest standing in for Windows. Starts postgres, (re)starts cape, and
# leaves cape stopped: check 7 compares the host before cape started with the host after it stopped.
# Check 8 (M6) proves the control service answers the backend and nobody else.
#
# `verify-cape.sh control` runs only the libvirt checks (1) and the control checks (8) against the
# running stack: no probe guest, cape is not stopped. It is the quick loop for the control service.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

CAPE_IMAGE=tartarus-cape:latest
PROBE=tt-probe
PROBE_DIR=/tmp/tt-probe
PROBE_MAC=52:54:00:7e:57:10
REGISTRATION_DIR=/var/lib/libvirt/tartarus/kvm.conf.d
REGISTRATION_STASH=/var/lib/libvirt/tartarus/kvm.conf.d.verify-cape
CIRROS_IMAGE=cirros-0.6.3-x86_64-disk.img
CIRROS_URL=https://github.com/cirros-dev/cirros/releases/download/0.6.3/$CIRROS_IMAGE
CIRROS_SHA256=${CIRROS_SHA256:-7d6355852aeb6dbcd191bcda7cd74f1536cfe5cbf8a10495a7283a8396e4b75b}
TIMEOUT=${VERIFY_TIMEOUT:-240}
PROC_MODULES=${VERIFY_PROC_MODULES:-/proc/modules}
HOST_PROCESS_PATTERN='qemu-system|libvirtd|virtlogd|inetsim|guacd|dnsmasq|suricata|supervisord|gunicorn'
CONTROL_NETWORK=tartarus-control
CONTROL_PORT=8002
# The registered guests' static addresses run from .10 to .99 (decision 5 of the M6 plan); the
# DHCP pool a cold-booting guest draws from starts above them.
FIRST_DHCP_HOST_NUMBER=100
# TEST-NET-3 and a public resolver: reaching INetSim through them proves the rooter's DNAT.
OUTSIDE_HTTP=203.0.113.10
OUTSIDE_DNS=8.8.8.8

failed=0
SCRATCH=""

ok() { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }
info() { printf '[INFO] %s\n' "$1"; }

check() {
    local description=$1 detail
    shift
    if detail=$("$@" 2>&1); then
        ok "$description"
    else
        detail=${detail//$'\n'/; }
        fail "$description${detail:+ ($detail)}"
        return 1
    fi
}

compose() { docker compose "$@"; }
in_cape() { compose exec -T cape "$@"; }
virsh_in_cape() { in_cape virsh -c qemu:///system "$@"; }
as_cape_user() { compose exec -T -u cape -w /opt/CAPEv2 cape "$@"; }
in_postgres() { compose exec -T postgres "$@"; }
on_internal_network() { docker run --rm -i -e CAPE_API_TOKEN --network tartarus-internal --entrypoint "" "$CAPE_IMAGE" "$@"; }
# Read-only: lists the host's rules from the host's network namespace.
in_host_network() { docker run --rm --network host --cap-add NET_ADMIN --entrypoint "" "$CAPE_IMAGE" "$@"; }

wait_until() {
    local deadline=$((SECONDS + TIMEOUT))
    until "$@"; do
        ((SECONDS < deadline)) || return 1
        sleep 2
    done
}

# Host state, for checks 4 and 7.

host_interfaces() { ip -br link | awk '{sub(/@.*/, "", $1); print $1}' | sort; }
host_interfaces_except_veth() { host_interfaces | grep -v '^veth' || true; }
host_firewall() {
    in_host_network sh -c 'nft list ruleset 2>/dev/null; iptables-legacy-save 2>/dev/null' |
        sed -E 's/counter packets [0-9]+ bytes [0-9]+//; s/\[[0-9]+:[0-9]+\]//; /^#/d'
}
host_processes() { pgrep -l "$HOST_PROCESS_PATTERN" | awk '{print $2}' | sort; }
host_modules() { awk '{print $1}' "$PROC_MODULES" | sort; }

take_baseline() {
    BASELINE_INTERFACES=$(host_interfaces)
    BASELINE_FIREWALL=$(host_firewall)
    BASELINE_PROCESSES=$(host_processes)
    BASELINE_MODULES=$(host_modules)
}

same_as() {
    local expected=$1 actual=$2
    [[ $expected == "$actual" ]] && return 0
    diff <(echo "$expected") <(echo "$actual") | grep '^[<>]' | head -n 5
    return 1
}

# The probe guest.

download_probe_image() {
    curl -fsSL --retry 3 -o "$SCRATCH/disk.qcow2" "$CIRROS_URL" || { echo "download failed"; return 1; }
    local actual
    actual=$(sha256sum "$SCRATCH/disk.qcow2" | cut -d' ' -f1)
    [[ $actual == "$CIRROS_SHA256" ]] || { echo "sha256 $actual, expected $CIRROS_SHA256"; return 1; }
}

write_probe_files() {
    cat >"$SCRATCH/domain.xml" <<EOF
<domain type='kvm'>
  <name>$PROBE</name>
  <memory unit='MiB'>256</memory>
  <vcpu>1</vcpu>
  <os><type arch='x86_64' machine='pc'>hvm</type><boot dev='hd'/></os>
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='$PROBE_DIR/disk.qcow2'/>
      <target dev='hda' bus='ide'/>
    </disk>
    <interface type='network'>
      <mac address='$PROBE_MAC'/>
      <source network='tt-guest'/>
      <model type='virtio'/>
    </interface>
    <serial type='pty'/>
    <console type='pty'/>
    <graphics type='vnc' autoport='yes' listen='127.0.0.1'/>
    <video><model type='vga'/></video>
  </devices>
</domain>
EOF
    cat >"$SCRATCH/$PROBE.conf" <<EOF
[kvm]
machines = $PROBE

[$PROBE]
label = $PROBE
platform = linux
ip = $PROBE_ADDRESS
arch = x64
interface = tt-guest
EOF
}

copy_probe_into_cape() {
    compose cp "$SCRATCH/." "cape:$PROBE_DIR" >/dev/null 2>&1 && in_cape chmod 755 "$PROBE_DIR"
}

define_probe() { virsh_in_cape define "$PROBE_DIR/domain.xml" >/dev/null; }

# CAPE's scheduler only starts once every registered machine is defined, and on start it powers
# off any registered machine that is running; so: define, register, let CAPE load it, then boot.
# Every registration file sets [kvm] machines and the last one read wins, so the probe can be the
# only registration: every other *.conf (a real guest's, or the control service's guests.conf) is
# set aside on the volume while the probe runs, and put back by cleanup_probe.
stash_other_registrations() {
    in_cape sh -c "mkdir -p '$REGISTRATION_STASH' &&
        find '$REGISTRATION_DIR' -maxdepth 1 -name '*.conf' ! -name '$PROBE.conf' -exec mv {} '$REGISTRATION_STASH/' \\;"
}

restore_other_registrations() {
    in_cape sh -c "[ -d '$REGISTRATION_STASH' ] || exit 0
        find '$REGISTRATION_STASH' -maxdepth 1 -name '*.conf' -exec mv {} '$REGISTRATION_DIR/' \\;
        rmdir '$REGISTRATION_STASH'"
}

register_probe() {
    stash_other_registrations &&
        in_cape cp "$PROBE_DIR/$PROBE.conf" "$REGISTRATION_DIR/$PROBE.conf" &&
        in_cape supervisorctl restart cape >/dev/null &&
        wait_until cape_database_lists_probe
}

# The probe has no static address, so it takes one from the DHCP pool; pinning its MAC to the
# pool's first address makes that address known before it boots, which the registration needs.
# Live only: tt-guest is a transient network.
probe_reservation() { echo "<host mac='$PROBE_MAC' ip='$PROBE_ADDRESS'/>"; }
reserve_probe_address() { virsh_in_cape net-update tt-guest add ip-dhcp-host "$(probe_reservation)" --live >/dev/null; }
release_probe_address() { virsh_in_cape net-update tt-guest delete ip-dhcp-host "$(probe_reservation)" --live >/dev/null 2>&1; }

boot_probe() { virsh_in_cape start "$PROBE" >/dev/null; }

# Cirros's published login; the probe only ever exists on the isolated bridge.
GUEST_REPORT_COMMAND="echo \"TT-PROBE \
ip=\$(ip -4 -o addr show eth0 | awk '{print \$4}') \
dns=\$(nslookup tartarus-probe.test $OUTSIDE_DNS 2>/dev/null | sed -n '/^Name:/,\$p' | grep -oE '([0-9]+\.){3}[0-9]+' | tail -n 1) \
disk=\$(cat /sys/block/sda/device/model) \
bios=\$(cat /sys/class/dmi/id/bios_vendor) \
acpi=\$(sudo head -c 24 /sys/firmware/acpi/tables/DSDT | tail -c 14 | tr -d '\\000') \
http=\$(wget -q -T 5 -O - http://$OUTSIDE_HTTP/ 2>/dev/null | tr -d '\r\n' | head -c 200)\""

SSH_CLIENT='import sys
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(sys.argv[1], username="cirros", password="gocubsgo", timeout=5, banner_timeout=5,
                   auth_timeout=5, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(sys.argv[2], timeout=40)
    print(stdout.read().decode(errors="replace"))
except Exception as error:
    print(f"ssh: {error}")'

latest_probe_report() {
    as_cape_user .venv/bin/python -c "$SSH_CLIENT" "$PROBE_ADDRESS" "$GUEST_REPORT_COMMAND" | tr -d '\r' | grep 'TT-PROBE ' | tail -n 1
}

capture_probe_report() {
    PROBE_REPORT=$(latest_probe_report)
    PROBE_IP="" PROBE_DNS="" PROBE_DISK="" PROBE_BIOS="" PROBE_ACPI="" PROBE_HTTP=""
    if [[ $PROBE_REPORT =~ ip=(.*)\ dns=(.*)\ disk=(.*)\ bios=(.*)\ acpi=(.*)\ http=(.*)$ ]]; then
        PROBE_IP=${BASH_REMATCH[1]} PROBE_DNS=${BASH_REMATCH[2]} PROBE_DISK=${BASH_REMATCH[3]}
        PROBE_BIOS=${BASH_REMATCH[4]} PROBE_ACPI=${BASH_REMATCH[5]} PROBE_HTTP=${BASH_REMATCH[6]}
    fi
    [[ -n $PROBE_REPORT ]]
}

probe_reached_inetsim() { capture_probe_report && [[ -n $PROBE_DNS && $PROBE_HTTP == *INetSim* ]]; }

ROOTER_CLIENT='import sys
from lib.cuckoo.core.rooter import rooter
print(rooter(*sys.argv[1:]))'

inetsim_route() {
    as_cape_user .venv/bin/python -c "$ROOTER_CLIENT" "inetsim_$1" "$PROBE_ADDRESS" "$GUEST_GATEWAY_IP" 53 2042 "" >/dev/null
}

cleanup_probe() {
    virsh_in_cape destroy "$PROBE" >/dev/null 2>&1
    release_probe_address
    virsh_in_cape undefine "$PROBE" >/dev/null 2>&1
    in_cape rm -rf "$PROBE_DIR" "$REGISTRATION_DIR/$PROBE.conf"
    in_postgres sh -c "psql -U \"\$CAPE_DB_USER\" -d \"\$CAPE_DB_NAME\" -qc \"delete from machines where label = '$PROBE'\"" >/dev/null 2>&1
    restore_other_registrations
    in_cape supervisorctl restart cape >/dev/null 2>&1
}

remove_scratch() { [[ -n $SCRATCH ]] && rm -rf "$SCRATCH"; }

# Check 1: libvirt.

all_running() {
    local status
    status=$(in_cape supervisorctl status "$@") || true
    for program in "$@"; do
        grep -qE "^$program +RUNNING" <<<"$status" || { grep -E "^$program " <<<"$status" || echo "$program not found"; return 1; }
    done
}

# libvirt's TCP endpoint has no authentication, and the container is privileged, so reaching it
# is host root. Nothing needs it until the guest wizard (M6), so it stays off: a compose-network
# neighbour must get a refused connection, not just a missing listener.
libvirt_tcp_has_no_listener() {
    local listeners
    listeners=$(in_cape ss -Hltn sport = :16509)
    [[ -z $listeners ]] || { echo "listening: $listeners"; return 1; }
}

libvirt_tcp_is_refused_from_another_container() {
    local output
    if output=$(on_internal_network virsh -c qemu+tcp://cape/system list --all 2>&1); then
        echo "another container can run virsh against libvirt"
        return 1
    fi
    # A failure for another reason (the name did not resolve, the image broke) proves nothing.
    grep -qi "refused" <<<"$output" || { echo "not a refusal: $output"; return 1; }
}

check_libvirt() {
    check "1 libvirt: virtlogd and libvirtd are running" all_running virtlogd libvirtd
    check "1 libvirt: virsh list works in the container" virsh_in_cape list --all
    check "1 libvirt: nothing listens on TCP 16509 inside the container" libvirt_tcp_has_no_listener
    check "1 libvirt: qemu+tcp://cape/system is refused from another container on tartarus-internal" \
        libvirt_tcp_is_refused_from_another_container
}

# Check 2: KVM.

capabilities_list_kvm() { virsh_in_cape capabilities | grep -q "domain type='kvm'" || { echo "no kvm domain type"; return 1; }; }

probe_boots_with_kvm() {
    virsh_in_cape dumpxml "$PROBE" | grep -q "domain type='kvm'" || { echo "not a kvm domain"; return 1; }
    [[ $(virsh_in_cape domstate "$PROBE") == running* ]] || { echo "not running"; return 1; }
    [[ -n $PROBE_REPORT ]] || { echo "no report from the guest over SSH"; return 1; }
}

guest_sees_no_emulator_strings() {
    local seen="disk='$PROBE_DISK' bios='$PROBE_BIOS' acpi='$PROBE_ACPI'"
    echo "$seen"
    [[ -n $PROBE_DISK && -n $PROBE_BIOS && -n ${PROBE_ACPI// /} ]] || return 1
    ! grep -qiE 'qemu|bochs|bxpc|seabios' <<<"$seen"
}

# Check 3: the guest bridge.

bridge_has_gateway() { in_cape ip -4 -br addr show dev tt-guest | grep -qF " $GUEST_GATEWAY_IP/24"; }
dhcp_pool_range() { virsh_in_cape net-dumpxml tt-guest | sed -n "s/.*<range start='\([0-9.]*\)' end='\([0-9.]*\)'.*/\1 \2/p"; }
dhcp_pool_is_above_the_static_addresses() {
    local start end
    read -r start end <<<"$(dhcp_pool_range)"
    [[ -n $start ]] || { echo "tt-guest has no DHCP range"; return 1; }
    ((${start##*.} >= FIRST_DHCP_HOST_NUMBER)) || { echo "the pool starts at $start"; return 1; }
}
bridge_absent_on_host() { ! ip link show tt-guest >/dev/null 2>&1; }
probe_has_guest_address() { [[ $PROBE_IP == "$PROBE_ADDRESS/24" ]] || { echo "guest reports '${PROBE_IP}'"; return 1; }; }

# Check 4: the rooter.

route_rules_present() { in_cape iptables-save -t nat | grep CAPE-rooter | grep -qF -- "-s $PROBE_ADDRESS/32"; }
route_rules_absent() { ! route_rules_present; }
# Docker adds its own per-container rules when cape starts, so the rooter is judged against the
# host as it was just before the route went up.
host_firewall_unchanged_by_route() { same_as "$BEFORE_ROUTE_FIREWALL" "$(host_firewall)"; }
host_firewall_unchanged() { same_as "$BASELINE_FIREWALL" "$(host_firewall)"; }
host_interfaces_unchanged_except_veth() {
    same_as "$(grep -v '^veth' <<<"$BASELINE_INTERFACES" || true)" "$(host_interfaces_except_veth)"
}

# Check 5: INetSim and guacd.

inetsim_answered_dns() { [[ $PROBE_DNS == "$GUEST_GATEWAY_IP" ]] || { echo "got '$PROBE_DNS'"; return 1; }; }
inetsim_answered_http() { [[ $PROBE_HTTP == *INetSim* ]] || { echo "got '${PROBE_HTTP:0:80}'"; return 1; }; }

GUACD_PROBE='import codecs, socket, sys, time

host, port, vnc_host, vnc_port = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]

def encode(*elements):
    return (",".join(f"{len(e)}.{e}" for e in elements) + ";").encode()

class Reader:
    def __init__(self, sock):
        self.sock, self.buffer, self.decoder = sock, "", codecs.getincrementaldecoder("utf-8")()

    def fill(self):
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError("guacd closed the connection")
        self.buffer += self.decoder.decode(data)

    def element(self):
        while "." not in self.buffer:
            self.fill()
        length, _ = self.buffer.split(".", 1)
        while len(self.buffer) < len(length) + 1 + int(length) + 1:
            self.fill()
        start = len(length) + 1
        value, terminator = self.buffer[start:start + int(length)], self.buffer[start + int(length)]
        self.buffer = self.buffer[start + int(length) + 1:]
        return value, terminator

    def instruction(self):
        elements = []
        while True:
            value, terminator = self.element()
            elements.append(value)
            if terminator == ";":
                return elements

def value_for(name):
    return {"hostname": vnc_host, "port": vnc_port}.get(name, name if name.startswith("VERSION_") else "")

try:
    sock = socket.create_connection((host, port), timeout=20)
    reader = Reader(sock)
    sock.sendall(encode("select", "vnc"))
    opcode, *names = reader.instruction()
    for instruction in (("size", "1024", "768", "96"), ("audio",), ("video",), ("image",)):
        sock.sendall(encode(*instruction))
    sock.sendall(encode("connect", *map(value_for, names)))
    deadline = time.time() + 20
    while time.time() < deadline:
        opcode, *args = reader.instruction()
        if opcode == "error":
            sys.exit(f"error: guacd said: {args}")
        if opcode == "size" and args[0] == "0":
            print(f"ok: guacd drew the VNC display (size {args[1]}x{args[2]})")
            sys.exit(0)
    sys.exit("error: no display within 20 s")
except (OSError, ValueError) as error:
    sys.exit(f"error: {error}")
'

guacd_draws_probe_display() {
    local display
    display=$(virsh_in_cape domdisplay "$PROBE")
    [[ $display =~ ^vnc://[^:]+:([0-9]+) ]] || { echo "no VNC display: $display"; return 1; }
    on_internal_network python3 -I - cape 4822 127.0.0.1 $((5900 + BASH_REMATCH[1])) <<<"$GUACD_PROBE"
}

# Check 6: CAPE.

api_status() { on_internal_network curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://cape:8000/apiv2/cuckoo/status/; }

api_refuses_without_token() {
    local code
    code=$(api_status)
    [[ $code == 401 || $code == 403 ]] || { echo "got HTTP $code"; return 1; }
}

api_answers_with_token() {
    local response code
    response=$(on_internal_network sh -c 'curl -s -o /tmp/body -w "%{http_code}\n" --max-time 10 \
        -H "Authorization: Token $CAPE_API_TOKEN" http://cape:8000/apiv2/cuckoo/status/; cat /tmp/body')
    code=$(head -n 1 <<<"$response")
    [[ $code == 200 && $response == *'"data"'* ]] || { echo "got HTTP $code: $(tail -n +2 <<<"$response" | head -c 200)"; return 1; }
}

cape_database_lists_probe() {
    in_postgres sh -c 'psql -U "$CAPE_DB_USER" -d "$CAPE_DB_NAME" -Atc "select label from machines"' | grep -qx "$PROBE"
}

MONGO_SETTINGS='from lib.cuckoo.common.config import Config
print("mongodb=%s web_reporting=%s" % (Config("reporting").mongodb.enabled, Config("web").web_reporting.enabled))'

no_mongo_anywhere() {
    local services settings processes
    services=$(compose config --format json | python3 -I -c 'import json, sys
print(" ".join(n for n, s in json.load(sys.stdin)["services"].items() if "mongo" in n + s.get("image", "")))')
    [[ -z $services ]] || { echo "compose has $services"; return 1; }
    settings=$(as_cape_user .venv/bin/python -c "$MONGO_SETTINGS")
    [[ $settings == "mongodb=False web_reporting=False" ]] || { echo "CAPE config: $settings"; return 1; }
    processes=$(in_cape sh -c 'pgrep -l mongod; ss -Htn dport = :27017')
    [[ -z $processes ]] || { echo "in cape: $processes"; return 1; }
}

# Check 8: the control service (guest-control) answers the backend and nobody else. An engine that
# is not installed yet answers 409, which proves the routing and the token as well as a 200.

CONTROL_CLIENT='import os, sys, urllib.error, urllib.request

token = {"with-token": os.environ["GUEST_CONTROL_TOKEN"], "wrong-token": "wrong"}.get(sys.argv[1])
request = urllib.request.Request(os.environ["GUEST_CONTROL_URL"] + "/guests")
if token:
    request.add_header("Authorization", "Bearer " + token)
try:
    print(urllib.request.urlopen(request, timeout=10).status)
except urllib.error.HTTPError as refused:
    print(refused.code)
except OSError as error:
    print(f"error: {error}")'

RESOLVER='import socket
print(" ".join(sorted({a[4][0] for a in socket.getaddrinfo("cape", None, socket.AF_INET)})))'

control_status() { compose exec -T backend python -c "$CONTROL_CLIENT" "$1"; }

backend_is_answered_with_the_token() {
    local status
    status=$(control_status with-token)
    [[ $status == 200 || $status == 409 ]] || { echo "got '$status'"; return 1; }
}

# 401 and nothing else: an unreachable service is not a refusal.
guest_control_refuses() {
    local status
    status=$(control_status "$1")
    [[ $status == 401 ]] || { echo "got '$status'"; return 1; }
}

address_of_cape_on() {
    docker inspect -f "{{(index .NetworkSettings.Networks \"$1\").IPAddress}}" "$(compose ps -q cape)"
}

only_cape_and_backend_are_on_the_control_network() {
    local members
    members=$(docker network inspect "$CONTROL_NETWORK" -f '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' | sort | xargs)
    [[ $members == "tartarus-backend tartarus-cape" ]] || { echo "members: ${members:-none}"; return 1; }
}

guest_control_listens_on_the_control_address_only() {
    local listening
    listening=$(in_cape ss -Hltn sport = ":$CONTROL_PORT" | awk '{print $4}' | sort | xargs)
    [[ $listening == "$(address_of_cape_on "$CONTROL_NETWORK"):$CONTROL_PORT" ]] || { echo "listening on: ${listening:-nothing}"; return 1; }
}

can_connect() { # service host port
    if [[ $1 == frontend ]]; then
        compose exec -T frontend nc -w 3 "$2" "$3" </dev/null >/dev/null 2>&1
    else
        compose exec -T "$1" timeout 3 bash -c 'exec 3<>/dev/tcp/$0/$1' "$2" "$3" </dev/null >/dev/null 2>&1
    fi
}

# A failed connection proves nothing if the probe cannot connect at all, so the same probe must
# first reach a port the service itself listens on.
cannot_connect_to_guest_control_from() {
    local service=$1 own_port=$2 control_address
    control_address=$(address_of_cape_on "$CONTROL_NETWORK")
    [[ -n $control_address ]] || { echo "cape has no address on $CONTROL_NETWORK"; return 1; }
    can_connect "$service" 127.0.0.1 "$own_port" || { echo "the probe in $service cannot connect to its own port $own_port"; return 1; }
    ! can_connect "$service" "$control_address" "$CONTROL_PORT" || { echo "$service reached $control_address:$CONTROL_PORT"; return 1; }
}

# The backend is on both networks; the name cape must keep meaning the internal address, where
# CAPE's API and guacd listen.
cape_resolves_to_the_internal_address_for_the_backend() {
    local resolved expected
    resolved=$(compose exec -T backend python -c "$RESOLVER")
    expected=$(address_of_cape_on tartarus-internal)
    [[ $resolved == "$expected" ]] || { echo "resolves to '$resolved', the internal address is $expected"; return 1; }
}

check_control() {
    check "8 control: the services probed from are running" compose up -d --wait backend frontend opensearch
    check "8 control: the backend gets an answer from guest-control with the token" backend_is_answered_with_the_token
    check "8 control: guest-control refuses a request without the token" guest_control_refuses without-token
    check "8 control: guest-control refuses a request with a wrong token" guest_control_refuses wrong-token
    check "8 control: only cape and backend are on $CONTROL_NETWORK" only_cape_and_backend_are_on_the_control_network
    check "8 control: guest-control listens on the control address only" guest_control_listens_on_the_control_address_only
    check "8 control: frontend cannot connect to guest-control" cannot_connect_to_guest_control_from frontend 80
    check "8 control: opensearch cannot connect to guest-control" cannot_connect_to_guest_control_from opensearch 9200
    check "8 control: postgres cannot connect to guest-control" cannot_connect_to_guest_control_from postgres 5432
    check "8 control: the name cape still resolves to the tartarus-internal address for the backend" \
        cape_resolves_to_the_internal_address_for_the_backend
}

# Check 7: teardown.

no_new_host_processes() { same_as "$BASELINE_PROCESSES" "$(host_processes)"; }
host_interfaces_unchanged() { same_as "$BASELINE_INTERFACES" "$(host_interfaces)"; }
container_cgroup_gone() {
    local leftovers
    leftovers=$(find /sys/fs/cgroup -maxdepth 4 -name "*${CAPE_CONTAINER_ID}*" 2>/dev/null)
    [[ -z $leftovers ]] || { echo "$leftovers"; return 1; }
}

report_new_modules() {
    local loaded
    loaded=$(comm -13 <(echo "$BASELINE_MODULES") <(host_modules) | tr '\n' ' ')
    [[ -z ${loaded// /} ]] || info "kernel modules the host loaded on demand while cape ran (they stay loaded): $loaded"
}

# Lifecycle.

guest_addresses() {
    local subnet pool_end
    subnet=$(in_cape printenv GUEST_SUBNET 2>/dev/null)
    subnet=${subnet:-192.168.150.0/24}
    GUEST_GATEWAY_IP=${subnet%.0/24}.1
    read -r PROBE_ADDRESS pool_end <<<"$(dhcp_pool_range)"
    [[ -n $PROBE_ADDRESS ]] || PROBE_ADDRESS=${subnet%.0/24}.$FIRST_DHCP_HOST_NUMBER
}

abort() {
    fail "$1"
    [[ -n $(compose ps --status running --services 2>/dev/null) ]] && cleanup_probe
    remove_scratch
    exit 1
}

main() {
    SCRATCH=$(mktemp -d)
    trap remove_scratch EXIT
    check "probe image: Cirros downloaded and its sha256 matches" download_probe_image || exit 1
    trap 'abort "interrupted"' INT TERM

    compose up -d --wait postgres >/dev/null 2>&1 || abort "setup: postgres did not become healthy"
    if compose ps --status running --services | grep -qx cape; then
        compose stop cape >/dev/null 2>&1
    fi
    take_baseline
    compose up -d --wait cape >/dev/null 2>&1 || abort "setup: cape did not become healthy (docker compose logs cape)"
    CAPE_CONTAINER_ID=$(compose ps -q cape)
    export CAPE_API_TOKEN=${CAPE_API_TOKEN:-$(in_cape printenv CAPE_API_TOKEN)}
    guest_addresses

    check_libvirt

    write_probe_files
    copy_probe_into_cape || abort "setup: could not copy the probe guest into cape"
    define_probe || abort "setup: libvirt rejected the probe guest's domain XML"
    register_probe || info "cape had not registered the probe guest in its database after ${TIMEOUT}s"
    reserve_probe_address || abort "setup: libvirt refused the probe guest's DHCP reservation"
    boot_probe || abort "setup: the probe guest did not start"
    wait_until capture_probe_report
    info "guest report before the route: $PROBE_REPORT"

    check "2 kvm: virsh capabilities lists the kvm domain type" capabilities_list_kvm
    check "2 kvm: the probe guest boots with KVM acceleration" probe_boots_with_kvm
    check "2 kvm: the guest sees no QEMU/Bochs/SeaBIOS strings in its disk, BIOS and ACPI ids" guest_sees_no_emulator_strings

    check "3 bridge: tt-guest has $GUEST_GATEWAY_IP/24 in the container" bridge_has_gateway
    check "3 bridge: tt-guest does not exist on the host" bridge_absent_on_host
    check "3 bridge: the guest got $PROBE_ADDRESS on tt-guest" probe_has_guest_address
    check "3 bridge: the DHCP pool lies above the static guest addresses" dhcp_pool_is_above_the_static_addresses

    BEFORE_ROUTE_FIREWALL=$(host_firewall)
    inetsim_route enable
    wait_until probe_reached_inetsim
    info "guest report with the inetsim route: $PROBE_REPORT"
    check "4 rooter: the inetsim route's rules appear in the container's nat table" route_rules_present
    check "4 rooter: the host's firewall rules are unchanged while the route is active" host_firewall_unchanged_by_route
    check "4 rooter: the host's interfaces are unchanged apart from the container's veth" host_interfaces_unchanged_except_veth

    check "5 inetsim: answers the guest's DNS query sent to $OUTSIDE_DNS" inetsim_answered_dns
    check "5 inetsim: answers the guest's HTTP request sent to $OUTSIDE_HTTP" inetsim_answered_http
    check "5 guacd: is running" all_running guacd
    check "5 guacd: draws the guest's VNC display for a client on tartarus-internal" guacd_draws_probe_display

    check "6 cape: cape, cape-processor and cape-web are running" all_running cape cape-processor cape-web
    check "6 cape: apiv2/cuckoo/status/ refuses a request without the token" api_refuses_without_token
    check "6 cape: apiv2/cuckoo/status/ answers with the token" api_answers_with_token
    check "6 cape: the cape Postgres database lists the registered guest" cape_database_lists_probe
    check "6 cape: no Mongo anywhere (compose, CAPE config, processes, connections)" no_mongo_anywhere

    check_control

    inetsim_route disable
    check "4 rooter: disabling the route removes its rules" route_rules_absent

    cleanup_probe
    compose stop cape >/dev/null 2>&1
    check "7 stop: no CAPE, libvirt or QEMU process is left on the host" no_new_host_processes
    check "7 stop: the host's interfaces match the pre-start baseline" host_interfaces_unchanged
    check "7 stop: the host's firewall rules match the pre-start baseline" host_firewall_unchanged
    check "7 stop: the container's cgroup is gone from the host" container_cgroup_gone
    report_new_modules
}

# The libvirt and control checks only, against the running stack.
control_only() {
    compose up -d --wait >/dev/null 2>&1 || { fail "setup: the stack did not become healthy (docker compose ps)"; exit 1; }
    check_libvirt
    check_control
}

case "${1:-}" in
    "") main ;;
    control) control_only ;;
    *) echo "usage: verify-cape.sh [control]   (without an argument: restarts the cape service and leaves it stopped)" >&2; exit 2 ;;
esac

exit "$failed"
