#!/usr/bin/env bash
# Tests the Windows profile's own build steps (guest/profiles/windows/steps/{install,provision,
# tamper-off,defender-on}) the way the build sequencer runs them: as executables with the TT_*
# environment, from a copy of guest/ laid out like the image. The guest is a fake agent on loopback
# (scripts/tests/fake_guest_agent.py); virsh and xorriso are stubs on PATH that record their calls.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTS="$REPO/scripts/tests"
WORK="$(mktemp -d)"
AGENT_PID=""
trap 'stop_agent; rm -rf "$WORK"' EXIT

failures=0
OUTPUT=""
STATUS=0

free_port() { python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

wait_for_port() {
    local tries=0
    until python3 -I -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.5).close()' "$1" 2>/dev/null; do
        ((++tries > 50)) && { echo "nothing listens on $1" >&2; return 1; }
        sleep 0.1
    done
}

stop_agent() { [[ -n $AGENT_PID ]] && { kill "$AGENT_PID" 2>/dev/null; wait "$AGENT_PID" 2>/dev/null; }; AGENT_PID=""; return 0; }

json_get() { python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

write_stubs() {
    cat >"$SB/bin/virsh" <<'STUB'
#!/usr/bin/env bash
# virsh -c <uri> <command> ...: the domain is "running" or "shut off"; STUB_DIR/domstate-sequence
# holds states to report one per domstate call before the real one.
shift 2
command=$1
shift
echo "virsh $command $*" >>"$STUB_DIR/calls"
case $command in
    define) cp "$1" "$STUB_DIR/defined.xml" ;;
    start) [[ -e $STUB_DIR/start-fails ]] && exit 1; echo running >"$STUB_DIR/state" ;;
    destroy) echo "shut off" >"$STUB_DIR/state" ;;
    domstate)
        if [[ -s $STUB_DIR/domstate-sequence ]]; then
            head -n1 "$STUB_DIR/domstate-sequence"
            sed -i 1d "$STUB_DIR/domstate-sequence"
        else
            cat "$STUB_DIR/state"
        fi ;;
    send-key | dominfo) ;;
esac
STUB
    cat >"$SB/bin/xorriso" <<'STUB'
