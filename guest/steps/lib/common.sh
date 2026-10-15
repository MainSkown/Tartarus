#!/usr/bin/env bash
# Sourced by every generic step (and available to a profile's own steps): the step protocol lines,
# the guest's facts from context.json, where its files live, and the libvirt calls they all make.
# Values are read with python3 -I and held in variables; none is ever pasted into a command line.
# shellcheck disable=SC2034  # the variables are this library's output, read by the steps that source it

STEPS_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SNAPSHOT_NAME=tartarus-clean
GUEST_NETWORK=tt-guest

step() { printf 'STEP %s\n' "${*//$'\n'/ }"; }
progress() { printf 'PROGRESS %s\n' "$1"; }
log() { printf 'LOG %s\n' "${*//$'\n'/ }"; }
fail() { log "$*"; exit 1; }

: "${TT_CONTEXT_JSON:?the step protocol gives every step TT_CONTEXT_JSON}"

# context_get <dotted.path>: a scalar of context.json (objects and lists print as JSON); status 3
# when the path is missing or null.
context_get() {
    python3 -I -c '
import json, sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    value = value.get(key) if isinstance(value, dict) else None
if value is None:
    sys.exit(3)
if isinstance(value, bool):
    value = str(value).lower()
print(json.dumps(value) if isinstance(value, (dict, list)) else value)
' "$TT_CONTEXT_JSON" "$1"
}

# context_var <VARIABLE> <dotted.path> [default]: set the variable from context.json, or stop the step.
# Not a command substitution on purpose: `fail` inside one would only end the subshell.
context_var() {
    local -n target=$1
    if target=$(context_get "$2"); then
        return
    fi
    (($# > 2)) || fail "context.json has no $2"
    target=$3
}

context_var GUEST_NAME guest.name
context_var GUEST_IP guest.ip
context_var GUEST_UUID guest.machine.uuid
context_var BUILD_KIND build.kind
context_var MEDIA_FILE guest.media.file ""
context_var LIBVIRT_DIR host.libvirt_dir
context_var MEDIA_DIR host.media_dir
context_var REGISTRY_ROOT host.registry_root
context_var LIBVIRT_URI host.libvirt_uri

IMAGES_DIR=$LIBVIRT_DIR/images
NVRAM_DIR=$LIBVIRT_DIR/nvram
CACHE_DIR=$LIBVIRT_DIR/tartarus/cache
DISK_PATH=$IMAGES_DIR/$GUEST_NAME.qcow2
NVRAM_PATH=$NVRAM_DIR/${GUEST_NAME}_VARS.fd
CLEAN_MEMORY=$IMAGES_DIR/$GUEST_NAME-clean.mem
CLEAN_OVERLAY=$IMAGES_DIR/$GUEST_NAME-clean.qcow2
MEDIA_PATH=${MEDIA_FILE:+$MEDIA_DIR/$MEDIA_FILE}

vsh() { virsh -c "$LIBVIRT_URI" "$@"; }
guest_record() { "$STEPS_LIB/guest-record" "$@"; }

# wait_for <seconds> <interval> <command...>: succeeds as soon as the command does.
wait_for() {
    local deadline=$((SECONDS + ${1:?})) interval=${2:?}
    shift 2
    until "$@"; do
        ((SECONDS < deadline)) || return 1
        sleep "$interval"
    done
}

domain_exists() { vsh dominfo "$GUEST_NAME" >/dev/null 2>&1; }
domain_state() { vsh domstate "$GUEST_NAME" 2>/dev/null; }
domain_running() { [[ $(domain_state) == running ]]; }
domain_shut_off() { [[ $(domain_state) == "shut off"* ]]; }

# The guest's own libvirt state goes with it: a leftover nvram, TPM state and snapshot metadata
# would otherwise make the next define refuse or boot a stale machine.
remove_domain() {
    domain_running && vsh destroy "$GUEST_NAME" >/dev/null 2>&1
    vsh undefine "$GUEST_NAME" --nvram --tpm --snapshots-metadata >/dev/null 2>&1
}

# render_domain <install|run> [render-domain options]: write $TT_BUILD_DIR/domain-<mode>.xml.
render_domain() {
    local mode=$1
    shift
    "$STEPS_LIB/render-domain" --mode "$mode" --disk "$DISK_PATH" --nvram "$NVRAM_PATH" "$@" \
        >"$TT_BUILD_DIR/domain-$mode.xml" || fail "could not render the $mode domain"
}

# define_rendered <install|run>: hand the rendered domain to libvirt.
define_rendered() {
    vsh define "$TT_BUILD_DIR/domain-$1.xml" >/dev/null || fail "libvirt rejected the $1 domain"
}

define_domain() {
    render_domain "$@"
    define_rendered "$1"
}

json_string() { python3 -I -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }

# Nothing records what kind of medium a guest was built from, so it is told by the file: an ISO is
# installed from, anything else is an installed disk image.
media_kind() {
    case ${MEDIA_FILE,,} in
        *.iso) echo installer ;;
        *) echo disk_image ;;
    esac
}
