#!/usr/bin/env bash
# Tests the generic guest build steps under guest/steps/ (preflight, fetch, define, snapshot,
# register) and guest-record. Each step runs for real against a scratch "host": stub virsh,
# qemu-img, curl, xorriso, df and sleep on PATH record their argv, and the context.json and
# guest.json come from the engine's own fixtures, so the steps see what the sequencer would give them.
# shellcheck disable=SC2001,SC2016  # sed indents the failure output; test stubs are written with single quotes on purpose
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEPS="$REPO/guest/steps"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
OUTPUT=""
STATUS=0

run_test() {
    local name=$1
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; echo "$OUTPUT" | sed 's/^/    | /'; return 1; }; }
assert_missing()  { [[ $OUTPUT != *"$1"* ]] || { echo "  expected output NOT to contain: $1"; return 1; }; }
assert_status()   { [[ $STATUS -eq $1 ]] || { echo "  expected exit $1, got $STATUS"; echo "$OUTPUT" | sed 's/^/    | /'; return 1; }; }
assert_logged()   { grep -qF -- "$1" "$LOG" || { echo "  expected a call containing: $1"; sed 's/^/    | /' "$LOG"; return 1; }; }
assert_not_logged() { ! grep -qF -- "$1" "$LOG" || { echo "  expected NO call containing: $1"; sed 's/^/    | /' "$LOG"; return 1; }; }

# Fails unless the first fragment is logged before the second.
assert_logged_before() {
    local first second
    first=$(grep -nF -- "$1" "$LOG" | head -n1 | cut -d: -f1)
    second=$(grep -nF -- "$2" "$LOG" | head -n1 | cut -d: -f1)
    [[ -n $first && -n $second && $first -lt $second ]] ||
        { echo "  expected '$1' before '$2'"; sed 's/^/    | /' "$LOG"; return 1; }
}

# --- a scratch host ------------------------------------------------------------------------

# Fills $WORLD with a registry, a profile dir, a context.json and the stub binaries.
# $1 = windows|ubuntu: which profile fixture the guest is built from.
new_world() {
    WORLD="$WORK/world.$RANDOM$RANDOM"
    mkdir -p "$WORLD"/{bin,state,libvirt/images,libvirt/nvram,libvirt/tartarus/cache,media,registry,profile,build}
    LOG="$WORLD/calls"
    : >"$LOG"
    install_stubs
    python3 -I - "$REPO" "$WORLD" "${1:-windows}" <<'PY'
import json, sys
from dataclasses import replace
from pathlib import Path

repo, world, profile_name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path[:0] = [str(repo / "cape"), str(repo / "cape" / "tests")]
from fixtures.guest_samples import make_guest
from fixtures.profile_samples import profile_data, sample_profile
from guest_engine.registry import MachineIdentity

profile = sample_profile(profile_name)
guest = make_guest("alpha", profile=profile_name, kind="build")
guest = replace(
    guest,
    machine=MachineIdentity("11111111-2222-3333-4444-555555555555", "00:14:22:ab:cd:ef", "7ABCDE1",
                            "/7ABCDE1/CN123456789012/", "S4EWNX0ABCDEF"),
)
view = profile.to_dict()
view.pop("adoption", None)
context = {
    "guest": guest.to_dict(),
    "profile": view,
    "source": None,
    "build": {"id": "b1", "kind": "build", "steps": ["preflight"]},
    "host": {
        "subnet": "192.168.150.0/24", "gateway": "192.168.150.1",
        "registry_root": str(world / "registry"), "libvirt_dir": str(world / "libvirt"),
        "media_dir": str(world / "media"), "registration_dir": str(world / "libvirt/tartarus/kvm.conf.d"),
        "libvirt_uri": "qemu:///system",
    },
}
(world / "context.json").write_text(json.dumps(context, indent=2))
(world / "registry" / "alpha").mkdir()
(world / "registry" / "alpha" / "guest.json").write_text(json.dumps(guest.to_dict(), indent=2))
PY
}


# --- stub binaries ---------------------------------------------------------------------------