#!/usr/bin/env bash
echo "xorriso $*" >>"$STUB_DIR/calls"
[[ -e $STUB_DIR/xorriso-fails ]] && { echo "xorriso: boom" >&2; exit 1; }
output="" source="${!#}"
while (($#)); do
    [[ $1 == -o ]] && output=$2
    shift
done
[[ -e $output ]] && echo "iso-existed" >>"$STUB_DIR/calls"
(cd "$source" && find . -type f | sort) >"$STUB_DIR/iso-listing"
cp "$source/autounattend.xml" "$STUB_DIR/staged-autounattend.xml"
: >"$output"
STUB
    chmod +x "$SB/bin/"*
}

# A fresh sandbox: a copy of guest/ laid out like the image, a context for the fake agent, stubs.
new_sandbox() {
    stop_agent
    SB="$(mktemp -d -p "$WORK")"
    export STUB_DIR="$SB/stub"
    mkdir -p "$SB/bin" "$STUB_DIR" "$SB/lv/tartarus/cache" "$SB/lv/images" "$SB/media" "$SB/build" "$SB/disk" "$SB/guestdir"
    cp -r "$REPO/guest" "$SB/guest"
    find "$SB/guest" -name __pycache__ -prune -exec rm -rf {} +
    PROFILE="$SB/guest/profiles/windows"
    echo "shut off" >"$STUB_DIR/state"
    : >"$STUB_DIR/domstate-sequence"
    write_stubs
    AGENT_PORT=$(free_port)
    python3 -I "$TESTS/make_step_context.py" "$SB/ctx" "$AGENT_PORT" "$SB/lv" "$SB/media"
    : >"$SB/media/disc.iso"
    : >"$SB/agent.py"
    local name
    while read -r _ name _; do : >"$SB/lv/tartarus/cache/$name"; done < <(grep -vE '^[[:space:]]*(#|$)' "$PROFILE/manifest.sha256")
    WORK_ON_DISK="$SB/disk/ProgramData/abcdefgh"
    DONE_MARKER=$(json_get "$PROFILE/names.json" done_marker)
    LOG_FILE=$(json_get "$PROFILE/names.json" log_file)
    echo '{}' >"$SB/behaviour.json"
    start_agent
}

start_agent() {
    python3 -I "$TESTS/fake_guest_agent.py" "$AGENT_PORT" "$SB/disk" "$SB/requests.jsonl" "$SB/behaviour.json" &
    AGENT_PID=$!
    wait_for_port "$AGENT_PORT"
}

behave() { printf '%s\n' "$1" >"$SB/behaviour.json"; }

# Runs a step with the environment the sequencer gives it (plus the test knobs).
run_step() {
    local step=$1
    shift
    OUTPUT="$(env -i PATH="$SB/bin:$PATH" HOME="$SB" STUB_DIR="$STUB_DIR" \
        TT_GUEST_DIR="$SB/guestdir" TT_GUEST_JSON="$SB/ctx/guest.json" TT_PROFILE_DIR="$PROFILE" \
        TT_STATE_FILE="$SB/state.json" TT_BUILD_DIR="$SB/build" TT_CONTEXT_JSON="$SB/ctx/context.json" \
        TT_STEP="$step" TT_BUILD_ID=b1 TT_LOG="$SB/log" \
        TT_AGENT_SCRIPT="$SB/agent.py" INSTALL_GUARD_SECONDS=30 INSTALL_POLL_SECONDS=0.05 INSTALL_KEY_PRESSES=3 INSTALL_KEY_INTERVAL=0.02 INSTALL_START_BYTES=0 INSTALL_START_CHECK=1 INSTALL_START_ATTEMPTS=3 "$@" \
        bash "$PROFILE/steps/$step" 2>&1 </dev/null)"
    STATUS=$?
}

indent() { sed 's/^/    | /'; }
assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_missing() { [[ $OUTPUT != *"$1"* ]] || { echo "  expected output NOT to contain: $1"; return 1; }; }
assert_status() { [[ $STATUS -eq $1 ]] || { echo "  expected exit $1, got $STATUS"; indent <<<"$OUTPUT"; return 1; }; }
calls() { cat "$STUB_DIR/calls" 2>/dev/null; }
assert_called() { calls | grep -qE -- "$1" || { echo "  expected a call matching: $1"; calls | indent; return 1; }; }
assert_not_called() { ! calls | grep -qE -- "$1" || { echo "  expected NO call matching: $1"; return 1; }; }

# Python over the agent's request log: $1 is the body of a check(requests) function.
requests_satisfy() {
    python3 -I -c '
import json, sys
requests = [json.loads(line) for line in open(sys.argv[1])]
exec(sys.argv[2])
' "$SB/requests.jsonl" "$1"
}

provisioned() { mkdir -p "$WORK_ON_DISK" && echo "marker" >"$WORK_ON_DISK/$DONE_MARKER"; }

# --- install ---------------------------------------------------------------------------------------

appears_after() { # polls
    behave "{\"appears_after_polls\": {\"path\": \"C:\\\\ProgramData\\\\abcdefgh\\\\$DONE_MARKER\", \"polls\": $1}}"
}

test_install_stages_the_answer_files_boots_the_installer_and_waits_for_provisioning() {
    new_sandbox
    appears_after 3
    run_step install
    assert_status 0 &&
        assert_called 'virsh define ' &&
        assert_called 'virsh start ' &&
        assert_contains "STEP " &&
        assert_contains "PROGRESS 100"
}

test_install_attaches_the_installation_medium_and_the_answer_files_as_two_discs() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    if grep -q "<source file='$SB/media/disc.iso'/>" "$STUB_DIR/defined.xml" &&
        grep -qE "<source file='[^']*\.iso'/>" <(grep -v disc.iso "$STUB_DIR/defined.xml"); then
        return 0
    fi
    echo "  the defined domain does not carry both discs:"
    grep -n "source file" "$STUB_DIR/defined.xml"
    return 1
}

