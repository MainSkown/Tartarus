#!/usr/bin/env bash
# Tests scripts/verify-cape.sh with `docker`, `curl`, `ip`, `pgrep`, `find` and `sleep` replaced by stubs on PATH.
# The docker stub answers each in-container command from a fixture file, and tracks the cape
# container's phase (stopped before the run, running, after the final stop) and whether the
# rooter route is active, so host-side fixtures can differ per phase.
set -uo pipefail

VERIFY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verify-cape.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0

fixture() { printf '%s\n' "$2" >"$STUB_DIR/f/$1"; }

install_stubs() {
    cat >"$STUB_DIR/bin/docker" <<'STUB'
#!/usr/bin/env bash
f="$STUB_DIR/f"
state() { cat "$STUB_DIR/state-$1" 2>/dev/null; }
set_state() { echo "$2" >"$STUB_DIR/state-$1"; }
show() { cat "$f/$1"; }
args="$*"
echo "$args" >>"$STUB_DIR/calls"
case "$args" in
    *"up -d --wait cape"*) set_state cape running ;;
    *"up -d --wait postgres"*) ;;
    *"stop cape"*) set_state cape after; cp "$STUB_DIR/modules.after" "$STUB_DIR/modules" ;;
    *"ps --status running --services"*) [[ $(state cape) == running ]] && echo cape ;;
    *"ps -q cape"*) echo 0123456789abcdef ;;
    *"config --format json"*) show compose-config ;;
    *"--network host"*) show "host-firewall.$(state cape)$(state route)" ;;
    *"--network tartarus-internal"*"qemu+tcp://cape/system"*) show virsh-tcp-list; [[ -e $f/virsh-tcp-connects ]] ;;
    *"--network tartarus-internal"*"4822"*) show guac ;;
    *"--network tartarus-internal"*"Authorization: Token"*)
        if [[ ${CAPE_API_TOKEN:-} == "${EXPECTED_TOKEN:-test-token}" ]]; then show api-with-token; else printf '401\n{}\n'; fi ;;
    *"--network tartarus-internal"*"cuckoo/status"*) show api-without-token ;;
    *"exec -T postgres"*) show postgres-machines ;;
    *"exec -T -u cape"*"inetsim_enable"*) set_state route .route; show rooter ;;
    *"exec -T -u cape"*"inetsim_disable"*) set_state route ""; show rooter ;;
    *"exec -T -u cape"*"mongodb"*) show cape-mongo-config ;;
    *"exec -T -u cape"*"paramiko"*) show guest-report ;;
    *"exec -T cape printenv CAPE_API_TOKEN"*) show container-token ;;
    *"exec -T cape supervisorctl status virtlogd libvirtd"*) show supervisor-libvirt ;;
    *"exec -T cape supervisorctl status guacd"*) show supervisor-guacd ;;
    *"exec -T cape supervisorctl status cape cape-processor cape-web"*) show supervisor-cape ;;
    *"exec -T cape virsh -c qemu:///system list --all"*) show virsh-list ;;
    *"exec -T cape virsh -c qemu:///system capabilities"*) show capabilities ;;
    *"exec -T cape virsh -c qemu:///system dumpxml tt-probe"*) show probe-xml ;;
    *"exec -T cape virsh -c qemu:///system domstate tt-probe"*) show probe-state ;;
    *"exec -T cape virsh -c qemu:///system domdisplay tt-probe"*) echo "vnc://127.0.0.1:0" ;;
    *"exec -T cape ss -Hltn sport = :16509"*) show libvirt-tcp-listeners ;;
    *"exec -T cape ip -4 -br addr show dev tt-guest"*) show tt-guest-addr ;;
    *"exec -T cape iptables-save -t nat"*) show "nat$(state route)" ;;
    *"exec -T cape sh -c"*"mongod"*) show mongo-processes ;;
    *"exec -T cape"* | *"cp "* | *"compose"*"up"* | *"rm "*) ;;
    *) echo "unstubbed docker call: $args" >&2; exit 99 ;;
esac
STUB
    cat >"$STUB_DIR/bin/curl" <<'STUB'