install_stubs() {
    local bin=$WORLD/bin name
    cat >"$bin/virsh" <<'STUB'
#!/usr/bin/env bash
echo "virsh $*" >>"$STUB_LOG"
S=$STUB_DIR
shift 2
command=$1
shift
case $command in
    dominfo) [[ -e $S/domain ]] || { echo "error: failed to get domain '$1'" >&2; exit 1; }; echo "Name: $1" ;;
    domuuid) [[ -e $S/domain ]] || exit 1; cat "$S/uuid" ;;
    domstate) [[ -e $S/domain ]] || exit 1; [[ -e $S/running ]] && echo running || echo "shut off" ;;
    define) cp "$1" "$S/domain.xml"; touch "$S/domain"; echo "Domain defined" ;;
    start) touch "$S/running" ;;
    shutdown) [[ -e $S/ignore-acpi ]] || rm -f "$S/running" ;;
    destroy) rm -f "$S/running" ;;
    undefine) rm -f "$S/domain" "$S/domain.xml" ;;
    dumpxml) cat "$S/dumpxml-override" 2>/dev/null || cat "$S/domain.xml" ;;
    snapshot-list) cat "$S/snapshots" 2>/dev/null ;;
    snapshot-create-as) echo tartarus-clean >>"$S/snapshots" ;;
    *) echo "unexpected virsh $command" >&2; exit 1 ;;
esac
STUB
    cat >"$bin/qemu-img" <<'STUB'
#!/usr/bin/env bash
echo "qemu-img $*" >>"$STUB_LOG"
case $1 in
    create) touch "$4" ;;
    convert) touch "${@: -1}" ;;
esac
STUB
    cat >"$bin/curl" <<'STUB'
#!/usr/bin/env bash
echo "curl $*" >>"$STUB_LOG"
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
    case ${args[i]} in
        -w) cat "$STUB_DIR/agent-code" 2>/dev/null || echo 200; exit 0 ;;
        -o) target=${args[i + 1]} ;;
    esac
done
[[ -e $STUB_DIR/download-fails ]] && exit 22
source=$STUB_DIR/served/$(basename "${args[-1]}")
[[ -f $source ]] || exit 22
cp "$source" "$target"
STUB
    cat >"$bin/df" <<'STUB'
#!/usr/bin/env bash
echo "df $*" >>"$STUB_LOG"
echo Avail
cat "$STUB_DIR/free-mb" 2>/dev/null || echo 10000000
STUB
    cat >"$bin/sleep" <<'STUB'
#!/usr/bin/env bash
echo "sleep $*" >>"$STUB_LOG"
STUB
    for name in virsh qemu-img curl df sleep; do chmod +x "$bin/$name"; done
}

# Edits context.json: ctx_set <dotted.path> <json value>.
ctx_set() {
    python3 -I - "$WORLD/context.json" "$1" "$2" <<'PY'
import json, sys
path, dotted, raw = sys.argv[1:4]
data = json.load(open(path))
*parents, last = dotted.split(".")
target = data
for key in parents:
    target = target[key]
target[last] = json.loads(raw)
json.dump(data, open(path, "w"), indent=2)
PY
}

# Runs a step of guest/steps as the sequencer would: TT_* variables, stubs first on PATH.
run_step() {
    local step=$1
    shift
    OUTPUT="$(env -i PATH="$WORLD/bin:/usr/bin:/bin" HOME="$WORLD" \
        TT_GUEST_DIR="$WORLD/registry/alpha" TT_GUEST_JSON="$WORLD/registry/alpha/guest.json" \
        TT_PROFILE_DIR="$WORLD/profile" TT_BUILD_DIR="$WORLD/build" TT_CONTEXT_JSON="$WORLD/context.json" \
        TT_STATE_FILE="$WORLD/build/build.json" TT_STEP="$step" TT_BUILD_ID=b1 TT_LOG="$WORLD/build/log" \
        STUB_DIR="$WORLD/state" STUB_LOG="$LOG" "$@" "$STEPS/$step" 2>&1 </dev/null)"
    STATUS=$?
}

guest_json_field() {
    python3 -I - "$WORLD/registry/alpha/guest.json" "$1" <<'PY'
import json, sys
print(json.dumps(json.load(open(sys.argv[1]))[sys.argv[2]]))
PY
}

# --- guest-record -------------------------------------------------------------------------

record() {
    OUTPUT="$(env -i PATH=/usr/bin:/bin TT_GUEST_DIR="$WORLD/registry/alpha" "$STEPS/lib/guest-record" "$@" 2>&1 </dev/null)"
    STATUS=$?
}

test_guest_record_sets_an_allowed_field() {
    new_world
    record set disk_path '"/var/lib/libvirt/images/alpha.qcow2"'
    assert_status 0 &&
        [[ $(guest_json_field disk_path) == '"/var/lib/libvirt/images/alpha.qcow2"' ]] &&
        [[ $(stat -c %a "$WORLD/registry/alpha/guest.json") == 600 ]]
}

