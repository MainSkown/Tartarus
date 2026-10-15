#!/usr/bin/env bash
set -euo pipefail

TEMPLATES=/usr/local/lib/tartarus/templates

: "${CAPE_API_TOKEN:?CAPE_API_TOKEN must be set}"
: "${CAPE_DB_PASSWORD:?CAPE_DB_PASSWORD must be set}"
: "${GUEST_CONTROL_TOKEN:?GUEST_CONTROL_TOKEN must be set}"

# The container is on two networks (docker-compose.yml) and Docker decides which one is eth0, so an
# interface cannot be told by its name. Each network gives the service an alias, and a container
# resolves its own alias to its address on exactly that network; the interface is then the one
# carrying that address.
INTERNAL_NETWORK_ALIAS=cape-internal
CONTROL_NETWORK_ALIAS=cape-control

address_on_network() {
    local alias=$1 address
    address=$(getent ahostsv4 "$alias" | awk 'NR == 1 {print $1}')
    if [[ -z $address ]]; then
        echo "the name $alias does not resolve: the cape service in docker-compose.yml must give each network an alias" >&2
        exit 1
    fi
    echo "$address"
}

interface_with_address() {
    ip -4 -o addr show | awk -v wanted="$1" '{split($4, address, "/"); if (address[1] == wanted) {print $2; exit}}'
}

derive_guest_addresses() {
    local subnet=${GUEST_SUBNET:-192.168.150.0/24}
    if [[ ! $subnet =~ ^([0-9]+\.[0-9]+\.[0-9]+)\.0/24$ ]]; then
        echo "GUEST_SUBNET must be a /24 such as 192.168.150.0/24, got '$subnet'" >&2
        exit 1
    fi
    # Registered guests have static addresses from .10 to .99. The DHCP pool is apart from them so a
    # guest that cold-boots on DHCP (every clone does) never competes with a registered guest's
    # address. GUEST_IP, the first static address, remains only for finish-run's default agent URL
    # (supervisord.conf), until the backend finishes runs through guest-control instead.
    export GUEST_GATEWAY_IP="${BASH_REMATCH[1]}.1" GUEST_IP="${BASH_REMATCH[1]}.10"
    export GUEST_DHCP_START="${BASH_REMATCH[1]}.100" GUEST_DHCP_END="${BASH_REMATCH[1]}.119"
}

render() {
    local template=$1 destination=$2 variables=$3
    envsubst "$variables" <"$TEMPLATES/$template" >"$destination"
}

# /dev/kvm keeps the host's group id, which rarely matches this image's kvm group.
grant_qemu_user_kvm_access() {
    local gid group
    gid=$(stat -c %g /dev/kvm)
    group=$(getent group "$gid" | cut -d: -f1) || true
    if [[ -z $group ]]; then
        groupadd --system --gid "$gid" host-kvm
        group=host-kvm
    fi
    usermod -aG "$group" libvirt-qemu
}

render_inetsim_config() {
    { cat /etc/inetsim/inetsim.conf; envsubst '${GUEST_GATEWAY_IP}' <"$TEMPLATES/inetsim.conf"; } >/etc/inetsim/tartarus.conf
}

render_cape_guest_network_overrides() {
    local name
    for name in cuckoo routing; do
        mkdir -p "/opt/CAPEv2/custom/conf/$name.conf.d"
        render "cape-conf.d/$name.conf" "/opt/CAPEv2/custom/conf/$name.conf.d/guest-network.conf" \
            '${GUEST_GATEWAY_IP} ${CAPE_INTERNAL_IFACE}'
    done
}

prepare_volumes() {
    mkdir -p /var/lib/libvirt/definitions /var/lib/libvirt/tartarus/kvm.conf.d
    install -d -o cape -g cape /opt/CAPEv2/storage /opt/CAPEv2/storage/analyses
}

# Every CAPE process creates the schema on first connect; on an empty database they race and
# collide on CREATE TYPE, so it is created once here before any of them starts.
create_cape_schema() {
    (cd /opt/CAPEv2 && runuser -u cape -- .venv/bin/python -c \
        'from lib.cuckoo.core.database import init_database; init_database()')
}

export CAPE_INTERNAL_IP CAPE_INTERNAL_IFACE CAPE_CONTROL_IP
CAPE_INTERNAL_IP=$(address_on_network "$INTERNAL_NETWORK_ALIAS")
CAPE_INTERNAL_IFACE=$(interface_with_address "$CAPE_INTERNAL_IP")
CAPE_CONTROL_IP=$(address_on_network "$CONTROL_NETWORK_ALIAS")
derive_guest_addresses
install -m 0644 "$TEMPLATES/libvirtd.conf" /etc/libvirt/libvirtd.conf
render_inetsim_config
render_cape_guest_network_overrides
grant_qemu_user_kvm_access
prepare_volumes
create_cape_schema

exec supervisord -n -c /etc/supervisor/supervisord.conf
