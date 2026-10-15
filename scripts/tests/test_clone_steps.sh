#!/usr/bin/env bash
# Tests the clone pipeline's two steps: the generic `copy` (guest/steps/copy) and the Windows
# profile's `reconfigure`. Each runs as the sequencer would run it, with the TT_* environment and
# a context.json made from the engine's own fixtures. copy runs against stub virsh/qemu-img/cp
# over scratch files; reconfigure talks to a fake guest agent on loopback with a stub virsh.
# shellcheck disable=SC2016  # stubs and python snippets are written with single quotes on purpose
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTS="$REPO/scripts/tests"
STEPS="$REPO/guest/steps"
WORK="$(mktemp -d)"
AGENT_PID=""
trap 'stop_agent; rm -rf "$WORK"' EXIT

failures=0
OUTPUT=""
STATUS=0

run_test() {
    local name=$1
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

indent() { sed 's/^/    | /'; }
assert_contains() { [[ $OUTPUT == *"$1"* ]] || { echo "  expected output to contain: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_missing() { [[ $OUTPUT != *"$1"* ]] || { echo "  expected output NOT to contain: $1"; indent <<<"$OUTPUT"; return 1; }; }
assert_status() { [[ $STATUS -eq $1 ]] || { echo "  expected exit $1, got $STATUS"; indent <<<"$OUTPUT"; return 1; }; }
calls() { cat "$LOG" 2>/dev/null; }
assert_called() { calls | grep -qE -- "$1" || { echo "  expected a call matching: $1"; calls | indent; return 1; }; }
assert_not_called() { ! calls | grep -qE -- "$1" || { echo "  expected NO call matching: $1"; calls | indent; return 1; }; }
assert_file_is() { [[ -f $1 && $(<"$1") == "$2" ]] || { echo "  expected $1 to hold '$2', it holds '$(cat "$1" 2>/dev/null)'"; return 1; }; }
assert_absent() { [[ ! -e $1 ]] || { echo "  expected $1 not to exist"; return 1; }; }

free_port() { python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
stop_agent() { [[ -n $AGENT_PID ]] && { kill "$AGENT_PID" 2>/dev/null; wait "$AGENT_PID" 2>/dev/null; }; AGENT_PID=""; return 0; }

# --- a scratch host for `copy` -----------------------------------------------------------------

SOURCE_BASE_BYTES=$((80 * 1024 * 1024 * 1024))

# Lays out a registry-less host: a ready source "beta" with a base disk, a snapshot overlay on top
# of it, a snapshot memory file and an nvram; the clone "alpha" has nothing yet. $WORLD/context.json
# is what the engine would write for the clone.
new_copy_world() {
    WORLD="$(mktemp -d -p "$WORK")"
    LOG="$WORLD/calls"
    : >"$LOG"
    S="$WORLD/state"
    IMAGES="$WORLD/libvirt/images"
    NVRAMS="$WORLD/libvirt/nvram"
    mkdir -p "$WORLD"/{bin,build,profile,media,registry} "$S" "$IMAGES" "$NVRAMS"
    BASE="$IMAGES/beta.qcow2"
    OVERLAY="$IMAGES/beta.1792021253"
    MEMORY="$IMAGES/beta-clean.mem"
    SOURCE_NVRAM="$NVRAMS/beta_VARS.fd"
    printf 'base image bytes' >"$BASE"
    printf 'overlay bytes' >"$OVERLAY"
    printf 'memory image bytes' >"$MEMORY"
    printf 'nvram bytes' >"$SOURCE_NVRAM"
    CLONE_DISK="$IMAGES/alpha.qcow2"
    CLONE_NVRAM="$NVRAMS/alpha_VARS.fd"
    write_copy_stubs
    describe_source_domain "$OVERLAY" "$SOURCE_NVRAM"
    describe_chain "$OVERLAY" "$BASE"
    python3 -I - "$REPO" "$WORLD" <<'PY'
import json, sys
from dataclasses import replace
from pathlib import Path

repo, world = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(repo / "cape"), str(repo / "cape" / "tests")]
from fixtures.guest_samples import make_guest
from fixtures.profile_samples import sample_profile

source = replace(make_guest("beta", ip="192.168.150.10"), state="ready", work_dir="C:\\ProgramData\\abcdefgh")
clone = replace(
    make_guest("alpha", ip="192.168.150.11", kind="clone", cloned_from="beta"),
    work_dir=source.work_dir,
)
view = sample_profile("windows").to_dict()
view.pop("adoption", None)
context = {
    "guest": clone.to_dict(),
    "profile": view,
    "source": source.to_dict(),
    "build": {"id": "b1", "kind": "clone", "steps": ["copy"]},
    "host": {
        "subnet": "192.168.150.0/24", "gateway": "192.168.150.1",
        "registry_root": str(world / "registry"), "libvirt_dir": str(world / "libvirt"),
        "media_dir": str(world / "media"), "registration_dir": str(world / "libvirt/tartarus/kvm.conf.d"),
        "libvirt_uri": "qemu:///system",
    },
}
(world / "context.json").write_text(json.dumps(context, indent=2))
PY
}

write_copy_stubs() {
    cat >"$WORLD/bin/virsh" <<'STUB'
#!/usr/bin/env bash
echo "virsh $*" >>"$STUB_LOG"
shift 2
command=$1 domain=$2
case $command in
    domstate) [[ -e $STUB_DIR/domain-$domain.xml ]] || exit 1; cat "$STUB_DIR/domstate-$domain" 2>/dev/null || echo "shut off" ;;
    dumpxml) cat "$STUB_DIR/domain-$domain.xml" 2>/dev/null || exit 1 ;;
    *) echo "unexpected virsh $command" >&2; exit 1 ;;
esac
STUB
    cat >"$WORLD/bin/qemu-img" <<'STUB'
#!/usr/bin/env bash
echo "qemu-img $*" >>"$STUB_LOG"
case $1 in
    info)
        file="$STUB_DIR/chain-$(basename "${@: -1}").json"
        [[ -f $file ]] || { echo "qemu-img: cannot open ${*: -1}" >&2; exit 1; }
        # Without --backing-chain qemu-img describes the top image alone.
        [[ " $* " == *" --backing-chain "* ]] && cat "$file" || python3 -I -c '"'"'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))[0]))'"'"' "$file" ;;
    convert)
        target=${@: -1}
        source=${@: -2:1}
        if [[ -e $STUB_DIR/convert-fails ]]; then printf 'half of ' >"$target"; echo "qemu-img: boom" >&2; exit 1; fi
        PATH=/usr/bin:/bin cp "$source" "$target" ;;
    *) echo "unexpected qemu-img $1" >&2; exit 1 ;;