test_install_builds_the_answer_iso_with_the_neutral_volume_label() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    local label
    label=$(json_get "$PROFILE/names.json" cd_volume_label)
    assert_called "xorriso .*-V $label .*-J -joliet-long -r -o "
}

test_install_stages_what_first_logon_provisioning_reads_from_the_disc() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    local marker expected
    marker=$(json_get "$PROFILE/names.json" cd_marker_file)
    for expected in ./autounattend.xml "./$marker" ./provision/provision.ps1 ./provision/defender-settings.ps1 \
        ./provision/decoys.ps1 ./provision/sysmon-config.xml ./payload/agent.py ./payload/python-3.11.9.exe ./payload/Sysmon64.exe; do
        grep -qxF "$expected" "$STUB_DIR/iso-listing" || { echo "  the disc lacks $expected:"; cat "$STUB_DIR/iso-listing"; return 1; }
    done
}

test_install_renders_the_answer_file_from_the_guest_record() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    grep -q "<Name>Michael</Name>" "$STUB_DIR/staged-autounattend.xml" &&
        grep -q "<ComputerName>DESKTOP-ABC1234</ComputerName>" "$STUB_DIR/staged-autounattend.xml" &&
        ! grep -qF "\${" "$STUB_DIR/staged-autounattend.xml"
}

test_install_never_prints_the_password_or_leaves_the_staging_folder_behind() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    assert_missing "Sup3r-secret-pw" || return 1
    [[ ! -e $SB/build/answer-files ]] || { echo "  the plaintext staging folder was left behind"; return 1; }
}

test_install_replaces_an_answer_iso_an_earlier_attempt_left() {
    new_sandbox
    appears_after 2
    : >"$SB/build/answer.iso"
    run_step install
    assert_status 0 || return 1
    grep -q 'iso-existed' "$STUB_DIR/calls" && { echo "  xorriso was run over the old ISO"; return 1; }
    return 0
}

test_install_dismisses_press_any_key_with_enter_for_the_configured_seconds() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    [[ $(calls | grep -c 'virsh send-key .* KEY_ENTER') -eq 3 ]] || { echo "  expected 3 Enter presses"; calls; return 1; }
}

# Setup has started once it writes to the blank disk; the firmware's "press any key" window is
# short and its timing varies, so a boot that never reached Setup is reset and tried again.
test_install_without_setup_writing_to_the_disk_resets_the_guest_and_presses_enter_again() {
    new_sandbox
    appears_after 2
    run_step install INSTALL_START_BYTES=100000
    assert_status 1 || return 1
    assert_contains "has not started" || return 1
    [[ $(calls | grep -c '^virsh reset') -eq 2 ]] || { echo "  expected 2 resets (3 attempts)"; calls; return 1; }
    [[ $(calls | grep -c 'virsh send-key .* KEY_ENTER') -eq 9 ]] || { echo "  expected 9 Enter presses"; calls; return 1; }
}

test_install_that_reaches_setup_on_the_first_attempt_resets_nothing() {
    new_sandbox
    appears_after 2
    head -c 200000 /dev/urandom >"$SB/lv/images/$(json_get "$SB/ctx/guest.json" name).qcow2"
    run_step install INSTALL_START_BYTES=100000
    assert_status 0 || return 1
    assert_not_called '^virsh reset'
}

test_install_starts_the_domain_after_defining_it_with_the_answer_disc() {
    new_sandbox
    appears_after 2
    run_step install
    assert_status 0 || return 1
    local order
    order=$(calls | awk '/^xorriso/ {print "iso"} /^virsh define/ {print "define"} /^virsh start/ {print "start"} /^virsh send-key/ {print "key"}' | uniq | tr '\n' ' ')
    [[ $order == "iso define start key " ]] || { echo "  order was: $order"; return 1; }
}

