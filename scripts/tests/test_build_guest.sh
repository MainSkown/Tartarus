#!/usr/bin/env bash
# Tests scripts/build-guest.sh, the thin wrapper that hands `make build-guest` to the `guest-build`
# command inside the cape container. `docker` is a stub on PATH that records its arguments, so the
# tests prove the preconditions it checks and the command line it assembles, not a build. The build
# itself is covered by the step tests (test_windows_steps.sh), the Python tests of guest-build, and
# end to end by `make build-guest` followed by `make verify-guest`.
set -uo pipefail

BUILD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build-guest.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0
GUEST_BUILD=/usr/local/lib/tartarus/guest-build

new_sandbox() {
    SB="$(mktemp -d -p "$WORK_DIR")"
    mkdir -p "$SB/bin" "$SB/iso"
    : >"$SB/env"
    : >"$SB/iso/Win11_25H2_Polish_x64_v2.iso"
    cat >"$SB/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Records one line per call: its arguments, then "[env GUEST_PASSWORD=<value>]" when that is set.
if [[ $* == *" cape true" ]]; then
    echo "stack-check $*" >>"$STUB_DIR/calls"
    [[ -e $STUB_DIR/stack-down ]] && exit 1
    exit 0
fi
echo "$*" >>"$STUB_DIR/calls"
echo "GUEST_PASSWORD=${GUEST_PASSWORD-<unset>} GUEST_PRODUCT_KEY=${GUEST_PRODUCT_KEY-<unset>}" >>"$STUB_DIR/environment"
exit "${STUB_BUILD_EXIT:-0}"
STUB
    chmod +x "$SB/bin/docker"
    export STUB_DIR="$SB"
}

# Runs the wrapper with only the variables given, so the host's own GUEST_* never leak in.
run() {
    OUTPUT="$(env -i PATH="$SB/bin:/usr/bin:/bin" HOME="$SB" STUB_DIR="$SB" \
        TARTARUS_ENV_FILE="$SB/env" TARTARUS_ISO_DIR="$SB/iso" "$@" bash "$BUILD" 2>&1 </dev/null)"
    STATUS=$?
}

run_with_args() {
    OUTPUT="$(env -i PATH="$SB/bin:/usr/bin:/bin" HOME="$SB" STUB_DIR="$SB" \
        TARTARUS_ENV_FILE="$SB/env" TARTARUS_ISO_DIR="$SB/iso" bash "$BUILD" "$@" 2>&1 </dev/null)"
    STATUS=$?
}

assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; echo "  got: $OUTPUT"; return 1; }; }
assert_status() { [[ $STATUS -eq $1 ]] || { echo "  expected exit $1, got $STATUS: $OUTPUT"; return 1; }; }

# The build command line the stub saw (the last call), as one string.
build_call() { tail -n1 "$SB/calls"; }
assert_build_call_contains() { [[ " $(build_call) " == *" $1 "* ]] || { echo "  build call lacks '$1': $(build_call)"; return 1; }; }
assert_build_call_lacks() { [[ " $(build_call) " != *" $1 "* ]] || { echo "  build call has '$1': $(build_call)"; return 1; }; }
build_calls() { grep -c "guest-build" "$SB/calls" 2>/dev/null; }

