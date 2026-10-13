#!/usr/bin/env bash
# Tests cape/bin/finish-run: the helper inside the cape container that ends a running analysis by
# asking the guest agent to create the folder CAPE's analyzer watches for. The guest is replaced by
# a fake agent that records what it is asked; the helper itself runs for real on a loopback port.
set -uo pipefail

FINISH_RUN="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/cape/bin/finish-run"
WORK_DIR="$(mktemp -d)"
HELPER_PID=""
AGENT_PID=""
trap 'stop_helper; stop_agent; rm -rf "$WORK_DIR"' EXIT

# CAPE's analyzer looks for md5("cape-<task id>") under %SystemRoot%\Temp.
MD5_OF_TASK_7=e1b195e357506023df3e0309f42a438e
MD5_OF_TASK_144=f6dc66cb0ffda3e53542c6bdceb57c46

failures=0

free_port() { python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

# A stand-in for CAPE's agent: POST /mkdir answers like do_mkdir does, in the mode given.
write_fake_agent() {
    cat >"$WORK_DIR/fake_agent.py" <<'PY'
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

port, mode, log_path = int(sys.argv[1]), sys.argv[2], sys.argv[3]


class Agent(BaseHTTPRequestHandler):
    def do_POST(self):
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        with open(log_path, "a") as log:
            log.write(json.dumps({"path": self.path, "form": form}) + "\n")
        if mode == "hang":
            import time

            time.sleep(30)
        status, body = {
            "ok": (200, {"message": "Successfully created directory", "status_code": 200}),
            "refuse": (500, {"message": "Error creating directory", "error_code": 500, "traceback": "secret traceback"}),
            "bad_request": (400, {"message": "No dirpath has been provided", "error_code": 400}),
            "garbage": (200, None),
        }[mode]
        payload = b"<html>not json</html>" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Agent).serve_forever()
PY
}

start_agent() { # mode
    AGENT_PORT=$(free_port)
    : >"$WORK_DIR/agent.log"
    python3 -I "$WORK_DIR/fake_agent.py" "$AGENT_PORT" "$1" "$WORK_DIR/agent.log" &
    AGENT_PID=$!
    wait_for_port "$AGENT_PORT"
}

stop_agent() { [[ -n $AGENT_PID ]] && { kill "$AGENT_PID" 2>/dev/null; wait "$AGENT_PID" 2>/dev/null; }; AGENT_PID=""; return 0; }

wait_for_port() {
    local tries=0
    until python3 -I -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.5).close()' "$1" 2>/dev/null; do
        ((++tries > 50)) && { echo "nothing listens on $1" >&2; return 1; }
        sleep 0.1
    done
}

start_helper() { # agent-url [extra env assignments]
    local agent_url=$1
    shift
    HELPER_PORT=$(free_port)
    env CAPE_INTERNAL_IP=127.0.0.1 FINISH_RUN_PORT="$HELPER_PORT" GUEST_AGENT_URL="$agent_url" "$@" \
        python3 -I "$FINISH_RUN" >"$WORK_DIR/helper.log" 2>&1 &
    HELPER_PID=$!
    wait_for_port "$HELPER_PORT"
}

stop_helper() { [[ -n $HELPER_PID ]] && { kill "$HELPER_PID" 2>/dev/null; wait "$HELPER_PID" 2>/dev/null; }; HELPER_PID=""; return 0; }

# Prints "<status> <body>".
call() { # method path
    curl -s --path-as-is -m 20 -o "$WORK_DIR/body" -w '%{http_code}' -X "$1" "http://127.0.0.1:$HELPER_PORT$2"
    printf ' %s' "$(cat "$WORK_DIR/body")"
}

status_of() { call "$@" | cut -d' ' -f1; }

import_finish_run() { # python expression over the module `finish_run`
    python3 -I -c '
import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("finish_run", sys.argv[1])
spec = importlib.util.spec_from_loader("finish_run", loader)
finish_run = importlib.util.module_from_spec(spec)
loader.exec_module(finish_run)
print(eval(sys.argv[2]))' "$FINISH_RUN" "$1"
}

test_the_folder_name_is_the_md5_of_cape_dash_the_task_id() {
    [[ $(import_finish_run 'finish_run.completion_folder(7)') == "$MD5_OF_TASK_7" ]] &&
        [[ $(import_finish_run 'finish_run.completion_folder(144)') == "$MD5_OF_TASK_144" ]]
}

test_the_agent_is_asked_to_make_the_folder_under_the_windows_temp_directory() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    call POST /tasks/7/finish >/dev/null
    python3 -I -c '
import json, sys
(entry,) = [json.loads(line) for line in open(sys.argv[1])]
assert entry["path"] == "/mkdir", entry
assert entry["form"]["dirpath"] == ["C:\\Windows\\Temp\\" + sys.argv[2]], entry
' "$WORK_DIR/agent.log" "$MD5_OF_TASK_7"
}