test_install_waits_with_progress_lines_that_never_go_backwards_or_pass_99_before_the_end() {
    new_sandbox
    appears_after 8
    run_step install
    assert_status 0 || return 1
    local values previous=-1 value
    values=$(grep '^PROGRESS ' <<<"$OUTPUT" | cut -d' ' -f2)
    for value in $values; do
        ((value >= previous)) || { echo "  progress went back: $previous -> $value"; return 1; }
        previous=$value
    done
    [[ $(grep -c '^PROGRESS ' <<<"$OUTPUT") -ge 3 ]]
}

test_install_on_resume_with_the_domain_running_does_not_wipe_it() {
    new_sandbox
    echo running >"$STUB_DIR/state"
    appears_after 2
    run_step install
    assert_status 0 &&
        assert_not_called 'virsh (define|start|destroy|undefine|send-key)' &&
        assert_not_called '^xorriso'
}

test_install_when_provisioning_already_finished_does_nothing() {
    new_sandbox
    echo running >"$STUB_DIR/state"
    provisioned
    run_step install
    assert_status 0 &&
        assert_not_called 'virsh (define|start|destroy|undefine|send-key)' &&
        assert_not_called '^xorriso' &&
        assert_contains "provisioning had already finished"
}

test_install_a_guest_that_shuts_off_before_provisioning_ends_fails_the_step() {
    new_sandbox
    printf 'running\nrunning\nshut off\n' >"$STUB_DIR/domstate-sequence"
    echo "shut off" >"$STUB_DIR/state"
    run_step install
    assert_status 1 && assert_contains "stopped"
}

test_install_a_domain_that_will_not_start_fails_the_step() {
    new_sandbox
    : >"$STUB_DIR/start-fails"
    run_step install
    assert_status 1 && assert_contains "start"
}

test_install_when_the_disc_cannot_be_built_fails_before_defining_anything() {
    new_sandbox
    : >"$STUB_DIR/xorriso-fails"
    run_step install
    assert_status 1 && assert_contains "answer" && assert_not_called 'virsh (define|start)'
}

test_install_without_a_downloaded_installer_says_to_run_fetch() {
    new_sandbox
    rm "$SB/lv/tartarus/cache/Sysmon64.exe"
    run_step install
    assert_status 1 && assert_contains "Sysmon64.exe" && assert_contains "fetch"
}

test_install_gives_up_after_its_own_generous_guard() {
    new_sandbox
    run_step install INSTALL_GUARD_SECONDS=1
    assert_status 1 && assert_contains "did not finish"
}

# --- provision -------------------------------------------------------------------------------------

with_guest_log() {
    mkdir -p "$WORK_ON_DISK"
    printf '2026-10-15 10:00:00  STEP one\r\n2026-10-15 10:00:01    ok\r\n' >"$WORK_ON_DISK/$LOG_FILE"
    provisioned
}

cleanup_replies() { # stdout of the script
    behave "{\"scripts\": {\"cleanup.ps1\": {\"stdout\": \"$1\"}}}"
}

test_provision_fetches_the_guest_log_into_the_build_dir_and_the_build_log() {
    new_sandbox
    with_guest_log
    cleanup_replies 'RESULT removed=python-3.11.9.exe\r\nEXITCODE 0\r\n'
    run_step provision
    assert_status 0 &&
        assert_contains "LOG guest: 2026-10-15 10:00:01    ok" &&
        [[ $(tr -d '\r' <"$SB/build/provision.log") == *"STEP one"* ]]
}

test_provision_fetches_the_log_before_it_runs_the_cleanup() {
    new_sandbox
    with_guest_log
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 || return 1
    requests_satisfy '
paths = [(r["path"], r.get("form", {}).get("filepath", "")) for r in requests]
log_at = next(i for i, p in enumerate(paths) if p[0] == "/retrieve" and p[1].endswith("setup.log"))
run_at = next(i for i, r in enumerate(requests) if r["path"] == "/execute")
assert log_at < run_at, paths
'
}

