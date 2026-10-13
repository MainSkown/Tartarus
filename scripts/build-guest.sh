#!/usr/bin/env bash
# Builds the Windows analysis guest unattended and registers it with CAPE, the seed of the M6
# wizard. Drives the running cape container over `docker compose exec`: it stages an answer-file
# ISO (autounattend.xml + the pinned installers + CAPE's agent.py + the provisioning scripts),
# defines a Q35/UEFI-SecureBoot/TPM-2.0 domain, installs Windows, waits for the agent, takes the
# tartarus-clean memory snapshot, and registers the machine. Re-runnable: a rebuild replaces the
# guest. Steps that stand alone (fetch, identity, render-domain, render-autounattend,
# verify-manifest) are also subcommands, which scripts/tests/test_build_guest.sh exercises
# without a guest.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO=$PWD
GUEST_SRC=$REPO/guest
MANIFEST=${MANIFEST:-$GUEST_SRC/manifest.sha256}
ENV_FILE=${TARTARUS_ENV_FILE:-$REPO/.env}

# `make build-guest` does not load .env the way compose does, so take the GUEST_* settings from
# it here; a variable already set in the environment wins.
load_guest_settings() {
    local key value
    [[ -f $ENV_FILE ]] || return 0
    while IFS='=' read -r key value; do
        [[ $key =~ ^GUEST_[A-Z0-9_]+$ && -z ${!key+set} ]] && export "$key=$value"
    done <"$ENV_FILE"
    return 0
}
load_guest_settings

# Guest identity and hardware.
LABEL=${GUEST_LABEL:-win}
GUEST_VCPUS=${GUEST_VCPUS:-2}
GUEST_RAM_MB=${GUEST_RAM_MB:-4096}
GUEST_DISK_GB=${GUEST_DISK_GB:-80}
GUEST_USERNAME=${GUEST_USERNAME:-Analyst}
GUEST_PASSWORD=${GUEST_PASSWORD:-Tartarus1!}
GUEST_HOSTNAME=${GUEST_HOSTNAME:-DESKTOP-7A3K2P9}
IMAGE_INDEX=${GUEST_IMAGE_INDEX:-5}
UI_LANG=${GUEST_UI_LANG:-pl-PL}
INPUT_LOCALE=${GUEST_INPUT_LOCALE:-0415:00000415}
ISO_NAME=${GUEST_ISO:-Win11_25H2_Polish_x64_v2.iso}
GUEST_SUBNET=${GUEST_SUBNET:-192.168.150.0/24}
GUEST_IP=${GUEST_SUBNET%.0/24}.10

# Firmware with Microsoft keys enrolled: real, enforcing Secure Boot for Windows 11.
OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.ms.fd
OVMF_VARS=/usr/share/OVMF/OVMF_VARS_4M.ms.fd

# Paths inside the container, all on the guest-images volume so they survive a recreate.
INSTALL_ISO=/data/iso/$ISO_NAME
BUILD_DIR=/var/lib/libvirt/tartarus/build
CACHE_DIR=/var/lib/libvirt/tartarus/cache
GUEST_DISK=/var/lib/libvirt/images/$LABEL.qcow2
GUEST_NVRAM=/var/lib/libvirt/nvram/${LABEL}_VARS.fd
CLEAN_MEMORY=/var/lib/libvirt/images/$LABEL-clean.mem
CLEAN_OVERLAY=/var/lib/libvirt/images/$LABEL-clean.qcow2
UNATTEND_ISO=/var/lib/libvirt/tartarus/$LABEL-unattend.iso
REGISTRATION=/var/lib/libvirt/tartarus/kvm.conf.d/$LABEL.conf

INSTALL_TIMEOUT=${GUEST_INSTALL_TIMEOUT:-5400}
AGENT_TIMEOUT=${GUEST_AGENT_TIMEOUT:-900}
IDLE_SECONDS=${GUEST_IDLE_SECONDS:-60}