run_test() {
    local name=$1
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

test_the_defaults_build_the_windows_guest_called_win() {
    new_sandbox
    run
    assert_status 0 &&
        [[ $(build_call) == "compose exec -T cape python3 -I $GUEST_BUILD --profile windows --media Win11_25H2_Polish_x64_v2.iso --variant 5 --name win --option defender=true --accept-without-selftest" ]] ||
        { echo "  got: $(build_call)"; return 1; }
}

test_the_guest_settings_come_from_the_env_file() {
    new_sandbox
    printf 'POSTGRES_PASSWORD=x\nGUEST_LABEL=lab\nGUEST_IMAGE_INDEX=6\nGUEST_VCPUS=4\nGUEST_RAM_MB=8192\nGUEST_DISK_GB=100\nGUEST_ISO=other.iso\n' >"$SB/env"
    : >"$SB/iso/other.iso"
    run
    assert_status 0 &&
        assert_build_call_contains "--name lab" && assert_build_call_contains "--variant 6" &&
        assert_build_call_contains "--vcpus 4" && assert_build_call_contains "--ram-mb 8192" &&
        assert_build_call_contains "--disk-gb 100" && assert_build_call_contains "--media other.iso"
}

test_the_environment_overrides_the_env_file() {
    new_sandbox
    printf 'GUEST_LABEL=fromfile\n' >"$SB/env"
    run GUEST_LABEL=fromenv
    assert_build_call_contains "--name fromenv" && assert_build_call_lacks "--name fromfile"
}

test_hardware_flags_are_left_out_when_not_set_so_the_profile_defaults_apply() {
    new_sandbox
    run
    assert_build_call_lacks "--vcpus" && assert_build_call_lacks "--ram-mb" && assert_build_call_lacks "--disk-gb"
}

test_the_account_and_computer_name_are_passed_only_when_set() {
    new_sandbox
    run
    assert_build_call_lacks "--username" && assert_build_call_lacks "--computer-name" || return 1
    run GUEST_USERNAME=casey GUEST_HOSTNAME=DESKTOP-Q1
    assert_build_call_contains "--username casey" && assert_build_call_contains "--computer-name DESKTOP-Q1"
}

test_the_password_and_product_key_travel_in_the_environment_never_on_a_command_line() {
    new_sandbox
    printf 'GUEST_PASSWORD=Hunter2-secret\nGUEST_PRODUCT_KEY=AAAAA-BBBBB-CCCCC-DDDDD-EEEEE\n' >"$SB/env"
    run
    assert_status 0 || return 1
    ! grep -qE 'Hunter2-secret|AAAAA-BBBBB' "$SB/calls" || { echo "  a secret is on the command line"; return 1; }
    assert_build_call_contains "-e" && [[ $(build_call) == *"-e GUEST_PASSWORD"* && $(build_call) == *"-e GUEST_PRODUCT_KEY"* ]] &&
        grep -q 'GUEST_PASSWORD=Hunter2-secret GUEST_PRODUCT_KEY=AAAAA-BBBBB-CCCCC-DDDDD-EEEEE' "$SB/environment"
}

test_no_secret_flags_are_passed_when_none_is_set() {
    new_sandbox
    run
    [[ $(build_call) != *"-e GUEST_"* ]]
}

test_defender_follows_guest_defender() {
    new_sandbox
    run GUEST_DEFENDER=false
    assert_build_call_contains "defender=false" && assert_build_call_lacks "defender=true"
}

test_other_options_are_passed_when_set() {
    new_sandbox
    run GUEST_DECOYS=true GUEST_SYSMON=false GUEST_KEYBOARD=German
    assert_build_call_contains "decoys=true" && assert_build_call_contains "sysmon=false" && assert_build_call_contains "keyboard=German"
}

test_the_exit_code_of_the_build_is_the_wrappers() {
    new_sandbox
    run STUB_BUILD_EXIT=75
    assert_status 75
}

test_the_build_is_accepted_without_a_selftest_as_make_build_guest_always_was() {
    new_sandbox
    run
    assert_build_call_contains "--accept-without-selftest"
}

test_a_missing_env_file_is_refused_before_docker_is_called() {
    new_sandbox
    rm "$SB/env"
    run
    assert_status 1 && assert_contains ".env is missing" && [[ ! -e $SB/calls ]]
}

test_a_missing_iso_is_refused_and_named() {
    new_sandbox
    rm "$SB/iso/Win11_25H2_Polish_x64_v2.iso"
    run
    assert_status 1 && assert_contains "Win11_25H2_Polish_x64_v2.iso" && assert_contains "not found" && [[ $(build_calls) -eq 0 ]]
}

test_a_stack_that_is_not_up_is_refused_with_the_command_that_fixes_it() {
    new_sandbox
    : >"$SB/stack-down"
    run
    assert_status 1 && assert_contains "docker compose up" && [[ $(build_calls) -eq 0 ]]
}

test_help_prints_the_usage_and_does_nothing() {
    new_sandbox
    run_with_args --help
    assert_status 0 && assert_contains "guest-build" && [[ ! -e $SB/calls ]]
}

test_an_unknown_argument_exits_2_with_the_usage() {
    new_sandbox
    run_with_args --bogus
    assert_status 2 && assert_contains "usage"
}

test_the_old_subcommands_are_gone() {
    new_sandbox
    local subcommand
    for subcommand in fetch identity render-domain render-autounattend verify-manifest; do
        run_with_args "$subcommand"
        assert_status 2 || return 1
    done
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