test_provision_runs_the_cleanup_in_the_64_bit_shell_with_the_work_folder_log_and_marker() {
    new_sandbox
    with_guest_log
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 || return 1
    requests_satisfy "
(execute,) = [r for r in requests if r['path'] == '/execute']
assert execute['command'].startswith('C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe -NoProfile'), execute
driver = execute['driver']
assert \"cleanup.ps1' -WorkDir 'C:\\\\ProgramData\\\\abcdefgh' -LogName 'setup.log' -DoneMarker 'setup.state'\" in driver, driver
"
}

test_provision_saves_the_log_without_carriage_returns_or_nul_bytes() {
    new_sandbox
    mkdir -p "$WORK_ON_DISK"
    printf 'first line\r\nsecond\000 line\r\n\000\000\000' >"$WORK_ON_DISK/$LOG_FILE"
    provisioned
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 || return 1
    [[ $(od -An -c "$SB/build/provision.log" | tr -d ' \n') == 'firstline\nsecondline\n' ]] ||
        { echo "  saved log: $(od -An -c "$SB/build/provision.log")"; return 1; }
}

test_provision_fails_when_the_cleanup_fails() {
    new_sandbox
    with_guest_log
    cleanup_replies 'RESULT kept=x\r\nEXITCODE 40\r\n'
    run_step provision
    assert_status 1 && assert_contains "cleanup" && assert_contains "RESULT kept=x"
}

test_provision_fails_when_the_agent_does_not_answer_after_the_cleanup() {
    new_sandbox
    with_guest_log
    behave '{"silent_after_execute": true, "scripts": {"cleanup.ps1": {"stdout": "EXITCODE 0\r\n"}}}'
    run_step provision PROVISION_AGENT_WAIT_SECONDS=1 PROVISION_AFTER_CLEANUP_WAIT_SECONDS=1 PROVISION_PROBE_SECONDS=0.2
    assert_status 1 && assert_contains "agent" && assert_contains "after the cleanup"
}

test_provision_fails_when_the_agent_never_answers() {
    new_sandbox
    behave '{"answers": false}'
    run_step provision PROVISION_AGENT_WAIT_SECONDS=1 PROVISION_AFTER_CLEANUP_WAIT_SECONDS=1 PROVISION_PROBE_SECONDS=0.2
    assert_status 1 && assert_contains "agent" && assert_missing "cleanup.ps1"
}

test_provision_warns_about_provisioning_steps_that_failed_in_the_guest() {
    new_sandbox
    mkdir -p "$WORK_ON_DISK"
    printf '2026-10-15 10:00:00  STEP sysmon\r\n2026-10-15 10:00:01    FAILED: no service\r\n' >"$WORK_ON_DISK/$LOG_FILE"
    provisioned
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 && assert_contains "1 provisioning step(s) failed"
}

test_provision_cannot_be_injected_through_the_guest_log() {
    new_sandbox
    mkdir -p "$WORK_ON_DISK"
    printf 'PAUSE do something\nPROGRESS 77\nSTEP fake\n' >"$WORK_ON_DISK/$LOG_FILE"
    provisioned
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 || return 1
    ! grep -qE '^(PAUSE|PROGRESS 77|STEP fake)' <<<"$OUTPUT" || { echo "  a guest line was taken for a protocol line"; return 1; }
}

test_provision_run_again_after_the_cleanup_still_works_from_the_saved_log() {
    new_sandbox
    with_guest_log
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 0 || return 1
    rm "$WORK_ON_DISK/$LOG_FILE"
    run_step provision
    assert_status 0 && assert_contains "saved"
}

test_provision_without_any_log_fails() {
    new_sandbox
    provisioned
    cleanup_replies 'EXITCODE 0\r\n'
    run_step provision
    assert_status 1 && assert_contains "log"
}