test_guest_record_sets_the_snapshot_name() {
    new_world
    record set snapshot '"tartarus-clean"'
    assert_status 0 && [[ $(guest_json_field snapshot) == '"tartarus-clean"' ]]
}

test_guest_record_refuses_a_field_outside_the_allow_list() {
    new_world
    local before; before=$(cat "$WORLD/registry/alpha/guest.json")
    record set state '"ready"'
    assert_status 2 && assert_contains "state" && [[ $(cat "$WORLD/registry/alpha/guest.json") == "$before" ]]
}

test_guest_record_refuses_the_secrets_and_the_identity() {
    new_world
    local field
    for field in identity machine ip name profile; do
        record set "$field" '"x"'
        assert_status 2 || return 1
    done
}

test_guest_record_refuses_a_value_that_is_not_json() {
    new_world
    record set disk_path not-json
    assert_status 2 && assert_contains "JSON"
}

test_guest_record_refuses_a_value_of_the_wrong_type() {
    new_world
    record set disk_path '5'
    assert_status 2 && assert_contains "disk_path"
}

test_guest_record_records_the_nvram_path_the_tpm_dir_and_the_display() {
    new_world
    record set nvram_path '"/var/lib/libvirt/nvram/alpha_VARS.fd"' &&
        record set tpm_dir '"/var/lib/libvirt/swtpm/alpha"' &&
        record set display '{"host": "127.0.0.1", "port": 5901}'
    assert_status 0 &&
        [[ $(guest_json_field nvram_path) == '"/var/lib/libvirt/nvram/alpha_VARS.fd"' ]] &&
        [[ $(guest_json_field tpm_dir) == '"/var/lib/libvirt/swtpm/alpha"' ]] &&
        [[ $(guest_json_field display) == '{"host": "127.0.0.1", "port": 5901}' ]]
}

test_guest_record_refuses_the_wrong_type_for_the_new_fields() {
    new_world
    local before; before=$(cat "$WORLD/registry/alpha/guest.json")
    record set display '"vnc://x"'
    assert_status 2 && assert_contains "display" && [[ $(cat "$WORLD/registry/alpha/guest.json") == "$before" ]]
}

test_guest_record_leaves_no_temporary_file_behind() {
    new_world
    record set snapshot '"tartarus-clean"'
    assert_status 0 && [[ -z $(find "$WORLD/registry/alpha" -name '*.tmp') ]]
}

test_guest_record_keeps_the_record_readable_by_the_engine() {
    new_world
    record set disk_path '"/x/alpha.qcow2"'
    python3 -I - "$REPO" "$WORLD/registry" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "cape"))
from guest_engine.registry import Registry
assert Registry(Path(sys.argv[2])).get("alpha").disk_path == "/x/alpha.qcow2"
PY
}

# --- preflight ----------------------------------------------------------------------------

# A host that passes every check; /dev/null stands in for a usable /dev/kvm (a character device).
preflight_ready_host() {
    new_world "${1:-windows}"
    printf 'flags\t\t: fpu vme vmx sse\n' >"$WORLD/cpuinfo"
    : >"$WORLD/media/Win11.iso"
    ctx_set guest.media.file '"Win11.iso"'
}

preflight() { run_step preflight TT_KVM_DEVICE=/dev/null TT_CPUINFO="$WORLD/cpuinfo" "$@"; }

test_preflight_passes_on_a_ready_host() {
    preflight_ready_host
    preflight
    assert_status 0 && assert_contains "STEP " && assert_contains "PROGRESS 100"
}

test_preflight_fails_without_dev_kvm() {
    preflight_ready_host
    preflight TT_KVM_DEVICE="$WORLD/no-such-device"
    assert_status 1 && assert_contains "$WORLD/no-such-device" && assert_contains "KVM"
}

test_preflight_fails_when_dev_kvm_is_not_a_device() {
    preflight_ready_host
    : >"$WORLD/not-a-device"
    preflight TT_KVM_DEVICE="$WORLD/not-a-device"
    assert_status 1 && assert_contains "not a usable"
}

test_preflight_fails_without_cpu_virtualization_flags() {
    preflight_ready_host
    printf 'flags\t\t: fpu vme sse\n' >"$WORLD/cpuinfo"
    preflight
    assert_status 1 && assert_contains "vmx" && assert_contains "svm"
}

test_preflight_accepts_amd_virtualization() {
    preflight_ready_host
    printf 'flags\t\t: fpu svm sse\n' >"$WORLD/cpuinfo"
    preflight
    assert_status 0
}