say() { printf '\n==> [%s] %s\n' "$(date +%T)" "$1"; }
die() { printf 'build-guest: %s\n' "$1" >&2; exit 1; }

compose() { docker compose --profile cape "$@"; }
in_cape() { compose exec -T cape "$@"; }
virsh_cape() { in_cape virsh -c qemu:///system "$@"; }

# A real Dell NIC OUI (00:14:22) with random host bytes, so the MAC does not look emulated.
random_mac() { printf '00:14:22:%02x:%02x:%02x' $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)); }

random_alnum() { LC_ALL=C tr -dc A-Z0-9 </dev/urandom | head -c "$1"; }

# Per-build machine identity: a Dell-style 7-character service tag, a Samsung SSD serial and a
# Dell MAC. Any of them can be pinned from the environment to rebuild an identical machine.
generate_identity() {
    export GUEST_UUID=${GUEST_UUID:-$(cat /proc/sys/kernel/random/uuid)}
    export GUEST_MAC=${GUEST_MAC:-$(random_mac)}
    export SMBIOS_SERIAL=${SMBIOS_SERIAL:-$(random_alnum 7)}
    export SMBIOS_BOARD_SERIAL=${SMBIOS_BOARD_SERIAL:-/$SMBIOS_SERIAL/CN$(random_alnum 12)/}
    export SMBIOS_DISK_SERIAL=${SMBIOS_DISK_SERIAL:-S4EWNX0$(random_alnum 6)}
}

# --- pure, testable helpers -------------------------------------------------

# Renders a ${VAR} template against the current environment, leaving unknown placeholders intact.
render_template() {
    python3 -I - "$1" <<'PY'
import os, sys, string
with open(sys.argv[1]) as handle:
    sys.stdout.write(string.Template(handle.read()).safe_substitute(os.environ))
PY
}

render_autounattend() {
    GUEST_USERNAME=$GUEST_USERNAME GUEST_PASSWORD=$GUEST_PASSWORD GUEST_HOSTNAME=$GUEST_HOSTNAME \
        IMAGE_INDEX=$IMAGE_INDEX UI_LANG=$UI_LANG INPUT_LOCALE=$INPUT_LOCALE \
        render_template "$GUEST_SRC/autounattend.xml.tpl"
}

# mode: "install" attaches both CDs and boots the installer; "run" ejects them and boots the disk.
render_domain() {
    local mode=${1:?render-domain needs install|run}
    local install_src="" unattend_src="" os_boot
    if [[ $mode == install ]]; then
        install_src="<source file='$INSTALL_ISO'/>"
        unattend_src="<source file='$UNATTEND_ISO'/>"
        os_boot="<boot dev='cdrom'/><boot dev='hd'/>"
    else
        os_boot="<boot dev='hd'/>"
    fi
    GUEST_NAME=$LABEL GUEST_UUID=${GUEST_UUID:?} GUEST_VCPUS=$GUEST_VCPUS \
        GUEST_RAM_KIB=$((GUEST_RAM_MB * 1024)) GUEST_DISK=$GUEST_DISK \
        OVMF_CODE=$OVMF_CODE OVMF_VARS=$OVMF_VARS GUEST_NVRAM=$GUEST_NVRAM \
        OS_BOOT=$os_boot INSTALL_CDROM_SOURCE=$install_src UNATTEND_CDROM_SOURCE=$unattend_src \
        GUEST_MAC=${GUEST_MAC:?} SMBIOS_SERIAL=${SMBIOS_SERIAL:?} \
        SMBIOS_BOARD_SERIAL=${SMBIOS_BOARD_SERIAL:?} SMBIOS_DISK_SERIAL=${SMBIOS_DISK_SERIAL:?} \
        render_template "$GUEST_SRC/domain.xml.tpl"
}