# --- tamper-off and defender-on --------------------------------------------------------------------

script_replies() { # script, stdout
    behave "{\"scripts\": {\"$1\": {\"stdout\": \"$2\"}}}"
}

test_tamper_off_uploads_both_scripts_runs_it_and_logs_the_result_lines() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT toggle_name=Tamper Protection\r\nRESULT IsTamperProtected=False\r\nEXITCODE 0\r\n'
    run_step tamper-off
    assert_status 0 &&
        assert_contains "LOG RESULT IsTamperProtected=False" &&
        [[ -f $WORK_ON_DISK/tamper-off.ps1 && -f $WORK_ON_DISK/defender-settings.ps1 && -f $WORK_ON_DISK/security-ui.ps1 ]] &&
        requests_satisfy "
stored = [r['form']['filepath'] for r in requests if r['path'] == '/store']
assert 'C:\\\\ProgramData\\\\abcdefgh\\\\tamper-off.ps1' in stored, stored
assert 'C:\\\\ProgramData\\\\abcdefgh\\\\defender-settings.ps1' in stored, stored
(execute,) = [r for r in requests if r['path'] == '/execute']
assert execute['command'].startswith('C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/ProgramData/abcdefgh/'), execute
assert 'tamper-off.ps1' in execute['driver'] and 'Remove-Item' in execute['driver']
"
}

test_tamper_off_pauses_with_instructions_when_the_toggle_is_not_found() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT toggle=not-found\r\nEXITCODE 10\r\n'
    run_step tamper-off
    assert_status 75 &&
        assert_contains "PAUSE " &&
        assert_contains "Tamper Protection" &&
        assert_contains "Continue" &&
        assert_contains "LOG RESULT toggle=not-found"
}

test_tamper_off_pause_text_is_one_protocol_line_and_names_no_giveaway() {
    new_sandbox
    script_replies tamper-off.ps1 'EXITCODE 10\r\n'
    run_step tamper-off
    [[ $(grep -c '^PAUSE ' <<<"$OUTPUT") -eq 1 ]] || { echo "  expected exactly one PAUSE line"; return 1; }
}

test_tamper_off_fails_when_verification_fails() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT IsTamperProtected=True\r\nEXITCODE 20\r\n'
    run_step tamper-off
    assert_status 1 && assert_contains "IsTamperProtected=True" && assert_missing "PAUSE "
}

test_tamper_off_fails_when_a_proof_fails() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT eicar_present_after_write=False\r\nEXITCODE 30\r\n'
    run_step tamper-off
    assert_status 1 && assert_contains "eicar_present_after_write=False" && assert_missing "PAUSE "
}

test_tamper_off_fails_on_an_exit_code_it_does_not_know() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT error=boom\r\nEXITCODE 40\r\n'
    run_step tamper-off
    assert_status 1 && assert_contains "exit code 40" && assert_contains "error=boom"
}

test_tamper_off_fails_when_the_script_reports_no_exit_code() {
    new_sandbox
    script_replies tamper-off.ps1 'RESULT a=b\r\n'
    run_step tamper-off
    assert_status 1 && assert_contains "no exit code"
}

test_tamper_off_fails_when_the_agent_is_unreachable() {
    new_sandbox
    stop_agent
    run_step tamper-off
    assert_status 1 && assert_contains "agent"
}

test_tamper_off_run_again_after_a_pause_runs_the_script_again() {
    new_sandbox
    script_replies tamper-off.ps1 'EXITCODE 10\r\n'
    run_step tamper-off
    assert_status 75 || return 1
    script_replies tamper-off.ps1 'RESULT IsTamperProtected=False\r\nEXITCODE 0\r\n'
    run_step tamper-off
    assert_status 0
}

