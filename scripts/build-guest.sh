#!/usr/bin/env bash
# Builds the Windows analysis guest unattended and registers it with CAPE: a thin wrapper that runs
# `guest-build` inside the cape container, which asks the guest control service to do the build
# (the same engine and steps the wizard uses). Settings come from the GUEST_* variables of .env (a
# variable already in the environment wins): GUEST_ISO, GUEST_IMAGE_INDEX, GUEST_LABEL, GUEST_VCPUS,
# GUEST_RAM_MB, GUEST_DISK_GB, GUEST_USERNAME, GUEST_PASSWORD, GUEST_HOSTNAME, GUEST_PRODUCT_KEY,
# GUEST_DEFENDER (default true), GUEST_DECOYS, GUEST_SYSMON, GUEST_KEYBOARD. The guest is accepted
# without the backend's self-test, so `make verify-guest` is what proves it.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO=$PWD
ENV_FILE=${TARTARUS_ENV_FILE:-$REPO/.env}
ISO_DIR=${TARTARUS_ISO_DIR:-$REPO/data/iso}
GUEST_BUILD=/usr/local/lib/tartarus/guest-build

die() { printf 'build-guest: %s\n' "$1" >&2; exit 1; }

# `make build-guest` does not load .env the way compose does, so take the GUEST_* settings from
# it here; a variable already set in the environment wins.
load_guest_settings() {
    local key value
    while IFS='=' read -r key value; do
        [[ $key =~ ^GUEST_[A-Z0-9_]+$ && -z ${!key+set} ]] && export "$key=$value"
    done <"$ENV_FILE"
    return 0
}

usage() { sed -n '2,/^[^#]/{/^#/s/^# \?//p}' "${BASH_SOURCE[0]}"; }

case "${1:-}" in
    "") ;;
    -h | --help) usage; exit 0 ;;
    *) echo "usage: build-guest.sh   (no arguments; settings are the GUEST_* variables of .env)" >&2; exit 2 ;;
esac

[[ -f $ENV_FILE ]] || die ".env is missing (copy .env.example and set the passwords and CAPE_API_TOKEN)"
load_guest_settings

ISO_NAME=${GUEST_ISO:-Win11_25H2_Polish_x64_v2.iso}
[[ -f $ISO_DIR/$ISO_NAME ]] || die "$ISO_DIR/$ISO_NAME not found"
docker compose exec -T cape true >/dev/null 2>&1 || die "the cape container is not running (docker compose up -d --wait)"

arguments=(--profile windows --media "$ISO_NAME" --variant "${GUEST_IMAGE_INDEX:-5}" --name "${GUEST_LABEL:-win}")
add_argument_if_set() { # <flag> <value>
    [[ -z ${2:-} ]] || arguments+=("$1" "$2")
}
add_option_if_set() { # <option key> <value>
    [[ -z ${2:-} ]] || arguments+=(--option "$1=$2")
}
add_argument_if_set --vcpus "${GUEST_VCPUS:-}"
add_argument_if_set --ram-mb "${GUEST_RAM_MB:-}"
add_argument_if_set --disk-gb "${GUEST_DISK_GB:-}"
add_argument_if_set --username "${GUEST_USERNAME:-}"
add_argument_if_set --computer-name "${GUEST_HOSTNAME:-}"
add_option_if_set defender "${GUEST_DEFENDER:-true}"
add_option_if_set decoys "${GUEST_DECOYS:-}"
add_option_if_set sysmon "${GUEST_SYSMON:-}"
add_option_if_set keyboard "${GUEST_KEYBOARD:-}"
arguments+=(--accept-without-selftest)

# Secrets go in the environment of the command, not on its command line, where `ps` would show them.
secret_variables=()
for secret in GUEST_PASSWORD GUEST_PRODUCT_KEY; do
    [[ -z ${!secret:-} ]] || secret_variables+=(-e "$secret")
done

docker compose exec -T "${secret_variables[@]}" cape python3 -I "$GUEST_BUILD" "${arguments[@]}"