# Prints the manifest's "<sha256> <name> <url>" entries, without comments and blank lines.
manifest_entries() { grep -vE '^[[:space:]]*(#|$)' "$MANIFEST"; }

# Read into an array up front: `docker compose exec` reads stdin, so calling it inside a
# `while read` over the manifest would swallow the remaining entries.
load_manifest() { mapfile -t MANIFEST_ENTRIES < <(manifest_entries); }

# Verifies every file named in the manifest against its sha256; prints each result.
verify_manifest() {
    local dir=${1:?verify-manifest needs a directory} entry hash name url actual status=0
    load_manifest
    for entry in "${MANIFEST_ENTRIES[@]}"; do
        read -r hash name url <<<"$entry"
        if [[ ! -f $dir/$name ]]; then
            printf '[MISS] %s\n' "$name"; status=1; continue
        fi
        actual=$(sha256sum "$dir/$name" | cut -d' ' -f1)
        if [[ $actual == "$hash" ]]; then
            printf '[ OK ] %s\n' "$name"
        else
            printf '[FAIL] %s (sha256 %s, expected %s)\n' "$name" "$actual" "$hash"; status=1
        fi
    done
    return $status
}

# --- download, staging and orchestration (need the running container) -------

download_into_cache() {
    say "downloading and verifying installers into the cache"
    in_cape mkdir -p "$CACHE_DIR"
    local entry hash name url
    load_manifest
    for entry in "${MANIFEST_ENTRIES[@]}"; do
        read -r hash name url <<<"$entry"
        if in_cape sh -c "[ -f '$CACHE_DIR/$name' ] && echo '$hash  $CACHE_DIR/$name' | sha256sum -c -" >/dev/null 2>&1; then
            printf '  cached %s\n' "$name"
            continue
        fi
        printf '  fetching %s\n' "$name"
        in_cape curl -fsSL --retry 3 -o "$CACHE_DIR/$name" "$url" || die "download failed: $url"
        in_cape sh -c "echo '$hash  $CACHE_DIR/$name' | sha256sum -c -" >/dev/null \
            || die "sha256 mismatch for $name"
    done
}

stage_unattend_iso() {
    say "staging the answer-file ISO"
    local iso_root=$BUILD_DIR/iso entry name
    in_cape rm -rf "$BUILD_DIR"
    in_cape mkdir -p "$iso_root/provision" "$iso_root/payload"
    render_autounattend | in_cape sh -c "cat >'$iso_root/autounattend.xml'"
    compose cp "$GUEST_SRC/provision/." "cape:$iso_root/provision/" >/dev/null || die "could not copy the provisioning scripts"
    load_manifest
    for entry in "${MANIFEST_ENTRIES[@]}"; do
        read -r _ name _ <<<"$entry"
        in_cape cp "$CACHE_DIR/$name" "$iso_root/payload/$name" || die "$name is not in the cache"
    done
    in_cape cp /opt/CAPEv2/agent/agent.py "$iso_root/payload/agent.py" \
        || die "CAPE agent.py not found at /opt/CAPEv2/agent/agent.py"
    in_cape touch "$iso_root/tartarus-provision.marker"
    in_cape xorriso -as mkisofs -quiet -V TARTARUS -J -joliet-long -r -o "$UNATTEND_ISO" "$iso_root" \
        || die "could not build the answer-file ISO"
}

prepare_disk_and_firmware() {
    say "creating the ${GUEST_DISK_GB}G thin disk and clearing stale firmware state"
    in_cape mkdir -p /var/lib/libvirt/images /var/lib/libvirt/nvram /var/lib/libvirt/tartarus/kvm.conf.d
    in_cape rm -f "$GUEST_DISK" "$GUEST_NVRAM"
    in_cape qemu-img create -f qcow2 "$GUEST_DISK" "${GUEST_DISK_GB}G" >/dev/null || die "qemu-img failed"
}