test_a_created_folder_answers_200_finished() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    [[ $(call POST /tasks/7/finish) == '200 {"finished": true}' ]]
}

test_finishing_again_is_the_same_answer_and_asks_the_agent_again() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    call POST /tasks/7/finish >/dev/null
    [[ $(call POST /tasks/7/finish) == '200 {"finished": true}' ]] && [[ $(wc -l <"$WORK_DIR/agent.log") -eq 2 ]]
}

test_a_task_id_with_leading_zeros_names_the_same_folder() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    call POST /tasks/007/finish >/dev/null
    grep -qF "$MD5_OF_TASK_7" "$WORK_DIR/agent.log"
}

test_an_unreachable_agent_answers_502_with_an_error() {
    start_helper "http://127.0.0.1:$(free_port)"
    local answer
    answer=$(call POST /tasks/7/finish)
    [[ $answer == 502* && $answer == *'"error"'* && $answer == *unreachable* ]]
}

test_an_agent_that_refuses_answers_502_without_its_traceback() {
    start_agent refuse
    start_helper "http://127.0.0.1:$AGENT_PORT"
    local answer
    answer=$(call POST /tasks/7/finish)
    [[ $answer == 502* && $answer == *"Error creating directory"* && $answer != *traceback* ]]
}

test_an_agent_that_answers_400_is_a_502_too() {
    start_agent bad_request
    start_helper "http://127.0.0.1:$AGENT_PORT"
    [[ $(status_of POST /tasks/7/finish) == 502 ]]
}

test_an_agent_that_answers_something_unreadable_is_a_502() {
    start_agent garbage
    start_helper "http://127.0.0.1:$AGENT_PORT"
    [[ $(status_of POST /tasks/7/finish) == 502 ]]
}

test_an_agent_that_hangs_is_given_up_on_after_the_timeout() {
    start_agent hang
    start_helper "http://127.0.0.1:$AGENT_PORT" FINISH_RUN_AGENT_TIMEOUT=1
    local before=$SECONDS answer
    answer=$(call POST /tasks/7/finish)
    [[ $answer == 502* ]] && ((SECONDS - before < 8))
}

test_a_task_id_that_is_not_digits_answers_400_and_asks_the_agent_nothing() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    local id
    for id in abc 7a -1 %2e%2e 7%20 ''; do
        [[ $(status_of POST "/tasks/$id/finish") == 400 ]] || { echo "id '$id' was not refused" >&2; return 1; }
    done
    [[ ! -s $WORK_DIR/agent.log ]]
}

test_a_task_id_that_is_absurdly_long_answers_400() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    [[ $(status_of POST "/tasks/$(printf '9%.0s' {1..40})/finish") == 400 ]]
}

test_any_other_method_on_the_route_answers_404() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    local method
    for method in GET PUT DELETE; do
        [[ $(status_of "$method" /tasks/7/finish) == 404 ]] || { echo "$method was not refused" >&2; return 1; }
    done
    [[ ! -s $WORK_DIR/agent.log ]]
}

test_any_other_route_answers_404() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    local path
    for path in / /tasks /tasks/7 /tasks/7/finish/ /tasks/7/other /mkdir /../tasks/7/finish; do
        [[ $(status_of POST "$path") == 404 ]] || { echo "POST $path was not refused" >&2; return 1; }
    done
    [[ ! -s $WORK_DIR/agent.log ]]
}

test_answers_are_json() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    curl -s -m 20 -D "$WORK_DIR/headers" -o /dev/null -X POST "http://127.0.0.1:$HELPER_PORT/tasks/7/finish"
    grep -qi '^content-type: application/json' "$WORK_DIR/headers"
}

test_it_listens_on_the_given_address_only() {
    start_agent ok
    start_helper "http://127.0.0.1:$AGENT_PORT"
    [[ $(ss -ltnH "sport = :$HELPER_PORT" | awk '{print $4}') == "127.0.0.1:$HELPER_PORT" ]]
}

test_it_refuses_to_start_without_an_internal_address() {
    env -u CAPE_INTERNAL_IP python3 -I "$FINISH_RUN" >"$WORK_DIR/out" 2>&1
    [[ $? -ne 0 ]] && grep -q CAPE_INTERNAL_IP "$WORK_DIR/out"
}

test_the_log_names_the_request_and_the_agent_failure_but_not_the_agent_traceback() {
    start_agent refuse
    start_helper "http://127.0.0.1:$AGENT_PORT"
    call POST /tasks/7/finish >/dev/null
    grep -q '/tasks/7/finish' "$WORK_DIR/helper.log" && ! grep -q 'secret traceback' "$WORK_DIR/helper.log"
}

write_fake_agent
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_helper
    stop_agent
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
