#!/usr/bin/env bash
# Tests the pure logic of scripts/build-guest.sh: template rendering and manifest verification,
# which need neither Docker nor a guest. The orchestration that drives the container is proven
# end to end by scripts/verify-guest.sh instead.
set -uo pipefail

BUILD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build-guest.sh"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0

# Identity vars render-domain requires; the real build generates these per run.
render_env() {
    GUEST_UUID=11111111-2222-3333-4444-555555555555 GUEST_MAC=00:14:22:ab:cd:ef \
        SMBIOS_SERIAL=7ABCDE1 SMBIOS_BOARD_SERIAL=/7ABCDE1/CN123456 SMBIOS_DISK_SERIAL=S4EWNX0ABCDEF \
        "$@"
}

run() { OUTPUT="$(TARTARUS_ENV_FILE=${TARTARUS_ENV_FILE:-/dev/null} render_env bash "$BUILD" "$@" 2>&1 </dev/null)"; STATUS=$?; }

assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; return 1; }; }
assert_missing()  { [[ $OUTPUT != *"$1"* ]] || { echo "  expected output NOT to contain: $1"; return 1; }; }

run_test() {
    local name=$1
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_autounattend_substitutes_the_build_parameters() {
    GUEST_USERNAME=Casey GUEST_IMAGE_INDEX=5 GUEST_UI_LANG=pl-PL run render-autounattend
    [[ $STATUS -eq 0 ]] || { echo "  non-zero exit"; return 1; }
    assert_contains "<Value>5</Value>" &&
        assert_contains "<Name>Casey</Name>" &&
        assert_contains "<UILanguage>pl-PL</UILanguage>" &&
        assert_contains "BypassTPMCheck" &&
        assert_missing '${'
}

well_formed_xml() { python3 -I -c 'import sys, xml.dom.minidom; xml.dom.minidom.parseString(sys.stdin.read())' <<<"$OUTPUT"; }

# Windows 11 25H2 Setup does not report a malformed answer file: setup.exe exits, and WinPE
# reboots straight back to the CD prompt. An unbound wcm: prefix once caused exactly that.
test_autounattend_is_well_formed_namespaced_xml() {
    run render-autounattend
    well_formed_xml || { echo "  rendered autounattend.xml is not well-formed XML"; return 1; }
}

test_domain_is_well_formed_xml() {
    run render-domain install
    well_formed_xml || { echo "  rendered install domain is not well-formed XML"; return 1; }
}

test_autounattend_runs_provisioning_at_first_logon() {
    run render-autounattend
    assert_contains "FirstLogonCommands" && assert_contains "provision.ps1"
}

test_domain_install_mode_attaches_media_and_boots_cdrom() {
    run render-domain install
    [[ $STATUS -eq 0 ]] || { echo "  non-zero exit"; return 1; }
    assert_contains "Win11_25H2" &&
        assert_contains "<boot dev='cdrom'/>" &&
        assert_contains "unattend.iso" &&
        assert_missing '${'
}

test_domain_run_mode_ejects_media_and_boots_disk() {
    run render-domain run
    assert_contains "<boot dev='hd'/>" &&
        assert_missing "Win11_25H2" &&
        assert_missing "unattend.iso"
}

test_domain_sets_tpm_secureboot_hidden_hypervisor_and_real_smbios() {
    run render-domain run
    assert_contains "<tpm model='tpm-crb'>" &&
        assert_contains "secure='yes'" &&
        assert_contains "OVMF_CODE_4M.ms.fd" &&
        assert_contains "<hidden state='on'/>" &&
        assert_contains "policy='disable' name='hypervisor'" &&
        assert_contains "<entry name='manufacturer'>Dell Inc.</entry>" &&
        assert_missing "Standard PC" &&
        assert_contains "model type='e1000e'" &&
        assert_contains "00:14:22:ab:cd:ef"
}

# make does not load .env, so build-guest reads its GUEST_* settings from it itself.
test_guest_settings_come_from_the_env_file() {
    printf 'POSTGRES_PASSWORD=x\nGUEST_RAM_MB=8192\nGUEST_VCPUS=4\n' >"$WORK_DIR/env"
    TARTARUS_ENV_FILE="$WORK_DIR/env" run render-domain run
    assert_contains "<memory unit='KiB'>8388608</memory>" && assert_contains "<vcpu placement='static'>4</vcpu>"
}

test_the_environment_overrides_the_env_file() {
    printf 'GUEST_RAM_MB=8192\n' >"$WORK_DIR/env"
    GUEST_RAM_MB=2048 TARTARUS_ENV_FILE="$WORK_DIR/env" run render-domain run
    assert_contains "<memory unit='KiB'>2097152</memory>"
}

# Under pipefail, `tr ... | head -c 7 || echo fallback` also ran the fallback (tr dies of SIGPIPE),
# so the guest reported a 14-character serial with the fallback glued on.
test_identity_generates_realistic_serials_and_a_dell_mac() {
    OUTPUT=$(bash "$BUILD" identity 2>&1 </dev/null); STATUS=$?
    [[ $STATUS -eq 0 ]] || { echo "  exit $STATUS: $OUTPUT"; return 1; }
    grep -qE '^SMBIOS_SERIAL=[A-Z0-9]{7}$' <<<"$OUTPUT" &&
        grep -qE '^SMBIOS_DISK_SERIAL=S4EWNX0[A-Z0-9]{6}$' <<<"$OUTPUT" &&
        grep -qE '^GUEST_MAC=00:14:22(:[0-9a-f]{2}){3}$' <<<"$OUTPUT" &&
        grep -qE '^GUEST_UUID=[0-9a-f-]{36}$' <<<"$OUTPUT" ||
        { echo "  unexpected identity:"; sed 's/^/    /' <<<"$OUTPUT"; return 1; }
}

# libvirt's element is <baseBoard>; it silently drops a lowercase <baseboard>, leaving the guest
# with no SMBIOS type 2 at all.
test_domain_sets_the_smbios_baseboard_with_libvirts_element_name() {
    run render-domain run
    assert_contains "<baseBoard>" && assert_missing "<baseboard>"
}

# migratable='off' exposes invtsc, and libvirt then refuses any memory snapshot of the guest.
test_domain_cpu_stays_migratable_so_memory_snapshots_work() {
    run render-domain run
    assert_contains "mode='host-passthrough'" && assert_contains "migratable='on'"
}

test_verify_manifest_passes_on_matching_hashes() {
    mkdir -p "$WORK_DIR/good"
    local empty; empty=$(printf '' | sha256sum | cut -d' ' -f1)
    { echo "# a comment line"; echo "$empty  alpha.bin  http://x/alpha"; echo "$empty  beta.bin  http://x/beta"; } >"$WORK_DIR/m"
    : >"$WORK_DIR/good/alpha.bin"; : >"$WORK_DIR/good/beta.bin"
    OUTPUT=$(MANIFEST="$WORK_DIR/m" bash "$BUILD" verify-manifest "$WORK_DIR/good" 2>&1); STATUS=$?
    [[ $STATUS -eq 0 ]] && assert_contains "[ OK ] alpha.bin" && assert_contains "[ OK ] beta.bin"
}

test_verify_manifest_fails_on_mismatch_and_missing() {
    mkdir -p "$WORK_DIR/bad"
    local empty; empty=$(printf '' | sha256sum | cut -d' ' -f1)
    { echo "$empty  present.bin  http://x/present"; echo "deadbeef  wrong.bin  http://x/wrong"; echo "$empty  absent.bin  http://x/absent"; } >"$WORK_DIR/mb"
    : >"$WORK_DIR/bad/present.bin"; printf 'data' >"$WORK_DIR/bad/wrong.bin"
    OUTPUT=$(MANIFEST="$WORK_DIR/mb" bash "$BUILD" verify-manifest "$WORK_DIR/bad" 2>&1); STATUS=$?
    [[ $STATUS -ne 0 ]] && assert_contains "[ OK ] present.bin" && assert_contains "[FAIL] wrong.bin" && assert_contains "[MISS] absent.bin"
}

# `docker compose exec` reads stdin; inside a `while read` over the manifest it once swallowed
# every entry after the first, so only Python was fetched.
test_fetch_downloads_every_manifest_entry_even_when_docker_reads_stdin() {
    local stub="$WORK_DIR/stub-fetch"
    mkdir -p "$stub/bin"
    cat >"$stub/bin/docker" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
echo "$*" >>"$STUB_LOG"
[[ $* == *"[ -f "* ]] && exit 1
exit 0
STUB
    chmod +x "$stub/bin/docker"
    { echo "# comment"; echo "aaa  one.exe  http://x/one.exe"; echo; echo "bbb  two.whl  http://x/two.whl"; } >"$WORK_DIR/m-fetch"
    OUTPUT=$(STUB_LOG="$stub/log" MANIFEST="$WORK_DIR/m-fetch" PATH="$stub/bin:$PATH" bash "$BUILD" fetch 2>&1 </dev/null); STATUS=$?
    [[ $STATUS -eq 0 ]] || { echo "  exit $STATUS: $OUTPUT"; return 1; }
    grep -q "curl .*http://x/one.exe" "$stub/log" && grep -q "curl .*http://x/two.whl" "$stub/log" ||
        { echo "  not every entry fetched:"; sed 's/^/    /' "$stub/log"; return 1; }
}

test_unknown_argument_exits_2() {
    run --bogus
    [[ $STATUS -eq 2 && $OUTPUT == *"usage"* ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