# Unregister first: cuckoo.py powers off a running registered machine whenever cape restarts,
# which would kill the installer mid-build.
remove_existing_guest() {
    say "removing any previous '$LABEL' guest and its registration"
    in_cape rm -f "$REGISTRATION"
    in_cape supervisorctl restart cape >/dev/null 2>&1
    virsh_cape destroy "$LABEL" >/dev/null 2>&1
    virsh_cape undefine "$LABEL" --nvram --snapshots-metadata >/dev/null 2>&1
    # The base disk, the snapshot's memory image and every overlay a revert left behind.
    in_cape sh -c "rm -f /var/lib/libvirt/images/$LABEL.* /var/lib/libvirt/images/$LABEL-clean.*"
}

define_and_boot_installer() {
    say "defining the domain and booting the Windows installer"
    render_domain install | in_cape sh -c "cat >'$BUILD_DIR/domain-install.xml'"
    virsh_cape define "$BUILD_DIR/domain-install.xml" >/dev/null || die "libvirt rejected the domain"
    virsh_cape start "$LABEL" >/dev/null || die "the domain did not start"
}

# Microsoft's UEFI media (efisys.bin) shows "Press any key to boot from CD" for about five
# seconds, a second or two after power-on; without a key the firmware falls through to the empty
# disk. Stop well before Setup's window appears: its focused button is "Cancel", and a stray
# Enter there opens an exit dialog. Only the first boot is nudged, so after Setup's own reboot
# the prompt times out and the installed disk boots.
dismiss_press_any_key() {
    local i
    for i in $(seq 1 20); do
        virsh_cape send-key "$LABEL" KEY_ENTER >/dev/null 2>&1
        sleep 1
    done
}

AGENT=http://$GUEST_IP:8000

wait_for() {
    local deadline=$((SECONDS + ${1:?})) interval=${2:?}
    shift 2
    until "$@"; do
        ((SECONDS < deadline)) || return 1
        sleep "$interval"
    done
}

agent_answers() { [[ $(in_cape curl -s -o /dev/null -w '%{http_code}' -m 5 "$AGENT/" 2>/dev/null) == 200 ]]; }

# provision.ps1 starts the agent before its last log lines and the done marker are written, so the
# agent alone does not mean provisioning finished.
provisioning_done() {
    agent_answers &&
        [[ $(in_cape curl -s -o /dev/null -w '%{http_code}' -m 10 -F 'filepath=C:\tartarus\provision.done' "$AGENT/retrieve") == 200 ]]
}

save_provision_log() {
    in_cape sh -c "curl -s -m 20 -F 'filepath=C:\\tartarus\\provision.log' '$AGENT/retrieve' | tr -d '\\r' >'$BUILD_DIR/provision.log'"
    in_cape cat "$BUILD_DIR/provision.log" | sed 's/^/  guest: /'
}

domain_shut_off() { [[ $(virsh_cape domstate "$LABEL" 2>/dev/null) == "shut off"* ]]; }

# A clean ACPI shutdown, not `virsh destroy`: a hard power-off right after provisioning loses
# whatever Windows has not flushed yet (the end of provision.log came back as NUL bytes once).
shut_down_guest() {
    virsh_cape shutdown "$LABEL" >/dev/null 2>&1
    wait_for 300 5 domain_shut_off && return
    echo "  warning: no clean shutdown within 300s, forcing power-off"
    virsh_cape destroy "$LABEL" >/dev/null 2>&1
}

# External, not internal: libvirt 10.0 refuses internal snapshots of any UEFI (pflash) domain.
# The base disk becomes the snapshot's read-only backing file; each revert (CAPE does one per
# task) replaces the overlay on top of it, so overlays do not pile up.
take_clean_snapshot() {
    virsh_cape snapshot-create-as "$LABEL" tartarus-clean "Tartarus clean baseline" --atomic \
        --memspec "file=$CLEAN_MEMORY,snapshot=external" \
        --diskspec "sda,snapshot=external,file=$CLEAN_OVERLAY" >/dev/null || die "snapshot-create-as failed"
}