test_preflight_fails_on_too_little_free_space_and_shows_the_numbers() {
    preflight_ready_host
    echo 51200 >"$WORLD/state/free-mb"
    preflight
    assert_status 1 && assert_contains "120 GB" && assert_contains "disk 80" &&
        assert_contains "scratch 20" && assert_contains "reserve 20" && assert_contains "50 GB"
}

test_preflight_scratch_defaults_to_nothing_when_the_profile_has_none() {
    preflight_ready_host
    ctx_set profile.resources.scratch_gb 0
    echo 102400 >"$WORLD/state/free-mb"
    preflight
    assert_status 0
}

# A restart after a failed build must not fail on the disk that build left behind.
test_preflight_counts_the_guests_own_earlier_disk_as_free() {
    preflight_ready_host
    echo $((120 * 1024 - 10)) >"$WORLD/state/free-mb"
    preflight
    assert_status 1 || return 1
    dd if=/dev/urandom of="$WORLD/libvirt/images/alpha.qcow2" bs=1M count=20 status=none
    preflight
    assert_status 0
}

test_preflight_fails_when_the_installation_media_is_missing() {
    preflight_ready_host
    rm "$WORLD/media/Win11.iso"
    preflight
    assert_status 1 && assert_contains "Win11.iso"
}

test_preflight_does_not_need_media_for_a_clone() {
    preflight_ready_host
    rm "$WORLD/media/Win11.iso"
    ctx_set build.kind '"clone"'
    preflight
    assert_status 0
}

test_preflight_refuses_a_domain_of_the_same_name_that_is_not_this_guests() {
    preflight_ready_host
    touch "$WORLD/state/domain"
    echo 99999999-0000-0000-0000-000000000000 >"$WORLD/state/uuid"
    preflight
    assert_status 1 && assert_contains "alpha" && assert_not_logged "undefine" && assert_not_logged "destroy"
}

test_preflight_removes_the_leftover_domain_of_this_guest() {
    preflight_ready_host
    touch "$WORLD/state/domain" "$WORLD/state/running"
    echo 11111111-2222-3333-4444-555555555555 >"$WORLD/state/uuid"
    preflight
    assert_status 0 && assert_logged_before "destroy alpha" "undefine alpha" &&
        assert_logged "undefine alpha --nvram --tpm --snapshots-metadata"
}

test_preflight_leaves_no_domain_alone_when_there_is_none() {
    preflight_ready_host
    preflight
    assert_status 0 && assert_not_logged "undefine"
}

test_preflight_fails_when_another_guest_holds_the_address() {
    preflight_ready_host
    mkdir "$WORLD/registry/beta"
    printf '{"name": "beta", "ip": "192.168.150.10"}' >"$WORLD/registry/beta/guest.json"
    preflight
    assert_status 1 && assert_contains "192.168.150.10" && assert_contains "beta"
}

test_preflight_ignores_other_guests_on_other_addresses() {
    preflight_ready_host
    mkdir "$WORLD/registry/beta"
    printf '{"name": "beta", "ip": "192.168.150.11"}' >"$WORLD/registry/beta/guest.json"
    preflight
    assert_status 0
}

test_preflight_reads_the_address_of_a_broken_record_too() {
    preflight_ready_host
    mkdir "$WORLD/registry/beta"
    printf '{"name": "beta", "ip": "192.168.150.10", "state": ' >"$WORLD/registry/beta/guest.json"
    preflight
    assert_status 1 && assert_contains "beta"
}

test_preflight_names_no_operating_system() {
    [[ -x $STEPS/preflight ]] && ! grep -qiE 'windows|defender|powershell|wiminfo' "$STEPS/preflight" "$STEPS/lib/common.sh"
}

# --- fetch --------------------------------------------------------------------------------

