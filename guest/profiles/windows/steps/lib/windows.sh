#!/usr/bin/env bash
# Sourced by the Windows profile's steps after the generic lib/common.sh: names from the profile's
# table, the calls to the guest's agent, and the two ways a step ends early (paused for the analyst,
# failed). Values reach python through files and arguments, never pasted into a command.

WINDOWS_STEPS_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PAUSED_EXIT_CODE=75
# Less than the pipeline's own timeout for these steps, so a hung script reports before it is killed.
DEFENDER_SCRIPT_TIMEOUT_S=540

# shellcheck source=../../../../steps/lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/../../../../steps/lib/common.sh"

guest_agent() { python3 -I "$WINDOWS_STEPS_LIB/guest_agent.py" "$@"; }

agent_answers() { guest_agent answers; }

# profile_name <key>: a value of the profile's names table (the neutral names the guest uses).
profile_name() {
    python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1] + "/names.json"))[sys.argv[2]])' \
        "$TT_PROFILE_DIR" "$1"
}

# result_field <step output> <key>: the value of the script's "RESULT key=value" line.
result_field() { sed -n "s/^LOG RESULT $2=//p" <<<"$1" | head -n1 | tr -d '\r'; }

# log_guest_file <file>: every line of a file fetched from the guest, as a LOG line, so that a line
# of it can never be taken for a protocol line.
log_guest_file() {
    local line
    while IFS= read -r line || [[ -n $line ]]; do
        [[ -z $line ]] || log "guest: $line"
    done < <(tr -d '\r\0' <"$1")
}

pause_for_analyst() {
    printf 'PAUSE %s\n' "${*//$'\n'/ }"
    exit "$PAUSED_EXIT_CODE"
}

# result_summary <step output>: the script's RESULT lines as "key=value; key=value".
result_summary() {
    sed -n 's/^LOG RESULT //p' <<<"$1" | paste -sd ';' - | sed 's/;/; /g'
}

# run_defender_script <script> <what to ask the analyst when the toggle cannot be found>
# Runs one of the profile's Defender scripts in the guest and maps its exit code: 0 done and
# verified, 10 the Windows Security toggle was not found (the analyst does it by hand), 20 the
# verification failed, 30 a proof step failed.
run_defender_script() {
    local script=$1 instructions=$2 output code
    output=$(guest_agent run "$script" --with defender-settings.ps1 --timeout "$DEFENDER_SCRIPT_TIMEOUT_S")
    code=$?
    [[ -z $output ]] || printf '%s\n' "$output"
    case $code in
        0) log "$script finished and verified it" ;;
        10) pause_for_analyst "$instructions" ;;
        20) fail "$script could not verify the change (exit code 20): $(result_summary "$output")" ;;
        30) fail "$script's proof failed (exit code 30): $(result_summary "$output")" ;;
        70) fail "the guest agent could not be used to run $script" ;;
        71) fail "$script reported no exit code" ;;
        *) fail "$script ended with exit code $code: $(result_summary "$output")" ;;
    esac
}
