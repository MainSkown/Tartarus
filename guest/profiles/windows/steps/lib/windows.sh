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

# The guest's provisioning log, read while the guest is still writing it. Only complete lines are
# kept: Add-Content may be mid-write when the file is read, and the half line is whole next round.
GUEST_LOG_LINES=()
GUEST_LOG_LINES_SHOWN=0
GUEST_LOG_TIMESTAMP='[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} +'

# fetch_guest_log_lines <log name>: status 1, quietly, when the guest's file cannot be read right now
# (not written yet, or held open by the writer): the caller asks again next round.
fetch_guest_log_lines() {
    local fetched line
    fetched=$(mktemp "$TT_BUILD_DIR/guest-log.XXXXXX")
    if ! guest_agent retrieve "$1" "$fetched" 2>/dev/null; then
        rm -f "$fetched"
        return 1
    fi
    GUEST_LOG_LINES=()
    while IFS= read -r line; do
        GUEST_LOG_LINES+=("$line")
    done < <(tr -d '\r\0' <"$fetched")
    rm -f "$fetched"
}

# show_new_guest_log_lines: the lines of GUEST_LOG_LINES not shown before, as LOG lines.
show_new_guest_log_lines() {
    local index line
    for ((index = GUEST_LOG_LINES_SHOWN; index < ${#GUEST_LOG_LINES[@]}; index++)); do
        line=${GUEST_LOG_LINES[index]}
        [[ -z $line ]] || log "guest: $line"
    done
    ((${#GUEST_LOG_LINES[@]} <= GUEST_LOG_LINES_SHOWN)) || GUEST_LOG_LINES_SHOWN=${#GUEST_LOG_LINES[@]}
}

# guest_log_plan: how many steps provision.ps1 announced in its "PLAN <n>" line, 0 before that.
guest_log_plan() {
    local line
    for line in "${GUEST_LOG_LINES[@]}"; do
        if [[ $line =~ ^${GUEST_LOG_TIMESTAMP}PLAN\ ([0-9]+)$ ]]; then
            echo "${BASH_REMATCH[1]}"
            return
        fi
    done
    echo 0
}

# guest_log_steps_done: the steps that ended, ok or FAILED (a failed step is recorded, not retried).
guest_log_steps_done() {
    local line ended=0
    for line in "${GUEST_LOG_LINES[@]}"; do
        [[ $line =~ ^${GUEST_LOG_TIMESTAMP}(ok|FAILED)([^A-Za-z]|$) ]] && ((ended++))
    done
    echo "$ended"
}

# guest_log_current_step: the name of the newest step the log says started, empty before the first.
guest_log_current_step() {
    local index
    for ((index = ${#GUEST_LOG_LINES[@]} - 1; index >= 0; index--)); do
        if [[ ${GUEST_LOG_LINES[index]} =~ ^${GUEST_LOG_TIMESTAMP}STEP\ (.+)$ ]]; then
            echo "${BASH_REMATCH[1]}"
            return
        fi
    done
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
    output=$(guest_agent run "$script" --with defender-settings.ps1 --with security-ui.ps1 --timeout "$DEFENDER_SCRIPT_TIMEOUT_S")
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