sha_of() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# A manifest of the given name/content pairs; each is also "served" as the download for its URL.
fetch_world() {
    new_world
    mkdir -p "$WORLD/state/served"
    local name content
    : >"$WORLD/profile/manifest.sha256"
    echo "# pinned downloads" >>"$WORLD/profile/manifest.sha256"
    while (($# >= 2)); do
        name=$1 content=$2
        shift 2
        printf '%s' "$content" >"$WORLD/state/served/$name"
        printf '%s  %s  https://example.test/dl/%s\n' "$(sha_of "$content")" "$name" "$name" >>"$WORLD/profile/manifest.sha256"
    done
}

cached() { echo "$WORLD/libvirt/tartarus/cache/$1"; }

test_fetch_with_no_manifest_has_nothing_to_do() {
    new_world
    run_step fetch
    assert_status 0 && assert_contains "nothing to fetch" && assert_not_logged "curl"
}

test_fetch_downloads_every_entry_into_the_cache_verified() {
    fetch_world one.bin first two.bin second
    run_step fetch
    assert_status 0 && assert_logged "https://example.test/dl/one.bin" && assert_logged "https://example.test/dl/two.bin" &&
        assert_logged "--retry 3" &&
        [[ $(cat "$(cached one.bin)") == first && $(cat "$(cached two.bin)") == second ]] &&
        assert_contains "PROGRESS 100"
}

test_fetch_uses_a_cached_file_whose_hash_matches() {
    fetch_world one.bin first two.bin second
    mkdir -p "$(dirname "$(cached one.bin)")"
    printf first >"$(cached one.bin)"
    run_step fetch
    assert_status 0 && assert_not_logged "dl/one.bin" && assert_logged "dl/two.bin"
}

test_fetch_never_trusts_a_cached_file_with_the_wrong_hash() {
    fetch_world one.bin first
    mkdir -p "$(dirname "$(cached one.bin)")"
    printf tampered >"$(cached one.bin)"
    run_step fetch
    assert_status 0 && assert_logged "dl/one.bin" && [[ $(cat "$(cached one.bin)") == first ]]
}

test_fetch_fails_on_a_download_that_does_not_match_its_hash() {
    fetch_world one.bin first
    printf substituted >"$WORLD/state/served/one.bin"
    run_step fetch
    assert_status 1 && assert_contains "sha256 mismatch for one.bin" && [[ ! -e $(cached one.bin) ]]
}

test_fetch_fails_when_the_download_fails() {
    fetch_world one.bin first
    touch "$WORLD/state/download-fails"
    run_step fetch
    assert_status 1 && assert_contains "https://example.test/dl/one.bin"
}

test_fetch_refuses_a_name_that_could_leave_the_cache() {
    fetch_world one.bin first
    printf '%s  ../escape  https://example.test/x\n' "$(sha_of x)" >>"$WORLD/profile/manifest.sha256"
    run_step fetch
    assert_status 1 && assert_contains "../escape" && assert_not_logged "dl/one.bin" && assert_not_logged "example.test/x"
}

test_fetch_refuses_a_url_that_is_not_http() {
    fetch_world one.bin first
    printf '%s  two.bin  file:///etc/passwd\n' "$(sha_of x)" >>"$WORLD/profile/manifest.sha256"
    run_step fetch
    assert_status 1 && assert_contains "file:///etc/passwd" && assert_not_logged "curl"
}

test_fetch_refuses_a_line_without_a_sha256() {
    fetch_world
    echo "deadbeef  one.bin  https://example.test/x" >>"$WORLD/profile/manifest.sha256"
    run_step fetch
    assert_status 1 && assert_contains "one.bin"
}

test_fetch_names_no_operating_system() {
    [[ -x $STEPS/fetch ]] && ! grep -qiE 'windows|defender|powershell|wiminfo' "$STEPS/fetch"
}

# --- define -------------------------------------------------------------------------------

DOMAIN_XML() { cat "$WORLD/state/domain.xml"; }

define_world() {
    new_world "${1:-windows}"
    : >"$WORLD/media/${2:-Win11.iso}"
    # The Linux fixture names a persona that is not installed; the default is the one that is.
    ctx_set profile.hardware.persona '"default"'
    ctx_set guest.media.file "\"${2:-Win11.iso}\""
    ctx_set guest.media_kind "\"$([[ ${2:-Win11.iso} == *.iso ]] && echo installer || echo disk_image)\""
}

domain_has() { DOMAIN_XML | grep -qF -- "$1" || { echo "  domain XML lacks: $1"; return 1; }; }
domain_lacks() { ! DOMAIN_XML | grep -qF -- "$1" || { echo "  domain XML has: $1"; return 1; }; }

test_define_creates_a_thin_disk_and_an_installer_domain() {
    define_world
    run_step define
    assert_status 0 &&
        assert_logged "qemu-img create -f qcow2 $WORLD/libvirt/images/alpha.qcow2 80G" &&
        assert_logged_before "qemu-img create" "virsh -c qemu:///system define" &&
        domain_has "<boot dev='cdrom'/>" && domain_has "<source file='$WORLD/media/Win11.iso'/>" &&
        domain_has "<source file='$WORLD/libvirt/images/alpha.qcow2'/>" &&
        python3 -I -c 'import sys, xml.dom.minidom; xml.dom.minidom.parse(sys.argv[1])' "$WORLD/state/domain.xml"
}

test_define_records_the_disk_in_the_guest_record() {
    define_world
    run_step define
    assert_status 0 && [[ $(guest_json_field disk_path) == "\"$WORLD/libvirt/images/alpha.qcow2\"" ]]
}

test_define_records_the_nvram_of_a_domain_that_has_one() {
    define_world
    run_step define
    assert_status 0 && domain_has "<nvram" &&
        [[ $(guest_json_field nvram_path) == "\"$WORLD/libvirt/nvram/alpha_VARS.fd\"" ]] &&
        [[ $(guest_json_field tpm_dir) == null ]]
}

test_define_records_no_nvram_for_a_bios_domain() {
    define_world ubuntu Ubuntu.iso
    ctx_set profile.hardware.boot '"bios"'
    ctx_set profile.hardware.secure_boot false
    ctx_set profile.hardware.tpm false
    ctx_set profile.hardware.disk_bus '"virtio"'
    ctx_set profile.hardware.nic_model '"virtio"'
    run_step define
    assert_status 0 && domain_lacks "<nvram" && [[ $(guest_json_field nvram_path) == null ]]
}

test_define_replaces_a_disk_and_nvram_left_by_an_earlier_attempt() {
    define_world
    echo stale >"$WORLD/libvirt/images/alpha.qcow2"
    echo stale >"$WORLD/libvirt/nvram/alpha_VARS.fd"
    run_step define
    assert_status 0 && [[ ! -e $WORLD/libvirt/nvram/alpha_VARS.fd ]] && [[ ! -s $WORLD/libvirt/images/alpha.qcow2 ]]
}

test_define_can_run_twice() {
    define_world
    run_step define
    run_step define
    assert_status 0
}

test_define_renders_the_windows_like_hardware_block() {
    define_world
    run_step define
    assert_status 0 && domain_has "secure='yes'" && domain_has "<tpm model='tpm-crb'>" &&
        domain_has "bus='sata'" && domain_has "<clock offset='localtime'>" && domain_has "<baseBoard>" &&
        domain_has "00:14:22:ab:cd:ef" && domain_has "7ABCDE1" && domain_has "S4EWNX0ABCDEF" &&
        domain_has "11111111-2222-3333-4444-555555555555"
}

test_define_renders_a_linux_like_hardware_block() {
    define_world ubuntu Ubuntu.iso
    ctx_set profile.hardware.boot '"bios"'
    ctx_set profile.hardware.secure_boot false
    ctx_set profile.hardware.disk_bus '"virtio"'
    ctx_set profile.hardware.nic_model '"virtio"'
    run_step define
    assert_status 0 && domain_lacks "<loader" && domain_lacks "<tpm" && domain_lacks "<smm" &&
        domain_has "<target dev='vda' bus='virtio'/>" && domain_has "<clock offset='utc'>"
}

test_define_refuses_hardware_it_has_no_fragment_for_and_creates_nothing() {
    define_world
    ctx_set profile.hardware.disk_bus '"ide"'
    run_step define
    assert_status 1 && assert_contains "ide" && assert_not_logged "define" && assert_not_logged "qemu-img create" &&
        [[ ! -e $WORLD/libvirt/images/alpha.qcow2 ]]
}

test_define_never_executes_a_hostile_guest_name() {
    define_world
    ctx_set guest.name '"a$(touch pwned-by-name)b"'
    pushd "$WORLD" >/dev/null || return 1
    run_step define
    popd >/dev/null || return 1
    [[ ! -e $WORLD/pwned-by-name ]] && domain_has 'a$(touch pwned-by-name)b'
}

test_define_converts_and_resizes_a_disk_image() {
    define_world ubuntu cloud.img
    run_step define
    assert_status 0 &&
        assert_logged "qemu-img convert -O qcow2 $WORLD/media/cloud.img $WORLD/libvirt/images/alpha.qcow2" &&
        assert_logged_before "qemu-img convert" "qemu-img resize $WORLD/libvirt/images/alpha.qcow2 80G" &&
        domain_has "<boot dev='hd'/>" && domain_lacks "<boot dev='cdrom'/>"
}

test_define_takes_the_media_kind_from_the_context_even_when_the_extension_says_otherwise() {
    define_world ubuntu cloud.img
    ctx_set guest.media_kind '"installer"'
    run_step define
    assert_status 0 && assert_logged "qemu-img create -f qcow2" && assert_not_logged "qemu-img convert" &&
        domain_has "<boot dev='cdrom'/>"
}

test_define_falls_back_to_the_extension_when_the_context_names_no_media_kind() {
    define_world ubuntu cloud.img
    ctx_set guest.media_kind null
    run_step define
    assert_status 0 && assert_logged "qemu-img convert -O qcow2" && assert_not_logged "qemu-img create"
}

test_define_for_a_clone_keeps_the_copied_disk_and_boots_from_it() {
    define_world
    ctx_set build.kind '"clone"'
    echo copied >"$WORLD/libvirt/images/alpha.qcow2"
    echo copied >"$WORLD/libvirt/nvram/alpha_VARS.fd"
    run_step define
    assert_status 0 && assert_not_logged "qemu-img" && [[ -s $WORLD/libvirt/nvram/alpha_VARS.fd ]] &&
        [[ $(cat "$WORLD/libvirt/images/alpha.qcow2") == copied ]] && domain_has "<boot dev='hd'/>"
}

test_define_for_a_clone_fails_when_the_copy_is_missing() {
    define_world
    ctx_set build.kind '"clone"'
    run_step define
    assert_status 1 && assert_contains "copy" && assert_not_logged "define"
}

test_define_names_no_operating_system() {
    [[ -x $STEPS/define ]] && ! grep -qiE 'windows|defender|powershell|wiminfo' "$STEPS/define"
}

test_the_domain_files_name_no_operating_system() {
    [[ -f $REPO/guest/domain/domain.xml.tpl ]] &&
        ! grep -riE 'windows|defender|powershell|wiminfo' "$REPO/guest/domain" "$REPO/guest/personas" "$STEPS/lib"
}

# --- snapshot -----------------------------------------------------------------------------

# A guest that finished installing: defined, running, in need of its clean snapshot.
snapshot_world() {
    define_world "$@"
    ctx_set profile.timeouts.shutdown_s 1
    ctx_set profile.timeouts.agent_s 1
    ctx_set profile.agent.pre_snapshot '[]'
    run_step define
    touch "$WORLD/state/running"
    : >"$LOG"
}

test_snapshot_shuts_down_redefines_boots_and_snapshots_in_order() {
    snapshot_world
    run_step snapshot
    assert_status 0 &&
        assert_logged_before "shutdown alpha" "define" &&
        assert_logged_before "define" "start alpha" &&
        assert_logged_before "start alpha" "http://192.168.150.10:8000/" &&
        assert_logged_before "http://192.168.150.10:8000/" "sleep 60" &&
        assert_logged_before "sleep 60" "snapshot-create-as" &&
        assert_logged_before "snapshot-create-as" "destroy alpha"
}

test_snapshot_never_destroys_before_the_snapshot_when_the_guest_shuts_down() {
    snapshot_world
    run_step snapshot
    assert_status 0 && assert_logged_before "snapshot-create-as" "destroy" && assert_missing "forcing"
}

test_snapshot_forces_power_off_only_after_the_acpi_shutdown_times_out() {
    snapshot_world
    touch "$WORLD/state/ignore-acpi"
    run_step snapshot
    assert_status 0 && assert_contains "forcing" && assert_logged_before "shutdown alpha" "destroy alpha"
}

test_snapshot_redefines_the_domain_for_running_from_the_disk() {
    snapshot_world
    run_step snapshot
    assert_status 0 && grep -qF "<boot dev='hd'/>" "$WORLD/state/domain.xml" &&
        ! grep -qF "Win11.iso" "$WORLD/state/domain.xml"
}

test_snapshot_takes_an_external_disk_and_memory_snapshot() {
    snapshot_world
    run_step snapshot
    assert_status 0 && assert_logged "snapshot-create-as alpha tartarus-clean" && assert_logged "--atomic" &&
        assert_logged "--memspec file=$WORLD/libvirt/images/alpha-clean.mem,snapshot=external" &&
        assert_logged "--diskspec sda,snapshot=external,file=$WORLD/libvirt/images/alpha-clean.qcow2"
}

test_snapshot_takes_the_disk_target_from_the_domain_xml() {
    snapshot_world ubuntu cloud.img
    ctx_set profile.hardware.disk_bus '"virtio"'
    run_step snapshot
    assert_status 0 && assert_logged "--diskspec vda,snapshot=external" && assert_not_logged "sda"
}

test_snapshot_reads_the_target_the_domain_really_has() {
    snapshot_world
    cat >"$WORLD/state/dumpxml-override" <<'XML'
<domain><devices><disk type='file' device='cdrom'><target dev='sdb'/></disk><disk type='file' device='disk'><target dev='vdc' bus='virtio'/></disk></devices></domain>
XML
    run_step snapshot
    assert_status 0 && assert_logged "--diskspec vdc,snapshot=external"
}

test_snapshot_records_the_snapshot_in_the_guest_record() {
    snapshot_world
    run_step snapshot
    assert_status 0 && [[ $(guest_json_field snapshot) == '"tartarus-clean"' ]]
}

test_snapshot_is_skipped_when_it_already_exists() {
    snapshot_world
    echo tartarus-clean >"$WORLD/state/snapshots"
    run_step snapshot
    assert_status 0 && assert_not_logged "snapshot-create-as" && assert_not_logged "shutdown" &&
        assert_not_logged "define" && assert_not_logged "start alpha" && assert_logged "destroy alpha"
}

test_snapshot_fails_when_the_agent_never_answers() {
    snapshot_world
    echo 503 >"$WORLD/state/agent-code"
    run_step snapshot
    assert_status 1 && assert_contains "agent" && assert_not_logged "snapshot-create-as"
}

test_snapshot_runs_the_profiles_pre_snapshot_step_before_the_snapshot() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '["flush"]'
    mkdir -p "$WORLD/profile/steps"
    printf '#!/usr/bin/env bash\necho "pre-snapshot ran for $TT_STEP" >>"$STUB_LOG"\n' >"$WORLD/profile/steps/flush"
    chmod +x "$WORLD/profile/steps/flush"
    run_step snapshot
    assert_status 0 && assert_logged_before "http://192.168.150.10:8000/" "pre-snapshot ran for snapshot" &&
        assert_logged_before "pre-snapshot ran" "snapshot-create-as"
}

test_snapshot_fails_when_the_pre_snapshot_step_fails() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '["flush"]'
    mkdir -p "$WORLD/profile/steps"
    printf '#!/usr/bin/env bash\nexit 4\n' >"$WORLD/profile/steps/flush"
    chmod +x "$WORLD/profile/steps/flush"
    run_step snapshot
    assert_status 1 && assert_contains "flush" && assert_not_logged "snapshot-create-as"
}