esac
STUB
    cat >"$WORLD/bin/cp" <<'STUB'
#!/bin/sh
echo "cp $*" >>"$STUB_LOG"
[ -e "$STUB_DIR/cp-fails" ] && { echo "cp: boom" >&2; exit 1; }
exec /usr/bin/cp "$@"
STUB
    printf '#!/usr/bin/env bash\necho "sleep $*" >>"$STUB_LOG"\n' >"$WORLD/bin/sleep"
    chmod +x "$WORLD"/bin/*
}

# describe_source_domain <current disk> <nvram>: what `virsh dumpxml beta` answers.
describe_source_domain() {
    cat >"$S/domain-beta.xml" <<XML
<domain type='kvm'>
  <name>beta</name>
  <os><nvram>$2</nvram></os>
  <devices>
    <disk type='file' device='cdrom'><target dev='sdb' bus='sata'/></disk>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='$1'/>
      <target dev='sda' bus='sata'/>
    </disk>
  </devices>
</domain>
XML
}

# describe_chain <top file> <deepest file> [deepest virtual size] [middle file...]: what
# `qemu-img info --backing-chain --output=json <top>` answers: the top first, the deepest last.
# Only the deepest image may have a size other than the guest's recorded one.
describe_chain() {
    local top=$1 deepest=$2 size=${3:-$SOURCE_BASE_BYTES}
    shift 3 2>/dev/null || shift $#
    python3 -I - "$S/chain-$(basename "$top").json" "$size" "$top" "$@" "$deepest" <<'PY'
import json, sys
out, size, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
chain = [{"filename": f, "format": "qcow2", "virtual-size": 80 * 1024**3} for f in files]
chain[-1]["virtual-size"] = size
for upper, lower in zip(chain, chain[1:]):
    upper["backing-filename"] = lower["filename"]
    upper["full-backing-filename"] = lower["filename"]
json.dump(chain, open(out, "w"))
PY
}

run_copy() {
    OUTPUT="$(env -i PATH="$WORLD/bin:/usr/bin:/bin" HOME="$WORLD" \
        TT_GUEST_DIR="$WORLD/registry/alpha" TT_PROFILE_DIR="$WORLD/profile" TT_BUILD_DIR="$WORLD/build" \
        TT_CONTEXT_JSON="$WORLD/context.json" TT_STATE_FILE="$WORLD/build/build.json" TT_STEP=copy \
        TT_BUILD_ID=b1 TT_LOG="$WORLD/build/log" STUB_DIR="$S" STUB_LOG="$LOG" "$STEPS/copy" 2>&1 </dev/null)"
    STATUS=$?
}

checksums_of_source() { (cd "$WORLD/libvirt" && sha256sum images/beta* nvram/beta_VARS.fd | sort); }

# --- copy ----------------------------------------------------------------------------------------

test_copy_converts_the_base_disk_and_not_the_overlay_on_top_of_it() {
    new_copy_world
    run_copy
    assert_status 0 &&
        assert_called "qemu-img convert -O qcow2 $BASE $CLONE_DISK.part" &&
        assert_not_called "convert .*$OVERLAY" &&
        assert_file_is "$CLONE_DISK" "base image bytes"
}

test_copy_takes_the_deepest_file_of_a_longer_chain() {
    new_copy_world
    local middle="$IMAGES/beta.middle"
    printf 'middle bytes' >"$middle"
    describe_chain "$OVERLAY" "$BASE" "$SOURCE_BASE_BYTES" "$middle"
    run_copy
    assert_status 0 && assert_called "convert -O qcow2 $BASE " && assert_file_is "$CLONE_DISK" "base image bytes"
}

test_copy_copies_a_disk_that_has_no_overlay() {
    new_copy_world
    describe_source_domain "$BASE" "$SOURCE_NVRAM"
    describe_chain "$BASE" "$BASE" "$SOURCE_BASE_BYTES"
    python3 -I - "$S/chain-beta.qcow2.json" <<'PY'
import json, sys
chain = json.load(open(sys.argv[1]))
json.dump(chain[:1], open(sys.argv[1], "w"))
PY
    run_copy
    assert_status 0 && assert_file_is "$CLONE_DISK" "base image bytes"
}

test_copy_resolves_a_backing_file_that_the_chain_names_relative_to_its_overlay() {
    new_copy_world
    python3 -I - "$S/chain-$(basename "$OVERLAY").json" <<'PY'
import json, sys
chain = json.load(open(sys.argv[1]))
chain[-1]["filename"] = "beta.qcow2"
json.dump(chain, open(sys.argv[1], "w"))
PY
    run_copy
    assert_status 0 && assert_called "convert -O qcow2 $BASE " && assert_file_is "$CLONE_DISK" "base image bytes"
}

test_copy_falls_back_to_the_filename_of_the_last_image_when_the_chain_has_no_resolved_name() {
    new_copy_world
    python3 -I - "$S/chain-$(basename "$OVERLAY").json" <<'PY'
import json, sys
chain = json.load(open(sys.argv[1]))
for image in chain:
    image.pop("full-backing-filename", None)
json.dump(chain, open(sys.argv[1], "w"))
PY
    run_copy
    assert_status 0 && assert_called "convert -O qcow2 $BASE " && assert_file_is "$CLONE_DISK" "base image bytes"
}

test_copy_copies_the_nvram_of_the_source_domain() {
    new_copy_world
    chmod 640 "$SOURCE_NVRAM"
    run_copy
    assert_status 0 && assert_file_is "$CLONE_NVRAM" "nvram bytes" &&
        [[ $(stat -c %a "$CLONE_NVRAM") == 640 ]]
}

test_copy_creates_the_clones_directories_when_the_source_keeps_its_files_elsewhere() {
    new_copy_world
    mkdir -p "$WORLD/elsewhere"
    mv "$SOURCE_NVRAM" "$WORLD/elsewhere/beta_VARS.fd"
    describe_source_domain "$OVERLAY" "$WORLD/elsewhere/beta_VARS.fd"
    rmdir "$NVRAMS"
    run_copy
    assert_status 0 && assert_file_is "$CLONE_NVRAM" "nvram bytes"
}

test_copy_says_that_no_tpm_state_is_copied() {
    new_copy_world
    run_copy
    assert_status 0 && assert_contains "LOG " && assert_contains "TPM"
}

test_copy_reports_progress_in_order_and_ends_at_100() {
    new_copy_world
    run_copy
    assert_status 0 || return 1
    [[ $(grep '^PROGRESS' <<<"$OUTPUT" | tr '\n' ' ') == "PROGRESS 0 PROGRESS 10 PROGRESS 90 PROGRESS 100 " ]] ||
        { echo "  unexpected progress:"; grep '^PROGRESS' <<<"$OUTPUT" | indent; return 1; }
}

test_copy_refuses_a_running_source_and_copies_nothing() {
    new_copy_world
    echo running >"$S/domstate-beta"
    run_copy
    assert_status 1 && assert_contains "beta" && assert_contains "running" &&
        assert_not_called "convert" && assert_absent "$CLONE_DISK.part" && assert_absent "$CLONE_DISK" && assert_absent "$CLONE_NVRAM"
}

test_copy_refuses_a_paused_source() {
    new_copy_world
    echo paused >"$S/domstate-beta"
    run_copy
    assert_status 1 && assert_contains "paused" && assert_not_called "convert"
}

test_copy_fails_clearly_when_the_source_has_no_domain() {
    new_copy_world
    rm "$S/domain-beta.xml"
    run_copy
    assert_status 1 && assert_contains "beta" && assert_not_called "convert"
}

test_copy_fails_clearly_when_the_context_has_no_source() {
    new_copy_world
    python3 -I - "$WORLD/context.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
data["source"] = None
json.dump(data, open(sys.argv[1], "w"))
PY
    run_copy
    assert_status 1 && assert_contains "source" && assert_not_called "convert"
}

test_copy_fails_when_the_base_disk_is_not_the_size_the_clone_is_recorded_with() {
    new_copy_world
    describe_chain "$OVERLAY" "$BASE" $((64 * 1024 * 1024 * 1024))
    run_copy
    assert_status 1 && assert_contains "64 GiB" && assert_contains "80 GiB" &&
        assert_not_called "convert" && assert_absent "$CLONE_DISK"
}

test_copy_fails_before_the_long_convert_when_the_source_nvram_is_missing() {
    new_copy_world
    rm "$SOURCE_NVRAM"
    run_copy
    assert_status 1 && assert_contains "$SOURCE_NVRAM" && assert_not_called "convert" && assert_absent "$CLONE_DISK"
}

test_copy_never_leaves_the_clone_disk_in_place_before_the_copy_is_whole() {
    new_copy_world
    touch "$S/convert-fails"
    run_copy
    assert_status 1 && assert_contains "convert" && assert_absent "$CLONE_DISK" && assert_absent "$CLONE_DISK.part" && assert_absent "$CLONE_NVRAM"
}

test_copy_keeps_an_earlier_complete_copy_when_a_new_attempt_fails() {
    new_copy_world
    printf 'earlier copy' >"$CLONE_DISK"
    touch "$S/convert-fails"
    run_copy
    assert_status 1 && assert_file_is "$CLONE_DISK" "earlier copy" && assert_absent "$CLONE_DISK.part"
}

test_copy_removes_the_disk_it_made_when_the_nvram_copy_then_fails() {
    new_copy_world
    touch "$S/cp-fails"
    run_copy
    assert_status 1 && assert_called "convert" && assert_absent "$CLONE_DISK" && assert_absent "$CLONE_NVRAM" && assert_absent "$CLONE_NVRAM.part"
}

test_copy_replaces_an_earlier_copy_and_a_stale_partial_one_on_a_rerun() {
    new_copy_world
    printf 'earlier copy' >"$CLONE_DISK"
    printf 'stale partial' >"$CLONE_DISK.part"
    printf 'earlier firmware' >"$CLONE_NVRAM"
    run_copy
    assert_status 0 && assert_file_is "$CLONE_DISK" "base image bytes" && assert_file_is "$CLONE_NVRAM" "nvram bytes" &&
        assert_absent "$CLONE_DISK.part" && assert_absent "$CLONE_NVRAM.part"
}

test_copy_runs_twice_with_the_same_result() {
    new_copy_world
    run_copy
    run_copy
    assert_status 0 && assert_file_is "$CLONE_DISK" "base image bytes" && assert_file_is "$CLONE_NVRAM" "nvram bytes"
}

test_copy_never_changes_a_file_of_the_source() {
    new_copy_world
    local before after
    before=$(checksums_of_source)
    run_copy
    after=$(checksums_of_source)
    assert_status 0 && [[ $before == "$after" ]] || { echo "  the source's files changed"; return 1; }
}

test_copy_leaves_the_snapshot_memory_file_alone() {
    new_copy_world
    run_copy
    assert_status 0 && assert_not_called "beta-clean.mem" && assert_not_called "$MEMORY" && assert_absent "$IMAGES/alpha-clean.mem"
}

test_copy_writes_only_to_the_clones_own_paths() {
    new_copy_world
    run_copy
    assert_status 0 || return 1
    local line target
    while read -r line; do
        case $line in
            "qemu-img convert"* | "cp "*) target=${line##* }; [[ $target == "$CLONE_DISK.part" || $target == "$CLONE_NVRAM.part" ]] || { echo "  wrote to $target"; return 1; } ;;
        esac
    done <"$LOG"
}

test_copy_names_no_operating_system() {
    [[ -x $STEPS/copy ]] && ! grep -qiE 'windows|defender|powershell|wiminfo|bitlocker' "$STEPS/copy"
}

# --- a scratch host for `reconfigure` --------------------------------------------------------------

GUEST_ADDRESS=127.0.0.5       # the address the clone will be given; the copy is not there at first
LEASED_ADDRESS=127.0.0.7      # the address DHCP gave the copy
CLONE_NAME=DESKTOP-ABC1234

# A fake agent that, unlike scripts/tests/fake_guest_agent.py, answers on every loopback address,
# only on those the scenario lists (before and after the Apply script ran), hands out scripted
# outputs one call after another and writes the files a script would have written.
write_phase_agent() {
    cat >"$WORK/phase_agent.py" <<'PY'
import re
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import fake_guest_agent as fake


class Agent(fake.Agent):
    applied = False
    gets = 0
    counts: dict = {}

    def alive(self):
        listed = self.behaviour().get("alive_after_apply" if type(self).applied else "alive_before_apply")
        return listed is None or self.host() in listed

    def host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def record(self, **entry):
        super().record(host=self.host(), **entry)

    def do_GET(self):
        if not self.alive():
            return
        type(self).gets += 1
        if self.gets <= self.behaviour().get("unready_polls", 0):
            self.record()
            self.reply(503, {"message": "not ready", "error_code": 503})
            return
        super().do_GET()

    def do_POST(self):
        if self.alive():
            super().do_POST()

    def execute(self, form, files):
        driver = self.driver_text(form.get("command", ""))
        behaviour = self.behaviour()
        sequences = [(key, outputs) for key, outputs in behaviour.get("sequences", {}).items() if key in driver]
        if sequences:
            key, outputs = sequences[0]
            index = self.counts.get(key, 0)
            self.counts[key] = index + 1
            self.reply(200, {"message": "Successfully executed command", "status_code": 200,
                             "stdout": outputs[min(index, len(outputs) - 1)], "stderr": ""})
        else:
            super().execute(form, files)
        for key, written in behaviour.get("on_execute_write", {}).items():
            if key in driver:
                target = fake.guest_path(self.root, written["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                token = re.search(r"-Token '([^']*)'", driver)
                target.write_text(written["content"].replace("{token}", token.group(1) if token else ""))
        if "-Phase 'Apply'" in driver:
            type(self).applied = True


port, root, log_path, behaviour_path = sys.argv[2:6]
handler = type("Bound", (Agent,), {"root": Path(root), "log_path": Path(log_path), "behaviour_path": Path(behaviour_path), "counts": {}})
ThreadingHTTPServer(("0.0.0.0", int(port)), handler).serve_forever()
PY
}

write_reconfigure_stubs() {
    cat >"$SB/bin/virsh" <<'STUB'
#!/usr/bin/env bash
shift 2
command=$1
shift
echo "virsh $command $*" >>"$STUB_DIR/calls"
case $command in
    dominfo) [[ -e $STUB_DIR/defined ]] || exit 1 ;;
    domstate) [[ -e $STUB_DIR/running ]] && echo running || echo "shut off" ;;
    start) [[ -e $STUB_DIR/start-fails ]] && exit 1; touch "$STUB_DIR/running" ;;
    shutdown | destroy) rm -f "$STUB_DIR/running" ;;
    net-dhcp-leases)
        echo " Expiry Time           MAC address         Protocol   IP address          Hostname   Client ID or DUID"
        echo "-------------------------------------------------------------------------------------------------------"
        echo " 2026-10-15 15:30:00   00:14:22:aa:aa:aa   ipv4       192.168.150.101/24  other      -"
        next=$(head -n1 "$STUB_DIR/leases" 2>/dev/null)
        [[ $(wc -l <"$STUB_DIR/leases") -gt 1 ]] && sed -i 1d "$STUB_DIR/leases"
        [[ -e $STUB_DIR/ipv6-lease ]] && echo " 2026-10-15 15:40:00   $(<"$STUB_DIR/mac")   ipv6       2001:db8::5/64  DESKTOP-OLD   01:aa"
        if [[ -e $STUB_DIR/older-lease && -n $next && $next != - ]]; then
            echo " 2026-10-15 15:10:00   $(<"$STUB_DIR/mac")   ipv4       127.0.0.9/24  DESKTOP-OLD   01:aa"
        fi
        if [[ -n $next && $next != - ]]; then
            echo " 2026-10-15 15:20:00   00:14:22:00:00:01   ipv4       192.168.150.99/24  stale      -"
            echo " 2026-10-15 15:30:00   $(<"$STUB_DIR/mac")   ipv4       $next/24  DESKTOP-OLD   01:aa"
        fi ;;
    *) echo "unexpected virsh $command" >&2; exit 1 ;;
esac
STUB
    chmod +x "$SB/bin/virsh"
}

new_sandbox() {
    stop_agent
    SB="$(mktemp -d -p "$WORK")"
    export STUB_DIR="$SB/stub"
    mkdir -p "$SB/bin" "$STUB_DIR" "$SB/lv/images" "$SB/media" "$SB/build" "$SB/disk" "$SB/guestdir"
    cp -r "$REPO/guest" "$SB/guest"
    find "$SB/guest" -name __pycache__ -prune -exec rm -rf {} +
    PROFILE="$SB/guest/profiles/windows"
    touch "$STUB_DIR/defined"
    printf -- '-\n' >"$STUB_DIR/leases"
    write_reconfigure_stubs
    AGENT_PORT=$(free_port)
    python3 -I "$TESTS/make_step_context.py" "$SB/ctx" "$AGENT_PORT" "$SB/lv" "$SB/media"
    ctx_set build.kind '"clone"'
    ctx_set guest.ip "\"$GUEST_ADDRESS\""
    CTX_MAC=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["guest"]["machine"]["mac"])' "$SB/ctx/context.json")
    printf '%s' "$CTX_MAC" >"$STUB_DIR/mac"
    ctx_set source '{"ip": "127.0.0.250"}'
    WORK_ON_DISK="$SB/disk/ProgramData/abcdefgh"
    LOG_FILE=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["log_file"])' "$PROFILE/names.json")
    TOKEN=""
    LEASES="$LEASED_ADDRESS"
    BEFORE_NAME=DESKTOP-OLD BEFORE_IP=$LEASED_ADDRESS BEFORE_GUID=guid-before BEFORE_BOOT=boot-1
    AFTER_NAME=${CLONE_NAME^^} AFTER_IP=$GUEST_ADDRESS AFTER_GUID=guid-after AFTER_BOOT=boot-2
    OLD_BOOT_REPORTS=0 UNREADY_POLLS=0 SCENARIO_ALIVE_BEFORE="$LEASED_ADDRESS" APPLY_WRITES_LOG=yes REPORT_EXIT_CODE=0
    GUEST_LOG_TEXT="static address set"
    echo '{}' >"$SB/behaviour.json"
    : >"$SB/requests.jsonl"
    write_phase_agent
    python3 -I "$WORK/phase_agent.py" "$TESTS" "$AGENT_PORT" "$SB/disk" "$SB/requests.jsonl" "$SB/behaviour.json" &
    AGENT_PID=$!
    wait_for_port "$AGENT_PORT"
}

wait_for_port() {
    local tries=0
    until python3 -I -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.5).close()' "$1" 2>/dev/null; do
        ((++tries > 50)) && { echo "nothing listens on $1" >&2; return 1; }
        sleep 0.1
    done
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

# Writes the fake agent's behaviour file from the scenario variables set so far.
write_behaviour() {
    printf '%s\n' "$LEASES" | tr ' ' '\n' >"$STUB_DIR/leases"
    python3 -I - "$SB/behaviour.json" "$WORK_ON_DISK/$LOG_FILE" <<'PY'
import json, os, sys

env = os.environ


def report(name, ip, guid, boot):
    lines = [f"RESULT hostname={name}", f"RESULT ip={ip}", f"RESULT machine_guid={guid}", f"RESULT boot_time={boot}"]
    return "\r\n".join(lines) + f"\r\nEXITCODE {env['REPORT_EXIT_CODE']}\r\n"


before = report(env["BEFORE_NAME"], env["BEFORE_IP"], env["BEFORE_GUID"], env["BEFORE_BOOT"])
still = report(env["BEFORE_NAME"], env["GUEST_ADDRESS"], env["BEFORE_GUID"], env["BEFORE_BOOT"])
after = report(env["AFTER_NAME"], env["AFTER_IP"], env["AFTER_GUID"], env["AFTER_BOOT"])
alive_before = env["SCENARIO_ALIVE_BEFORE"].split() or None
behaviour = {
    "unready_polls": int(env["UNREADY_POLLS"]),
    "alive_before_apply": alive_before,
    "alive_after_apply": [env["GUEST_ADDRESS"]],
    "sequences": {"-Phase 'Report'": [before] + [still] * int(env["OLD_BOOT_REPORTS"]) + [after]},
}
if env["APPLY_WRITES_LOG"] == "yes":
    content = f"{env['GUEST_LOG_TEXT']}\r\nrebooting {{token}}\r\n"
    behaviour["on_execute_write"] = {"-Phase 'Apply'": {"path": "C:\\ProgramData\\abcdefgh\\" + os.path.basename(sys.argv[2]), "content": content}}
json.dump(behaviour, open(sys.argv[1], "w"))
PY
}

run_reconfigure() {
    export GUEST_ADDRESS TOKEN LEASES BEFORE_NAME BEFORE_IP BEFORE_GUID BEFORE_BOOT AFTER_NAME AFTER_IP AFTER_GUID AFTER_BOOT \
        OLD_BOOT_REPORTS UNREADY_POLLS SCENARIO_ALIVE_BEFORE APPLY_WRITES_LOG GUEST_LOG_TEXT REPORT_EXIT_CODE
    write_behaviour
    OUTPUT="$(env -i PATH="$SB/bin:$PATH" HOME="$SB" STUB_DIR="$STUB_DIR" \
        TT_GUEST_DIR="$SB/guestdir" TT_GUEST_JSON="$SB/ctx/guest.json" TT_PROFILE_DIR="$PROFILE" \
        TT_STATE_FILE="$SB/state.json" TT_BUILD_DIR="$SB/build" TT_CONTEXT_JSON="$SB/ctx/context.json" \
        TT_STEP=reconfigure TT_BUILD_ID=b1 TT_LOG="$SB/log" ${TOKEN:+RECONFIGURE_TOKEN="$TOKEN"} \
        RECONFIGURE_LEASE_WAIT_SECONDS=3 RECONFIGURE_AGENT_WAIT_SECONDS=3 RECONFIGURE_APPLY_WAIT_SECONDS=3 \
        RECONFIGURE_REBOOT_WAIT_SECONDS=3 RECONFIGURE_PROBE_SECONDS=0.05 RECONFIGURE_SETTLE_SECONDS=0 \
        bash "$PROFILE/steps/reconfigure" 2>&1 </dev/null)"
    STATUS=$?
}

vcalls() { cat "$STUB_DIR/calls" 2>/dev/null; }
assert_virsh() { vcalls | grep -qE -- "$1" || { echo "  expected a virsh call matching: $1"; vcalls | indent; return 1; }; }
assert_no_virsh() { ! vcalls | grep -qE -- "$1" || { echo "  expected NO virsh call matching: $1"; vcalls | indent; return 1; }; }

# Python over the agent's request log: $1 is the body of a check(requests) function.
requests_satisfy() {
    python3 -I -c '
import json, re, sys
requests = [json.loads(line) for line in open(sys.argv[1])]
executes = [r for r in requests if r["path"] == "/execute"]
exec(sys.argv[2])
' "$SB/requests.jsonl" "$1" || { echo "  the agent's requests did not satisfy: $1"; indent <"$SB/requests.jsonl"; return 1; }
}

# --- reconfigure -------------------------------------------------------------------------------

test_reconfigure_starts_the_copy_and_leaves_it_running() {
    new_sandbox
    run_reconfigure
    assert_status 0 && assert_virsh '^virsh start ' && assert_no_virsh '^virsh (shutdown|destroy)' && [[ -e $STUB_DIR/running ]]
}

test_reconfigure_does_not_start_a_copy_that_is_already_running() {
    new_sandbox
    touch "$STUB_DIR/running"
    run_reconfigure
    assert_status 0 && assert_no_virsh '^virsh start ' && [[ -e $STUB_DIR/running ]]
}

test_reconfigure_fails_when_the_domain_was_never_defined() {
    new_sandbox
    rm "$STUB_DIR/defined"
    run_reconfigure
    assert_status 1 && assert_contains "define" && assert_no_virsh '^virsh start '
}

test_reconfigure_fails_when_the_copy_does_not_start() {
    new_sandbox
    touch "$STUB_DIR/start-fails"
    run_reconfigure
    assert_status 1 && assert_contains "start"
}

test_reconfigure_finds_the_copy_by_its_new_mac_in_the_dhcp_lease_table() {
    new_sandbox
    run_reconfigure
    assert_status 0 && assert_virsh "^virsh net-dhcp-leases tt-guest --mac $CTX_MAC" && assert_contains "$LEASED_ADDRESS"
}

test_reconfigure_waits_until_a_lease_appears_and_talks_to_the_leased_address() {
    new_sandbox
    LEASES="- - - $LEASED_ADDRESS"
    run_reconfigure
    assert_status 0 &&
        requests_satisfy 'assert executes[0]["host"] == "'$LEASED_ADDRESS'", executes[0]["host"]'
}

test_reconfigure_ignores_the_leases_of_other_machines() {
    new_sandbox
    LEASES="-"
    run_reconfigure
    assert_status 1 && assert_missing "192.168.150.101" && assert_missing "192.168.150.99" && assert_contains "$CTX_MAC"
}

test_reconfigure_ignores_a_lease_of_its_mac_that_is_not_an_ipv4_one() {
    new_sandbox
    LEASES="-"
    touch "$STUB_DIR/ipv6-lease"
    run_reconfigure
    assert_status 1 && assert_missing "2001:db8"
}

test_reconfigure_takes_the_newest_lease_of_its_mac() {
    new_sandbox
    touch "$STUB_DIR/older-lease"
    run_reconfigure
    assert_status 0 && requests_satisfy 'assert executes[0]["host"] == "'$LEASED_ADDRESS'", executes[0]["host"]'
}

test_reconfigure_fails_when_no_lease_ever_appears() {
    new_sandbox
    LEASES="-"
    run_reconfigure
    assert_status 1 && assert_contains "lease" && requests_satisfy 'assert executes == []'
}

test_reconfigure_does_not_assume_the_address_the_guest_will_be_given() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy 'assert executes[0]["host"] != "'$GUEST_ADDRESS'"'
}

# A source built by the real provisioning has a static address, so its copy boots there, not on DHCP.
test_reconfigure_finds_a_copy_that_booted_on_its_sources_static_address() {
    new_sandbox
    SCENARIO_ALIVE_BEFORE="127.0.0.250"
    LEASES="-"
    run_reconfigure
    assert_status 0 && requests_satisfy 'assert executes[0]["host"] == "127.0.0.250", executes[0]["host"]'
}

test_reconfigure_waits_for_an_agent_that_is_not_up_yet() {
    new_sandbox
    LEASES="$LEASED_ADDRESS"
    UNREADY_POLLS=4
    run_reconfigure
    assert_status 0
}

test_reconfigure_fails_when_the_agent_never_answers() {
    new_sandbox
    LEASES="$LEASED_ADDRESS"
    UNREADY_POLLS=100000
    run_reconfigure
    assert_status 1 && assert_contains "agent" && requests_satisfy 'assert executes == []'
}

test_reconfigure_resumes_a_copy_that_already_has_its_final_address() {
    new_sandbox
    SCENARIO_ALIVE_BEFORE="$GUEST_ADDRESS"
    BEFORE_IP=$GUEST_ADDRESS
    LEASES="-"
    run_reconfigure
    assert_status 0 && requests_satisfy 'assert executes[0]["host"] == "'$GUEST_ADDRESS'"'
}

test_reconfigure_reads_the_identity_before_changing_it() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
phases = ["Report" if "-Phase '"'"'Report'"'"'" in r["driver"] else "Apply" if "-Phase '"'"'Apply'"'"'" in r["driver"] else "Discard" for r in executes]
assert phases[:2] == ["Report", "Apply"], phases'
}

test_reconfigure_runs_the_script_in_the_64_bit_shell_and_uploads_it() {
    new_sandbox
    run_reconfigure
    assert_status 0 &&
        requests_satisfy '
assert all("C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe" in r["command"] for r in executes)
stores = [r["form"]["filepath"] for r in requests if r["path"] == "/store"]
assert "C:\\ProgramData\\abcdefgh\\reconfigure.ps1" in stores, stores'
}

test_reconfigure_applies_asynchronously_because_the_address_change_ends_the_connection() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
applies = [r for r in executes if "-Phase '"'"'Apply'"'"'" in r["driver"]]
assert len(applies) == 1 and applies[0]["asynchronous"] is True
assert all(r["asynchronous"] is False for r in executes if r not in applies)'
}

test_reconfigure_hands_the_script_the_guests_name_and_network() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
apply = [r for r in executes if "-Phase '"'"'Apply'"'"'" in r["driver"]][0]["driver"]
for expected in ("-MachineName '"'$CLONE_NAME'"'", "-GuestIp '"'$GUEST_ADDRESS'"'", "-Gateway '"'192.168.150.1'"'", "-Prefix '"'24'"'", "-Decoys '"'false'"'"):
    assert expected in apply, expected
assert re.search(r"-Token '"'"'[0-9a-f-]{36}'"'"'", apply), apply'
}

test_reconfigure_takes_the_prefix_length_from_the_guest_subnet() {
    new_sandbox
    ctx_set host.subnet '"192.168.150.0/25"'
    run_reconfigure
    assert_status 0 && requests_satisfy '
apply = [r for r in executes if "-Phase '"'"'Apply'"'"'" in r["driver"]][0]["driver"]
assert "-Prefix '"'25'"'" in apply'
}

test_reconfigure_uses_a_new_token_for_every_run() {
    new_sandbox
    run_reconfigure
    assert_status 0 || return 1
    local first second
    first=$(grep -o "Token '[^']*'" "$SB/requests.jsonl" | sort -u)
    new_sandbox
    run_reconfigure
    second=$(grep -o "Token '[^']*'" "$SB/requests.jsonl" | sort -u)
    assert_status 0 && [[ -n $first && -n $second && $first != "$second" ]] || { echo "  tokens: $first / $second"; return 1; }
}

test_reconfigure_uploads_the_decoys_script_when_decoys_are_asked_for() {
    new_sandbox
    ctx_set guest.options.decoys true
    run_reconfigure
    assert_status 0 && requests_satisfy '
stores = [r["form"]["filepath"] for r in requests if r["path"] == "/store"]
assert any(path.endswith("decoys.ps1") for path in stores), stores
apply = [r for r in executes if "-Phase '"'"'Apply'"'"'" in r["driver"]][0]["driver"]
assert "-Decoys '"'true'"'" in apply'
}

test_reconfigure_does_not_upload_the_decoys_script_when_they_are_not_asked_for() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
assert not any(r["form"]["filepath"].endswith("decoys.ps1") for r in requests if r["path"] == "/store")'
}

test_reconfigure_waits_for_the_guest_to_say_it_is_rebooting() {
    new_sandbox
    APPLY_WRITES_LOG=no
    mkdir -p "$WORK_ON_DISK"
    printf 'rebooting an-earlier-run\r\n' >"$WORK_ON_DISK/$LOG_FILE"
    run_reconfigure
    assert_status 1 && assert_contains "reboot"
}

test_reconfigure_shows_the_guests_own_log() {
    new_sandbox
    GUEST_LOG_TEXT="the address was set to $GUEST_ADDRESS"
    run_reconfigure
    assert_status 0 && assert_contains "LOG guest: the address was set to $GUEST_ADDRESS"
}

test_reconfigure_removes_the_guests_log_once_it_has_read_it() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
last = executes[-1]["driver"]
assert "-Phase '"'"'Discard'"'"'" in last and "-LogName" in last, last'
}

test_reconfigure_talks_to_the_final_address_after_the_reboot() {
    new_sandbox
    run_reconfigure
    assert_status 0 && requests_satisfy '
reports = [r for r in executes if "-Phase '"'"'Report'"'"'" in r["driver"]]
assert reports[0]["host"] == "'$LEASED_ADDRESS'" and reports[-1]["host"] == "'$GUEST_ADDRESS'", [r["host"] for r in reports]'
}

test_reconfigure_keeps_asking_until_the_boot_time_has_changed() {
    new_sandbox
    OLD_BOOT_REPORTS=3
    run_reconfigure
    assert_status 0 && requests_satisfy '
reports = [r for r in executes if "-Phase '"'"'Report'"'"'" in r["driver"]]
assert len(reports) == 1 + 3 + 1, len(reports)'
}

test_reconfigure_fails_when_the_guest_never_reboots() {
    new_sandbox
    OLD_BOOT_REPORTS=100000
    run_reconfigure
    assert_status 1 && assert_contains "reboot"
}

test_reconfigure_succeeds_with_the_name_in_capitals_as_windows_reports_it() {
    new_sandbox
    AFTER_NAME=${CLONE_NAME^^}
    run_reconfigure
    assert_status 0 && assert_contains "hostname=$AFTER_NAME"
}

test_reconfigure_fails_when_the_computer_name_is_not_the_one_asked_for() {
    new_sandbox
    AFTER_NAME=DESKTOP-OLD
    run_reconfigure
    assert_status 1 && assert_contains "DESKTOP-OLD" && assert_contains "$CLONE_NAME" && assert_contains "hostname"
}

test_reconfigure_fails_when_the_address_is_not_the_one_asked_for() {
    new_sandbox
    AFTER_IP=192.168.150.200
    run_reconfigure
    assert_status 1 && assert_contains "192.168.150.200" && assert_contains "$GUEST_ADDRESS"
}

test_reconfigure_fails_when_the_machine_guid_did_not_change() {
    new_sandbox
    AFTER_GUID=$BEFORE_GUID
    run_reconfigure
    assert_status 1 && assert_contains "MachineGuid" && assert_contains "$BEFORE_GUID"
}

test_reconfigure_reports_every_mismatch_at_once() {
    new_sandbox
    AFTER_NAME=WRONG AFTER_IP=10.0.0.9 AFTER_GUID=$BEFORE_GUID
    run_reconfigure
    assert_status 1 && assert_contains "WRONG" && assert_contains "10.0.0.9" && assert_contains "MachineGuid"
}

test_reconfigure_logs_what_it_verified() {
    new_sandbox
    run_reconfigure
    assert_status 0 && assert_contains "LOG " && assert_contains "$AFTER_GUID" && assert_contains "$AFTER_IP" && assert_contains "PROGRESS 100"
}

test_reconfigure_fails_when_the_report_script_fails() {
    new_sandbox
    REPORT_EXIT_CODE=40
    run_reconfigure
    assert_status 1 && assert_contains "40" && requests_satisfy 'assert not any("-Phase '"'"'Apply'"'"'" in r["driver"] for r in executes)'
}

test_reconfigure_never_prints_the_guests_password() {
    new_sandbox
    run_reconfigure
    assert_status 0 && assert_missing "Sup3r-secret-pw" && ! grep -q "Sup3r-secret-pw" "$SB/requests.jsonl"
}

test_reconfigure_ends_every_pipeline_step_the_same_way_as_its_siblings() {
    new_sandbox
    run_reconfigure
    assert_status 0 && assert_contains "STEP " && [[ $(grep -c '^PROGRESS' <<<"$OUTPUT") -ge 5 ]]
}

for test_name in $(declare -F | awk '$3 ~ /^test_/ {print $3}'); do
    [[ $test_name == *"${ONLY:-}"* ]] && run_test "$test_name"
done

if ((failures > 0)); then echo "$failures test(s) failed"; exit 1; fi
echo "all tests passed"