#!/usr/bin/env bash
while (($#)); do [[ $1 == -o ]] && printf 'cirros image' >"$2"; shift; done
STUB
    cat >"$STUB_DIR/bin/ip" <<'STUB'
#!/usr/bin/env bash
state=$(cat "$STUB_DIR/state-cape" 2>/dev/null)
case "$*" in
    "-br link") cat "$STUB_DIR/f/host-links.$state" ;;
    "link show tt-guest") [[ -e $STUB_DIR/f/host-has-tt-guest ]] ;;
    *) echo "unstubbed ip call: $*" >&2; exit 99 ;;
esac
STUB
    cat >"$STUB_DIR/bin/pgrep" <<'STUB'
#!/usr/bin/env bash
cat "$STUB_DIR/f/host-processes.$(cat "$STUB_DIR/state-cape" 2>/dev/null)"
STUB
    cat >"$STUB_DIR/bin/find" <<'STUB'
#!/usr/bin/env bash
[[ $(cat "$STUB_DIR/state-cape") == after ]] && cat "$STUB_DIR/f/host-cgroups.after" 2>/dev/null
exit 0
STUB
    printf '#!/usr/bin/env bash\nexit 0\n' >"$STUB_DIR/bin/sleep"
    chmod +x "$STUB_DIR"/bin/*
}

healthy_fixtures() {
    fixture compose-config '{"services":{"postgres":{"image":"postgres:16"},"cape":{"image":"tartarus-cape:latest"}}}'
    local phase
    for phase in stopped after; do
        fixture "host-links.$phase" $'lo UNKNOWN\neth0 UP\nbr-1234 UP'
        fixture "host-processes.$phase" '7 qemu-system-x86'
        fixture "host-firewall.$phase" 'table ip filter { chain DOCKER { } }'
    done
    fixture host-links.running $'lo UNKNOWN\neth0 UP\nbr-1234 UP\nveth12ab@if5 UP'
    fixture host-processes.running $'7 qemu-system-x86\n101 qemu-system-x86\n102 libvirtd'
    fixture host-firewall.running 'table ip filter { chain DOCKER { } }'
    fixture host-firewall.running.route 'table ip filter { chain DOCKER { } }'
    fixture supervisor-libvirt $'virtlogd RUNNING pid 10, uptime 0:01:00\nlibvirtd RUNNING pid 11, uptime 0:01:00'
    fixture virsh-list $' Id   Name       State\n------------------------\n 1    tt-probe   running'
    fixture virsh-tcp-list 'error: unable to connect to server at cape:16509: Connection refused'
    fixture libvirt-tcp-listeners ''
    fixture capabilities "<capabilities><guest><arch name='x86_64'><domain type='qemu'/><domain type='kvm'/></arch></guest></capabilities>"
    fixture probe-xml "<domain type='kvm' id='1'><name>tt-probe</name></domain>"
    fixture probe-state 'running'
    fixture guest-report $'login: \nTT-PROBE ip=192.168.150.10/24 dns=192.168.150.1 disk=SAMSUNG MZ76E120 bios=AMIBios acpi=ALASKA AMI http=<html><title>INetSim default HTML page</title>'
    fixture tt-guest-addr 'tt-guest UP 192.168.150.1/24'
    fixture rooter '{"output": null, "exception": null}'
    fixture nat '-A PREROUTING -s 10.0.0.1/32 -j DNAT --to-destination 172.30.0.1'
    fixture nat.route $'-A PREROUTING -s 192.168.150.10/32 -p udp -m udp --dport 53 -m comment --comment CAPE-rooter -j DNAT --to-destination 192.168.150.1:53'
    fixture supervisor-guacd 'guacd RUNNING pid 20, uptime 0:01:00'
    fixture guac 'ok: guacd drew the VNC display (size 720x400)'
    fixture supervisor-cape $'cape RUNNING pid 30, uptime 0:01:00\ncape-processor RUNNING pid 31, uptime 0:01:00\ncape-web RUNNING pid 32, uptime 0:01:00'
    fixture api-without-token '401'
    fixture api-with-token $'200\n{"error": [], "data": {"machines": {"total": 1}}}'
    fixture postgres-machines 'tt-probe'
    fixture cape-mongo-config 'mongodb=False web_reporting=False'
    fixture mongo-processes ''
    fixture container-token 'test-token'
    printf 'kvm 1 0 - Live 0x0\n' >"$STUB_DIR/modules"
    cp "$STUB_DIR/modules" "$STUB_DIR/modules.after"
}

new_sandbox() {
    STUB_DIR="$(mktemp -d -p "$WORK_DIR")"
    export STUB_DIR
    mkdir "$STUB_DIR/bin" "$STUB_DIR/f"
    echo stopped >"$STUB_DIR/state-cape"
    install_stubs
    healthy_fixtures
}

run_verify() {
    OUTPUT="$(PATH="$STUB_DIR/bin:$PATH" VERIFY_PROC_MODULES="$STUB_DIR/modules" VERIFY_TIMEOUT=1 \
        CIRROS_SHA256="${CIRROS_SHA256:-$(printf 'cirros image' | sha256sum | cut -d' ' -f1)}" \
        CAPE_API_TOKEN="${TEST_TOKEN-test-token}" bash "$VERIFY" "$@" 2>&1)"
    STATUS=$?
}

expect_pass() {
    if [[ $STATUS -ne 0 || $OUTPUT == *"[FAIL]"* ]]; then
        echo "  expected success, got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

expect_fail_mentioning() {
    if [[ $STATUS -eq 0 || $OUTPUT != *"[FAIL] $1"* ]]; then
        echo "  expected a [FAIL] line starting '$1', got status $STATUS"; echo "$OUTPUT" | sed 's/^/    /'; return 1
    fi
}

expect_ok_lines_for_every_check() {
    local number
    for number in 1 2 3 4 5 6 7; do
        [[ $OUTPUT == *"[ OK ] $number "* ]] || { echo "  no [ OK ] line for check $number"; echo "$OUTPUT" | sed 's/^/    /'; return 1; }
    done
}

run_test() {
    local name=$1
    new_sandbox
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_passes_when_every_check_holds() {
    run_verify
    expect_pass && expect_ok_lines_for_every_check
}

test_leaves_cape_stopped_and_cleans_up_the_probe() {
    run_verify
    [[ $(cat "$STUB_DIR/state-cape") == after ]] || { echo "  cape left running"; return 1; }
    grep -q "undefine" "$STUB_DIR/calls" || { echo "  probe domain never undefined"; return 1; }
    grep -q "inetsim_disable" "$STUB_DIR/calls" || { echo "  route never disabled"; return 1; }
}

test_does_not_need_the_cape_compose_profile() {
    run_verify
    ! grep -q -- '--profile' "$STUB_DIR/calls" || { echo "  still passes --profile"; return 1; }
}

test_rejects_a_checksum_mismatch_before_touching_docker() {
    CIRROS_SHA256=0000 run_verify
    expect_fail_mentioning "probe image" && ! grep -qs "up -d" "$STUB_DIR/calls"
}

test_check1_fails_when_libvirtd_is_down() {
    fixture supervisor-libvirt $'virtlogd RUNNING pid 10, uptime 0:01:00\nlibvirtd FATAL Exited too quickly'
    run_verify
    expect_fail_mentioning "1 libvirt: virtlogd and libvirtd are running"
}

test_check1_fails_when_libvirt_listens_on_tcp() {
    fixture libvirt-tcp-listeners 'LISTEN 0 50 172.30.0.5:16509 0.0.0.0:*'
    run_verify
    expect_fail_mentioning "1 libvirt: nothing listens on TCP 16509"
}

test_check1_fails_when_another_container_can_reach_libvirt() {
    fixture virsh-tcp-list "$(cat "$STUB_DIR/f/virsh-list")"
    touch "$STUB_DIR/f/virsh-tcp-connects"
    run_verify
    expect_fail_mentioning "1 libvirt: qemu+tcp://cape/system is refused"
}

test_check1_does_not_count_a_dns_failure_as_a_refused_connection() {
    fixture virsh-tcp-list 'error: Failed to connect socket to cape: Name or service not known'
    run_verify
    expect_fail_mentioning "1 libvirt: qemu+tcp://cape/system is refused"
}

test_check2_fails_without_kvm_in_capabilities() {
    fixture capabilities "<capabilities><guest><arch name='x86_64'><domain type='qemu'/></arch></guest></capabilities>"
    run_verify
    expect_fail_mentioning "2 kvm: virsh capabilities lists the kvm domain type"
}

test_check2_fails_when_the_guest_never_boots() {
    fixture guest-report 'ssh: [Errno 113] No route to host'
    run_verify
    expect_fail_mentioning "2 kvm: the probe guest boots with KVM acceleration"
}

test_check2_fails_when_the_guest_sees_qemu_strings() {
    fixture guest-report 'TT-PROBE ip=192.168.150.10/24 dns=192.168.150.1 disk=QEMU HARDDISK bios=SeaBIOS acpi=BOCHS BXPC http=INetSim'
    run_verify
    expect_fail_mentioning "2 kvm: the guest sees no QEMU/Bochs/SeaBIOS strings"
}

test_check2_string_check_fails_without_a_guest_report() {
    fixture guest-report 'ssh: [Errno 113] No route to host'
    run_verify
    expect_fail_mentioning "2 kvm: the guest sees no QEMU/Bochs/SeaBIOS strings"
}

test_starts_the_probe_only_after_cape_registered_it() {
    run_verify
    local define register start
    define=$(grep -n 'define /tmp/tt-probe/domain.xml' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    register=$(grep -n 'exec -T postgres' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    start=$(grep -n 'start tt-probe' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    ((define < register && register < start)) || { echo "  define@$define register@$register start@$start"; return 1; }
}

# Each registration sets [kvm] machines, so a registered Windows guest would hide the probe.
test_sets_other_registrations_aside_while_the_probe_is_registered_and_restores_them() {
    run_verify
    local stash register restore cleanup
    stash=$(grep -n 'kvm.conf.d.verify-cape' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    register=$(grep -n 'cp /tmp/tt-probe/tt-probe.conf' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    cleanup=$(grep -n 'undefine tt-probe' "$STUB_DIR/calls" | head -n 1 | cut -d: -f1)
    restore=$(grep -n 'kvm.conf.d.verify-cape' "$STUB_DIR/calls" | tail -n 1 | cut -d: -f1)
    [[ -n $stash && -n $register && -n $cleanup && -n $restore ]] && ((stash < register && cleanup < restore)) ||
        { echo "  stash@$stash register@$register cleanup@$cleanup restore@$restore"; return 1; }
}

test_check3_fails_when_the_bridge_is_on_the_host() {
    : >"$STUB_DIR/f/host-has-tt-guest"
    run_verify
    expect_fail_mentioning "3 bridge: tt-guest does not exist on the host"
}

test_check3_fails_when_the_guest_has_no_address() {
    fixture guest-report 'TT-PROBE ip= dns= disk=SAMSUNG MZ76E120 bios=AMIBios acpi=ALASKA AMI http='
    run_verify
    expect_fail_mentioning "3 bridge: the guest got 192.168.150.10"
}

test_check4_fails_when_the_rooter_adds_no_rules() {
    fixture nat.route '-A PREROUTING -s 10.0.0.1/32 -j DNAT --to-destination 172.30.0.1'
    run_verify
    expect_fail_mentioning "4 rooter: the inetsim route's rules appear in the container's nat table"
}

test_check4_fails_when_the_host_firewall_changes() {
    fixture host-firewall.running.route 'table ip nat { chain PREROUTING { ip saddr 192.168.150.10 dnat to 192.168.150.1 } }'
    run_verify
    expect_fail_mentioning "4 rooter: the host's firewall rules are unchanged"
}

test_check4_ignores_rules_docker_adds_when_cape_starts() {
    fixture host-firewall.running 'table ip filter { chain DOCKER { } } table ip raw { ip daddr 172.30.0.5 drop }'
    fixture host-firewall.running.route "$(cat "$STUB_DIR/f/host-firewall.running")"
    run_verify
    expect_pass
}

test_check4_fails_when_disabling_leaves_rules() {
    fixture nat "$(cat "$STUB_DIR/f/nat.route")"
    run_verify
    expect_fail_mentioning "4 rooter: disabling the route removes its rules"
}

test_check5_fails_when_inetsim_does_not_answer_dns() {
    fixture guest-report 'TT-PROBE ip=192.168.150.10/24 dns= disk=SAMSUNG MZ76E120 bios=AMIBios acpi=ALASKA AMI http=<title>INetSim default HTML page</title>'
    run_verify
    expect_fail_mentioning "5 inetsim: answers the guest's DNS query"
}

test_check5_fails_when_inetsim_does_not_answer_http() {
    fixture guest-report 'TT-PROBE ip=192.168.150.10/24 dns=192.168.150.1 disk=SAMSUNG MZ76E120 bios=AMIBios acpi=ALASKA AMI http='
    run_verify
    expect_fail_mentioning "5 inetsim: answers the guest's HTTP request"
}

test_check5_fails_when_guacd_cannot_reach_vnc() {
    fixture guac 'error: guacd said: 3.519,Aborted. See logs.'
    sed -i 's|show guac ;;|show guac; exit 1 ;;|' "$STUB_DIR/bin/docker"
    run_verify
    expect_fail_mentioning "5 guacd: draws the guest's VNC display"
}

test_check6_reads_the_api_token_from_the_container_when_unset() {
    fixture container-token 'from-container'
    TEST_TOKEN="" EXPECTED_TOKEN=from-container run_verify
    expect_pass
}

test_check6_fails_when_a_cape_service_is_down() {
    fixture supervisor-cape $'cape RUNNING pid 30, uptime 0:01:00\ncape-processor BACKOFF Exited too quickly\ncape-web RUNNING pid 32, uptime 0:01:00'
    run_verify
    expect_fail_mentioning "6 cape: cape, cape-processor and cape-web are running"
}

test_check6_fails_when_the_api_answers_without_a_token() {
    fixture api-without-token '200'
    run_verify
    expect_fail_mentioning "6 cape: apiv2/cuckoo/status/ refuses a request without the token"
}

test_check6_fails_when_the_api_rejects_the_token() {
    fixture api-with-token $'401\n{"detail": "Invalid token."}'
    run_verify
    expect_fail_mentioning "6 cape: apiv2/cuckoo/status/ answers with the token"
}

test_check6_fails_when_the_guest_is_not_in_the_cape_database() {
    fixture postgres-machines ''
    run_verify
    expect_fail_mentioning "6 cape: the cape Postgres database lists the registered guest"
}

test_check6_fails_when_mongo_is_enabled() {
    fixture cape-mongo-config 'mongodb=True web_reporting=False'
    run_verify
    expect_fail_mentioning "6 cape: no Mongo anywhere"
}

test_check6_fails_when_compose_has_a_mongo_service() {
    fixture compose-config '{"services":{"mongo":{"image":"mongo:7"},"cape":{"image":"tartarus-cape:latest"}}}'
    run_verify
    expect_fail_mentioning "6 cape: no Mongo anywhere"
}

test_check7_fails_when_a_process_survives_the_stop() {
    fixture host-processes.after $'7 qemu-system-x86\n102 libvirtd'
    run_verify
    expect_fail_mentioning "7 stop: no CAPE, libvirt or QEMU process is left on the host"
}

test_check7_ignores_processes_that_predate_the_run() {
    run_verify
    expect_pass
}

test_check7_fails_when_an_interface_survives_the_stop() {
    fixture host-links.after $'lo UNKNOWN\neth0 UP\nbr-1234 UP\ntt-guest UP'
    run_verify
    expect_fail_mentioning "7 stop: the host's interfaces match the pre-start baseline"
}

test_check7_fails_when_a_firewall_rule_survives_the_stop() {
    fixture host-firewall.after 'table ip filter { chain DOCKER { } chain LIBVIRT_FWO { } }'
    run_verify
    expect_fail_mentioning "7 stop: the host's firewall rules match the pre-start baseline"
}

test_check7_fails_when_the_container_cgroup_survives_the_stop() {
    fixture host-cgroups.after '/sys/fs/cgroup/system.slice/docker-0123456789abcdef.scope/machine'
    run_verify
    expect_fail_mentioning "7 stop: the container's cgroup is gone from the host"
}

test_reports_kernel_modules_loaded_while_cape_ran() {
    printf 'kvm 1 0 - Live 0x0\ntun 1 0 - Live 0x0\n' >"$STUB_DIR/modules.after"
    run_verify
    [[ $OUTPUT == *"[INFO]"*"tun"* ]] || { echo "  no [INFO] line naming tun"; echo "$OUTPUT" | sed 's/^/    /'; return 1; }
}

test_unknown_argument_prints_usage_and_exits_2() {
    run_verify --bogus
    [[ $STATUS -eq 2 && $OUTPUT == *"usage"* ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