test_snapshot_fails_when_the_named_pre_snapshot_step_does_not_exist() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '["nowhere"]'
    run_step snapshot
    assert_status 1 && assert_contains "nowhere"
}

# pre_snapshot_steps <name>...: profile steps that log their name, in the order they ran.
pre_snapshot_steps() {
    local name
    mkdir -p "$WORLD/profile/steps"
    for name in "$@"; do
        printf '#!/usr/bin/env bash\necho "pre-snapshot step %s ran" >>"$STUB_LOG"\n' "$name" >"$WORLD/profile/steps/$name"
        chmod +x "$WORLD/profile/steps/$name"
    done
}

test_snapshot_runs_every_pre_snapshot_step_in_the_order_listed_before_the_snapshot() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '["first", "second"]'
    pre_snapshot_steps first second
    run_step snapshot
    assert_status 0 && assert_logged_before "http://192.168.150.10:8000/" "pre-snapshot step first ran" &&
        assert_logged_before "pre-snapshot step first ran" "pre-snapshot step second ran" &&
        assert_logged_before "pre-snapshot step second ran" "snapshot-create-as"
}

test_snapshot_fails_when_the_second_pre_snapshot_step_fails_and_takes_no_snapshot() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '["first", "second"]'
    pre_snapshot_steps first
    printf '#!/usr/bin/env bash\nexit 4\n' >"$WORLD/profile/steps/second"
    chmod +x "$WORLD/profile/steps/second"
    run_step snapshot
    assert_status 1 && assert_logged "pre-snapshot step first ran" && assert_contains "second" &&
        assert_not_logged "snapshot-create-as"
}

test_snapshot_runs_no_pre_snapshot_step_for_an_empty_list() {
    snapshot_world
    ctx_set profile.agent.pre_snapshot '[]'
    run_step snapshot
    assert_status 0 && assert_not_logged "pre-snapshot" && assert_logged "snapshot-create-as"
}

test_snapshot_names_no_operating_system() {
    [[ -x $STEPS/snapshot ]] && ! grep -qiE 'windows|defender|powershell|wiminfo' "$STEPS/snapshot"
}

# --- register -----------------------------------------------------------------------------

test_register_is_a_no_op_that_announces_itself() {
    new_world
    run_step register
    assert_status 0 && assert_contains "STEP " && [[ ! -s $LOG ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
