#!/usr/bin/env bash
# Tests the Windows profile's self-test check step (guest/profiles/windows/steps/selftest-checks) the
# way the control service runs it: as an executable with the TT_* environment, from a copy of guest/
# laid out like the image. The guest is the fake agent on loopback (scripts/tests/fake_guest_agent.py);
# virsh is a stub on PATH that records its calls and what the agent had been asked when it was called.
# shellcheck disable=SC2016  # python snippets and stubs are written with single quotes on purpose
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTS="$REPO/scripts/tests"
WORK="$(mktemp -d)"
AGENT_PID=""
trap 'stop_agent; rm -rf "$WORK"' EXIT

failures=0
OUTPUT=""
STATUS=0
PASSWORD="Sup3r-secret-pw"

free_port() { python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

wait_for_port() {
    local tries=0
    until python3 -I -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.5).close()' "$1" 2>/dev/null; do
        ((++tries > 50)) && { echo "nothing listens on $1" >&2; return 1; }
        sleep 0.1
    done
}

stop_agent() { [[ -n $AGENT_PID ]] && { kill "$AGENT_PID" 2>/dev/null; wait "$AGENT_PID" 2>/dev/null; }; AGENT_PID=""; return 0; }

indent() { sed 's/^/    | /'; }
assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_missing() { [[ $OUTPUT != *"$1"* ]] || { echo "  expected output NOT to contain: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_line() { grep -qxF -- "$1" <<<"$OUTPUT" || { echo "  expected a line that is exactly: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_no_line() { ! grep -qxF -- "$1" <<<"$OUTPUT" || { echo "  expected NO line that is exactly: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_status() { [[ $STATUS -eq $1 ]] || { echo "  expected exit $1, got $STATUS"; indent <<<"$OUTPUT"; return 1; }; }
calls() { cat "$STUB_DIR/calls" 2>/dev/null; }
assert_called() { calls | grep -qE -- "$1" || { echo "  expected a call matching: $1"; calls | indent; return 1; }; }
assert_not_called() { ! calls | grep -qE -- "$1" || { echo "  expected NO call matching: $1"; calls | indent; return 1; }; }

write_stubs() {
    cat >"$SB/bin/virsh" <<'STUB'
#!/usr/bin/env bash
# virsh -c <uri> <command> ...; for a revert and a destroy it saves how many requests the agent had
# seen by then, and a revert is what makes the agent answer at all.
shift 2
command=$1
shift
echo "virsh $command $*" >>"$STUB_DIR/calls"
case $command in
    snapshot-revert)
        [[ -e $STUB_DIR/revert-fails ]] && { echo "error: snapshot not found" >&2; exit 1; }
        wc -l <"$SB/requests.jsonl" >"$STUB_DIR/requests-at-revert"
        [[ -e $STUB_DIR/agent-stays-down ]] && exit 0
        python3 -I - "$SB/behaviour.json" <<'PY'
import json, sys
behaviour = json.load(open(sys.argv[1]))
behaviour["answers"] = True
json.dump(behaviour, open(sys.argv[1], "w"))
PY
        ;;
    destroy) wc -l <"$SB/requests.jsonl" >"$STUB_DIR/requests-at-destroy" ;;
esac
STUB
    chmod +x "$SB/bin/"*
}

# A fresh sandbox: a copy of guest/ laid out like the image, a context for the fake agent, stubs.
new_sandbox() {
    stop_agent
    SB="$(mktemp -d -p "$WORK")"
    export STUB_DIR="$SB/stub"
    mkdir -p "$SB/bin" "$STUB_DIR" "$SB/lv/images" "$SB/media" "$SB/build" "$SB/disk" "$SB/guestdir"
    cp -r "$REPO/guest" "$SB/guest"
    find "$SB/guest" -name __pycache__ -prune -exec rm -rf {} +
    PROFILE="$SB/guest/profiles/windows"
    : >"$SB/requests.jsonl"
    write_stubs
    AGENT_PORT=$(free_port)
    python3 -I "$TESTS/make_step_context.py" "$SB/ctx" "$AGENT_PORT" "$SB/lv" "$SB/media"
    WORK_ON_DISK="$SB/disk/ProgramData/abcdefgh"
    FACTS_OK='FACT system.model=Standard PC\r\nFACT os.hostname=DESKTOP-ABC1234\r\nEXITCODE 0\r\n'
    PROOF_REMOVED='RESULT write=ok\r\nRESULT eicar_present=False\r\nEXITCODE 0\r\n'
    PROOF_KEPT='RESULT write=ok\r\nRESULT eicar_present=True\r\nEXITCODE 0\r\n'
    behave_scripts "$FACTS_OK" "$PROOF_REMOVED"
    start_agent
}

# The fake agent plus two behaviours a guest can have that it has not: refusing to store a file
# ("refuse_store_of": a file name) and being slow to run a script ("execute_delay_s": {script: seconds}).
write_agent() {
    cat >"$WORK/agent.py" <<'PY'
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import fake_guest_agent as fake


class Agent(fake.Agent):
    def store(self, form, files):
        refused = self.behaviour().get("refuse_store_of", "")
        if refused and form.get("filepath", "").endswith(refused):
            self.reply(500, {"message": "disk full", "error_code": 500})
            return
        super().store(form, files)

    def execute(self, form, files):
        driver = self.driver_text(form.get("command", ""))
        for script, seconds in self.behaviour().get("execute_delay_s", {}).items():
            if script in driver:
                time.sleep(seconds)
        super().execute(form, files)


port, root, log_path, behaviour_path = sys.argv[2:6]
handler = type("Bound", (Agent,), {"root": Path(root), "log_path": Path(log_path), "behaviour_path": Path(behaviour_path)})
ThreadingHTTPServer(("127.0.0.1", int(port)), handler).serve_forever()
PY
}

start_agent() {
    write_agent
    python3 -I "$WORK/agent.py" "$TESTS" "$AGENT_PORT" "$SB/disk" "$SB/requests.jsonl" "$SB/behaviour.json" &
    AGENT_PID=$!
    wait_for_port "$AGENT_PORT"
}

# behave_with <key> <json value>: adds a behaviour to what behave_scripts wrote.
behave_with() {
    python3 -I - "$SB/behaviour.json" "$1" "$2" <<'PY'
import json, sys
path, key, value = sys.argv[1:4]
behaviour = json.load(open(path))
behaviour[key] = json.loads(value)
json.dump(behaviour, open(path, "w"))
PY
}

# behave_scripts <what guest-facts.ps1 prints> <what defender-proof.ps1 prints>; the agent answers
# only once the snapshot was restored.
behave_scripts() {
    python3 -I - "$SB/behaviour.json" "$1" "$2" <<'PY'
import json, sys
path, facts, proof = sys.argv[1:4]
decode = lambda text: text.encode().decode("unicode_escape")
json.dump(
    {"answers": False, "scripts": {"guest-facts.ps1": {"stdout": decode(facts)}, "defender-proof.ps1": {"stdout": decode(proof)}}},
    open(path, "w"),
)
PY
}

ctx_set() {
    python3 -I - "$SB/ctx/context.json" "$1" "$2" <<'PY'
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

defender() { ctx_set guest.options.defender "$1"; }

run_step() {
    OUTPUT="$(env -i PATH="$SB/bin:$PATH" HOME="$SB" STUB_DIR="$STUB_DIR" SB="$SB" \
        TT_GUEST_DIR="$SB/guestdir" TT_GUEST_JSON="$SB/ctx/guest.json" TT_PROFILE_DIR="$PROFILE" \
        TT_STATE_FILE="$SB/state.json" TT_BUILD_DIR="$SB/build" TT_CONTEXT_JSON="$SB/ctx/context.json" \
        TT_STEP=selftest-checks TT_BUILD_ID=checks-1 TT_LOG="$SB/log" \
        SELFTEST_AGENT_WAIT_SECONDS=3 SELFTEST_PROBE_SECONDS=0.05 "$@" \
        bash "$PROFILE/steps/selftest-checks" 2>&1 </dev/null)"
    STATUS=$?
}

# Python over the agent's request log: $1 is the body of a check(requests) function.
requests_satisfy() {
    python3 -I -c '
import json, sys
requests = [json.loads(line) for line in open(sys.argv[1])]
exec(sys.argv[2])
' "$SB/requests.jsonl" "$1" || { echo "  the agent's requests did not satisfy: $1"; indent <"$SB/requests.jsonl"; return 1; }
}

proof_lines() { grep -E '^PROOF ' <<<"$OUTPUT"; }
assert_proof_line() { proof_lines | grep -q -- "$1" || { echo "  no proof line matching: $1"; proof_lines | indent; return 1; }; }

# --- the order of things ---------------------------------------------------------------------------

test_the_snapshot_is_restored_first_with_the_running_flag() {
    new_sandbox
    run_step
    assert_status 0 &&
        assert_called '^virsh snapshot-revert alpha tartarus-clean --running$' &&
        [[ $(<"$STUB_DIR/requests-at-revert") -eq 0 ]]
}

test_the_agent_is_waited_for_before_anything_is_uploaded_or_run() {
    new_sandbox
    run_step
    assert_status 0 &&
        requests_satisfy "
kinds = [(r['method'], r['path']) for r in requests]
assert kinds[0] == ('GET', '/'), kinds
first_store = kinds.index(('POST', '/store'))
assert all(kind == ('GET', '/') for kind in kinds[:first_store]), kinds
"
}

test_the_facts_script_is_uploaded_and_run_before_the_defender_proof() {
    new_sandbox
    run_step
    assert_status 0 &&
        requests_satisfy "
stored = [r['form']['filepath'] for r in requests if r['path'] == '/store']
assert stored.index('C:\\\\ProgramData\\\\abcdefgh\\\\guest-facts.ps1') < stored.index('C:\\\\ProgramData\\\\abcdefgh\\\\defender-proof.ps1'), stored
runs = [r for r in requests if r['path'] == '/execute']
assert len(runs) == 2, runs
assert 'guest-facts.ps1' in runs[0]['driver'] and 'defender-proof.ps1' in runs[1]['driver'], runs
for run in runs:
    assert run['command'].startswith('C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File '), run
"
}

test_the_domain_is_destroyed_last_when_everything_worked() {
    new_sandbox
    run_step
    local total
    assert_status 0 && assert_called '^virsh destroy alpha$' || return 1
    total=$(wc -l <"$SB/requests.jsonl")
    [[ $(<"$STUB_DIR/requests-at-destroy") -eq $total ]] || { echo "  destroy came before the last request"; return 1; }
    [[ $(calls | tail -n1) == "virsh destroy alpha" ]] || { echo "  destroy was not the last call"; calls | indent; return 1; }
}

test_the_uploaded_scripts_are_removed_by_the_driver_that_runs_them() {
    new_sandbox
    run_step
    assert_status 0 &&
        requests_satisfy "
for run in [r for r in requests if r['path'] == '/execute']:
    assert 'Remove-Item' in run['driver'] and 'run.ps1' in run['driver'], run
"
}

# --- what the guest facts become --------------------------------------------------------------------

test_the_fact_and_giveaway_lines_of_the_guest_are_passed_through_unchanged() {
    new_sandbox
    behave_scripts 'FACT system.model=Standard PC (Q35 + ICH9, 2009)\r\nGIVEAWAY service: Remote Tartarus\r\nEXITCODE 0\r\n' "$PROOF_REMOVED"
    run_step
    assert_status 0 &&
        assert_line 'FACT system.model=Standard PC (Q35 + ICH9, 2009)' &&
        assert_line 'GIVEAWAY service: Remote Tartarus'
}

test_a_line_of_the_guest_that_only_looks_like_a_protocol_line_stays_log() {
    new_sandbox
    behave_scripts 'FACT os.hostname=PC\r\nPROOF defender=ok\r\nFACT novalue\r\nGIVEAWAY\r\nSTEP boo\r\nPROGRESS 100\r\nEXITCODE 0\r\n' "$PROOF_KEPT"
    defender false
    run_step
    assert_status 0 &&
        assert_line 'LOG PROOF defender=ok' && assert_line 'LOG FACT novalue' && assert_line 'LOG GIVEAWAY' &&
        assert_line 'LOG STEP boo' && assert_line 'LOG PROGRESS 100' &&
        [[ $(proof_lines | wc -l) -eq 1 ]]
}

test_a_proof_line_in_what_the_guest_wrote_to_stderr_stays_log() {
    new_sandbox
    python3 -I - "$SB/behaviour.json" <<'PY'
import json, sys
json.dump({"answers": False, "scripts": {
    "guest-facts.ps1": {"stdout": "FACT a=1\r\nEXITCODE 0\r\n"},
    "defender-proof.ps1": {"stdout": "RESULT eicar_present=False\r\n", "stderr": "boom\nPROOF defender=ok"},
}}, open(sys.argv[1], "w"))
PY
    defender false
    run_step
    assert_status 0 && assert_no_line 'PROOF defender=ok' && assert_contains 'PROOF defender=failed'
}

test_a_facts_script_that_printed_no_fact_fails_the_step() {
    new_sandbox
    behave_scripts 'nothing useful\r\nEXITCODE 0\r\n' "$PROOF_REMOVED"
    run_step
    assert_status 1 && assert_contains 'no facts' && assert_called '^virsh destroy alpha$'
}

test_a_facts_script_exit_code_of_a_leftover_native_command_is_tolerated() {
    new_sandbox
    behave_scripts 'FACT a=1\r\nEXITCODE 1\r\n' "$PROOF_REMOVED"
    run_step
    assert_status 0 && assert_line 'FACT a=1' && assert_line 'PROOF defender=ok'
}

test_a_facts_script_that_threw_fails_the_step() {
    new_sandbox
    behave_scripts 'FACT a=1\r\nRESULT error=boom\r\nEXITCODE 40\r\n' "$PROOF_REMOVED"
    run_step
    assert_status 1 && assert_contains 'guest-facts.ps1' && assert_called '^virsh destroy alpha$'
}

test_a_facts_script_that_reported_no_exit_code_fails_the_step() {
    new_sandbox
    behave_scripts 'FACT a=1\r\n' "$PROOF_REMOVED"
    run_step
    assert_status 1 && assert_called '^virsh destroy alpha$'
}

test_a_profile_without_a_facts_script_still_gets_its_defender_proof() {
    new_sandbox
    ctx_set profile.selftest.facts null
    run_step
    assert_status 0 && assert_line 'PROOF defender=ok' &&
        requests_satisfy "assert 'guest-facts.ps1' not in str([r.get('driver') for r in requests])"
}

# --- the defender proof ------------------------------------------------------------------------------

test_defender_on_and_the_file_removed_is_a_pass() {
    new_sandbox
    defender true
    behave_scripts "$FACTS_OK" "$PROOF_REMOVED"
    run_step
    assert_status 0 && assert_line 'PROOF defender=ok'
}

test_defender_on_and_the_file_kept_is_a_failure_that_says_what_was_expected_and_seen() {
    new_sandbox
    defender true
    behave_scripts "$FACTS_OK" "$PROOF_KEPT"
    run_step
    assert_status 0 && assert_proof_line '^PROOF defender=failed .*on.*removed.*still'
}

test_defender_off_and_the_file_kept_is_a_pass() {
    new_sandbox
    defender false
    behave_scripts "$FACTS_OK" "$PROOF_KEPT"
    run_step
    assert_status 0 && assert_line 'PROOF defender=ok'
}

test_defender_off_and_the_file_removed_is_a_failure_that_says_what_was_expected_and_seen() {
    new_sandbox
    defender false
    behave_scripts "$FACTS_OK" "$PROOF_REMOVED"
    run_step
    assert_status 0 && assert_proof_line '^PROOF defender=failed .*off.*kept.*removed'
}

test_a_guest_without_the_defender_option_is_taken_to_have_it_on() {
    new_sandbox
    python3 -I - "$SB/ctx/context.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
del data["guest"]["options"]["defender"]
json.dump(data, open(sys.argv[1], "w"))
PY
    run_step
    assert_status 0 && assert_line 'PROOF defender=ok'
}

test_an_agent_that_refuses_the_proof_script_fails_the_step_and_the_domain_is_still_destroyed() {
    new_sandbox
    behave_with refuse_store_of '"defender-proof.ps1"'
    run_step
    assert_status 1 && assert_contains 'defender-proof.ps1' && assert_called '^virsh destroy alpha$' &&
        assert_line 'FACT system.model=Standard PC' && [[ -z $(proof_lines) ]]
}

test_a_facts_script_that_takes_longer_than_the_limit_fails_the_step_and_the_domain_is_still_destroyed() {
    new_sandbox
    behave_with execute_delay_s '{"guest-facts.ps1": 3}'
    run_step SELFTEST_SCRIPT_TIMEOUT_SECONDS=1
    assert_status 1 && assert_called '^virsh destroy alpha$' && [[ -z $(proof_lines) ]]
}

test_a_proof_script_that_takes_longer_than_the_limit_fails_the_step_and_the_domain_is_still_destroyed() {
    new_sandbox
    behave_with execute_delay_s '{"defender-proof.ps1": 3}'
    run_step SELFTEST_SCRIPT_TIMEOUT_SECONDS=1
    assert_status 1 && assert_called '^virsh destroy alpha$' && [[ -z $(proof_lines) ]] &&
        assert_line 'FACT system.model=Standard PC'
}

test_the_result_lines_of_the_proof_script_are_shown_as_log() {
    new_sandbox
    run_step
    assert_status 0 && assert_line 'LOG RESULT eicar_present=False' && assert_line 'LOG RESULT write=ok'
}

test_a_proof_script_that_fails_is_a_failed_proof_not_a_failed_step() {
    new_sandbox
    behave_scripts "$FACTS_OK" 'RESULT error=access denied\r\nEXITCODE 40\r\n'
    run_step
    assert_status 0 && assert_proof_line '^PROOF defender=failed .*exit code 40' &&
        assert_line 'FACT system.model=Standard PC' && assert_called '^virsh destroy alpha$'
}

test_a_proof_script_that_reported_no_result_is_a_failed_proof() {
    new_sandbox
    behave_scripts "$FACTS_OK" 'EXITCODE 0\r\n'
    run_step
    assert_status 0 && assert_proof_line '^PROOF defender=failed .*no result'
}

test_the_proof_waits_fifteen_seconds_by_default_and_the_wait_can_be_set() {
    new_sandbox
    run_step
    assert_status 0 && requests_satisfy "
(proof,) = [r for r in requests if r['path'] == '/execute' and 'defender-proof.ps1' in r['driver']]
assert \"-WaitSeconds '15'\" in proof['driver'], proof['driver']
" || return 1
    new_sandbox
    run_step SELFTEST_PROOF_WAIT_SECONDS=3
    assert_status 0 && requests_satisfy "
(proof,) = [r for r in requests if r['path'] == '/execute' and 'defender-proof.ps1' in r['driver']]
assert \"-WaitSeconds '3'\" in proof['driver'], proof['driver']
"
}

test_the_test_string_never_goes_to_the_guest_as_one_literal() {
    new_sandbox
    run_step
    assert_status 0 || return 1
    local file
    for file in "$WORK_ON_DISK"/*; do
        ! grep -qi 'EICAR-STANDARD-ANTIVIRUS' "$file" || { echo "  $file holds the whole test string"; return 1; }
        ! grep -qi 'ANTIVIRUS-TEST-FILE' "$file" || { echo "  $file holds the whole test string"; return 1; }
    done
    grep -q 'eicarFirstHalf + \$eicarSecondHalf' "$WORK_ON_DISK/defender-proof.ps1" || { echo "  the proof script does not assemble the string"; return 1; }
}

# --- when something goes wrong ------------------------------------------------------------------------

test_an_agent_that_never_answers_fails_the_step_and_the_domain_is_still_destroyed() {
    new_sandbox
    touch "$STUB_DIR/agent-stays-down"
    run_step SELFTEST_AGENT_WAIT_SECONDS=1
    assert_status 1 && assert_contains 'agent' && assert_called '^virsh destroy alpha$' &&
        [[ -z $(proof_lines) ]] && [[ ! -e $WORK_ON_DISK ]]
}

test_a_snapshot_that_cannot_be_restored_fails_the_step_and_the_domain_is_still_destroyed() {
    new_sandbox
    touch "$STUB_DIR/revert-fails"
    run_step
    assert_status 1 && assert_contains 'snapshot' && assert_called '^virsh destroy alpha$' &&
        [[ ! -s $SB/requests.jsonl ]]
}

test_the_guests_password_is_never_printed() {
    new_sandbox
    run_step
    assert_status 0 && assert_missing "$PASSWORD"
}

# --- the step itself ----------------------------------------------------------------------------------

test_the_step_is_executable_bash_with_strict_mode_and_a_destroy_trap() {
    local step=$REPO/guest/profiles/windows/steps/selftest-checks
    [[ -x $step ]] || { echo "  not executable"; return 1; }
    head -n1 "$step" | grep -qx '#!/usr/bin/env bash' || { echo "  wrong shebang"; return 1; }
    grep -q '^set -uo pipefail' "$step" || { echo "  no strict mode"; return 1; }
    grep -qE "^trap .*vsh destroy" "$step" || { echo "  no trap that destroys the domain"; return 1; }
}

# With arguments, only the named tests run.
tests=("$@")
((${#tests[@]})) || mapfile -t tests < <(declare -F | awk '$3 ~ /^test_/ {print $3}')
for name in "${tests[@]}"; do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