test_defender_on_runs_its_own_script_with_the_shared_settings_script() {
    new_sandbox
    script_replies defender-on.ps1 'RESULT eicar_removed=True\r\nEXITCODE 0\r\n'
    run_step defender-on
    assert_status 0 &&
        assert_contains "LOG RESULT eicar_removed=True" &&
        requests_satisfy "
stored = [r['form']['filepath'] for r in requests if r['path'] == '/store']
assert any(p.endswith('defender-on.ps1') for p in stored) and any(p.endswith('defender-settings.ps1') for p in stored) and any(p.endswith('security-ui.ps1') for p in stored), stored
"
}

test_defender_on_pauses_asking_to_switch_tamper_protection_on() {
    new_sandbox
    script_replies defender-on.ps1 'EXITCODE 10\r\n'
    run_step defender-on
    assert_status 75 && assert_contains "PAUSE " && assert_contains " on"
}

test_defender_on_fails_when_verification_or_the_removal_proof_fails() {
    new_sandbox
    local code
    for code in 20 30; do
        script_replies defender-on.ps1 "RESULT x=y\\r\\nEXITCODE $code\\r\\n"
        run_step defender-on
        assert_status 1 || return 1
    done
}

# --- the steps themselves --------------------------------------------------------------------------

# --- remove-ghost-drives ----------------------------------------------------------------------

test_remove_ghost_drives_uploads_its_script_runs_it_and_logs_what_it_removed() {
    new_sandbox
    script_replies remove-ghost-drives.ps1 'RESULT found=2\r\nRESULT removed=2\r\nEXITCODE 0\r\n'
    run_step remove-ghost-drives
    assert_status 0 &&
        assert_contains "LOG RESULT removed=2" &&
        requests_satisfy "
stored = [r['form']['filepath'] for r in requests if r['path'] == '/store']
assert 'C:\\\\ProgramData\\\\abcdefgh\\\\remove-ghost-drives.ps1' in stored, stored
(execute,) = [r for r in requests if r['path'] == '/execute']
assert 'remove-ghost-drives.ps1' in execute['driver'] and 'Remove-Item' in execute['driver']
"
}

test_remove_ghost_drives_with_nothing_to_remove_succeeds_again() {
    new_sandbox
    script_replies remove-ghost-drives.ps1 'RESULT found=0\r\nRESULT removed=0\r\nEXITCODE 0\r\n'
    run_step remove-ghost-drives
    assert_status 0 && assert_contains "LOG RESULT removed=0"
}

test_remove_ghost_drives_fails_when_the_script_fails() {
    new_sandbox
    script_replies remove-ghost-drives.ps1 'RESULT error=boom\r\nEXITCODE 40\r\n'
    run_step remove-ghost-drives
    assert_status 1 && assert_contains "remove-ghost-drives.ps1"
}

test_remove_ghost_drives_fails_when_the_script_reports_no_exit_code() {
    new_sandbox
    script_replies remove-ghost-drives.ps1 'RESULT a=b\r\n'
    run_step remove-ghost-drives
    assert_status 1 && assert_contains "no exit code"
}

test_remove_ghost_drives_fails_when_the_agent_is_unreachable() {
    new_sandbox
    stop_agent
    run_step remove-ghost-drives
    assert_status 1 && assert_contains "agent"
}

test_every_step_is_executable_and_is_bash_with_strict_mode() {
    local step
    for step in install provision tamper-off defender-on remove-ghost-drives; do
        [[ -x $REPO/guest/profiles/windows/steps/$step ]] || { echo "  $step is not executable"; return 1; }
        head -n1 "$REPO/guest/profiles/windows/steps/$step" | grep -qx '#!/usr/bin/env bash' || { echo "  $step: wrong shebang"; return 1; }
        grep -q '^set -uo pipefail' "$REPO/guest/profiles/windows/steps/$step" || { echo "  $step: no strict mode"; return 1; }
    done
}

# With arguments, only the named tests run.
tests=("$@")
((${#tests[@]})) || mapfile -t tests < <(declare -F | awk '$3 ~ /^test_/ {print $3}')
for name in "${tests[@]}"; do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