snapshot_and_register() {
    say "provisioning finished; guest log saved to $BUILD_DIR/provision.log"
    save_provision_log

    say "shutting down, ejecting the install media and booting the clean guest"
    shut_down_guest
    render_domain run | in_cape sh -c "cat >'$BUILD_DIR/domain-run.xml'"
    virsh_cape define "$BUILD_DIR/domain-run.xml" >/dev/null || die "libvirt rejected the run domain"
    virsh_cape start "$LABEL" >/dev/null || die "the clean guest did not start"
    wait_for "$AGENT_TIMEOUT" 5 agent_answers || die "the agent did not answer after the clean reboot"

    say "letting the guest idle ${IDLE_SECONDS}s, then taking the tartarus-clean memory snapshot"
    sleep "$IDLE_SECONDS"
    take_clean_snapshot
    # cuckoo.py powers off a running registered machine on start, so power off before registering.
    # The snapshot already holds the running state; nothing after it needs to reach the disk.
    virsh_cape destroy "$LABEL" >/dev/null 2>&1

    say "registering the guest with CAPE"
    printf '[kvm]\nmachines = %s\n\n[%s]\nlabel = %s\nplatform = windows\nip = %s\nsnapshot = tartarus-clean\narch = x64\ninterface = tt-guest\ntags = windows,win11\n' \
        "$LABEL" "$LABEL" "$LABEL" "$GUEST_IP" | in_cape sh -c "cat >'$REGISTRATION'"
    in_cape supervisorctl restart cape >/dev/null
}

full_build() {
    [[ -f $REPO/.env ]] || die ".env is missing (copy .env.example and set the passwords and CAPE_API_TOKEN)"
    docker image inspect tartarus-cape:latest >/dev/null 2>&1 || die "tartarus-cape:latest is not built (docker compose --profile cape build cape)"
    [[ -f $REPO/data/iso/$ISO_NAME ]] || die "data/iso/$ISO_NAME not found"

    generate_identity

    say "starting postgres and cape"
    compose up -d --wait postgres >/dev/null 2>&1 || die "postgres did not become healthy"
    compose up -d --wait cape >/dev/null 2>&1 || die "cape did not become healthy (docker compose --profile cape logs cape)"

    remove_existing_guest
    download_into_cache
    stage_unattend_iso
    prepare_disk_and_firmware
    define_and_boot_installer
    dismiss_press_any_key
    say "waiting for Windows to install and first-logon provisioning to finish (up to $((INSTALL_TIMEOUT / 60)) min)"
    wait_for "$INSTALL_TIMEOUT" 15 provisioning_done || die "provisioning never finished (no agent or no provision.done); see virsh screenshot $LABEL"
    snapshot_and_register
    say "done. Verify with scripts/verify-guest.sh (make verify-guest)."
}

case "${1:-}" in
    "")                full_build ;;
    render-domain)     render_domain "${2:-}" ;;
    render-autounattend) render_autounattend ;;
    verify-manifest)   verify_manifest "${2:-}" ;;
    fetch)             download_into_cache ;;
    identity)          generate_identity
                       printf '%s=%s\n' GUEST_UUID "$GUEST_UUID" GUEST_MAC "$GUEST_MAC" SMBIOS_SERIAL "$SMBIOS_SERIAL" \
                           SMBIOS_BOARD_SERIAL "$SMBIOS_BOARD_SERIAL" SMBIOS_DISK_SERIAL "$SMBIOS_DISK_SERIAL" ;;
    -h|--help)         sed -n '2,9p' "${BASH_SOURCE[0]}" ;;
    *) echo "usage: build-guest.sh [fetch | identity | render-domain install|run | render-autounattend | verify-manifest <dir>]" >&2; exit 2 ;;
esac
