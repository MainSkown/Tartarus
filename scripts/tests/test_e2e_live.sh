#!/usr/bin/env bash
# Tests live_events_are_in_the_final_index (scripts/lib/e2e-live.sh): live API calls are the final
# index's calls with the clock offset between the rounded live calibration and the exact final one.
# The index and the live summary are replaced by a document written where json_assert reads it.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-live.sh"

# What summary_with_index_ids builds from a real run: the live summary and the index's capemon calls.
summary_with_index_ids() { cp "$WORK_DIR/document.json" "$RESPONSE_FILE"; }

# Writes the document: the final calls are 20 calls of pid 180 half a second apart (six distinct, the rest one repeated call); the live ones are the same
# calls `offset` seconds early, minus those in `drop_live`, plus `extra_live` calls the index has not got.
write_document() { # offset drop_live extra_live drop_final
    python3 -I - "$@" >"$WORK_DIR/document.json" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone

offset, drop_live, extra_live, drop_final = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
start = datetime(2026, 10, 14, 15, 49, 0, tzinfo=timezone.utc)

def call(index, shift=0.0, name=None):
    name = name or (f"NtCall{index}" if index < 6 else "NtOpenKey")
    when = start + timedelta(seconds=index * 0.5 + shift)
    return f"180|{when.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z|api-call|{name}"

final_calls = [call(i) for i in range(20)][drop_final:]
live_calls = [call(i, -offset) for i in range(20)][drop_live:] + [call(i, -offset, "NtNeverInTheIndex") for i in range(extra_live)]
ids = [f"id{i}" for i in range(20)]
live = {"messages": [{"type": "events", "ids": ids, "calls": live_calls, "api": 20, "dropped": 0, "n": 20, "conn": 0}]}
print(json.dumps({"live": live, "final": ids, "final_calls": final_calls}))
PY
}

passes() { write_document "$@" && live_events_are_in_the_final_index "$WORK_DIR/summary.json" 1 >"$WORK_DIR/out" 2>&1; }
fails_saying() { # words, then document arguments
    local words=$1
    shift
    write_document "$@" && ! live_events_are_in_the_final_index "$WORK_DIR/summary.json" 1 >"$WORK_DIR/out" 2>&1 && grep -q "$words" "$WORK_DIR/out"
}

test_live_calls_a_constant_few_seconds_early_are_the_final_calls() { passes 4.8 0 0 0; }
test_live_calls_on_the_same_clock_are_the_final_calls() { passes 0 0 0 0; }
test_the_offset_is_reported() { passes 4.8 0 0 0 && grep -q "4.8 s off" "$WORK_DIR/out"; }
test_a_live_call_the_index_does_not_have_is_caught() { fails_saying "no matching call in the final index" 4.8 0 2 0; }
test_a_final_call_that_never_arrived_live_is_caught() { fails_saying "never arrived live" 4.8 3 0 0; }
test_an_offset_beyond_the_rounded_calibration_is_caught() { fails_saying "off the final ones" 12 0 0 0; }

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; cat "$WORK_DIR/out" 2>/dev/null | head -3; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
