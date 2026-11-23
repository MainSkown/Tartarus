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
DATABASE_NETWORK_ALIAS=cape-db
# The host in the connection of cape/conf/cuckoo.conf.
DATABASE_HOST=postgres

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
    # address.
    export GUEST_GATEWAY_IP="${BASH_REMATCH[1]}.1"
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
    local fake_host_names
    # A dns_static line INetSim refuses stops all of its services, so a helper that fails outright
    # leaves the fake hosts without names instead of INetSim without a start.
    fake_host_names=$(python3 -I /usr/local/lib/tartarus/lan-dns-static) || fake_host_names=
    {
        cat /etc/inetsim/inetsim.conf
        envsubst '${GUEST_GATEWAY_IP}' <"$TEMPLATES/inetsim.conf"
        printf '%s' "$fake_host_names"
    } >/etc/inetsim/tartarus.conf
}

render_cape_guest_network_overrides() {
    local name
    for name in cuckoo routing; do
        mkdir -p "/opt/CAPEv2/custom/conf/$name.conf.d"
        render "cape-conf.d/$name.conf" "/opt/CAPEv2/custom/conf/$name.conf.d/guest-network.conf" \
            '${GUEST_GATEWAY_IP} ${CAPE_INTERNAL_IFACE}'
    done
}

# Docker mounts /proc/sys read-only for a container that is not privileged, and libvirt writes
# net.ipv6.conf.<bridge>.disable_ipv6 for the bridge it creates. Only the network subtree, which is
# this container's own namespace, becomes writable; kernel.* stays read-only.
make_network_sysctls_writable() {
    mount --bind /proc/sys/net /proc/sys/net
    mount -o remount,rw,bind /proc/sys/net
}

prepare_volumes() {
    mkdir -p /var/lib/libvirt/definitions /var/lib/libvirt/tartarus/kvm.conf.d
    install -d -o cape -g cape /opt/CAPEv2/storage /opt/CAPEv2/storage/analyses
}

# /run/lan-sim is the lan-run volume, shared with the lan-sim container (docker-compose.yml). That
# container parses hostile input and runs as uid 10001: it may read the sessions this service
# publishes but never write them, and it owns the two directories it writes.
prepare_lan_sim_directory() {
    install -d -m 0755 -o root -g root /run/lan-sim /run/lan-sim/sessions
    install -d -m 0755 -o 10001 -g 10001 /run/lan-sim/status
    install -d -m 0750 -o 10001 -g 10001 /run/lan-sim/logs
}

# Every CAPE process creates the schema on first connect; on an empty database they race and
# collide on CREATE TYPE, so it is created once here before any of them starts.
# CAPE answers a schema it does not expect by exiting with status 0, which would let every CAPE program
# die at import while this script went on: here that is a failure.
create_cape_schema() {
    (cd /opt/CAPEv2 && runuser -u cape -- .venv/bin/python -c '
import sys
from lib.cuckoo.core.database import init_database
try:
    init_database()
except SystemExit:
    sys.exit(1)')
}

cape_database_has_a_schema() {
    (cd /opt/CAPEv2 && runuser -u cape -- .venv/bin/python -c '
import sys
import psycopg
from lib.cuckoo.common.config import Config
with psycopg.connect(Config().database.connection) as connection:
    versioned = connection.execute("select to_regclass(%s)", ("public.alembic_version",)).fetchone()[0]
sys.exit(0 if versioned else 1)')
}

# A database made by the CAPE of an earlier image is brought to this image's schema with CAPE's own
# migrations. A new database has no schema to migrate: create_cape_schema makes it at the current one.
migrate_cape_schema() {
    cape_database_has_a_schema || return 0
    (cd /opt/CAPEv2/utils/db_migration && runuser -u cape -- /opt/CAPEv2/.venv/bin/alembic upgrade head)
}

export CAPE_INTERNAL_IP CAPE_INTERNAL_IFACE CAPE_CONTROL_IP CAPE_DB_IP CAPE_DB_IFACE
CAPE_INTERNAL_IP=$(address_on_network "$INTERNAL_NETWORK_ALIAS")
CAPE_INTERNAL_IFACE=$(interface_with_address "$CAPE_INTERNAL_IP")
CAPE_CONTROL_IP=$(address_on_network "$CONTROL_NETWORK_ALIAS")
CAPE_DB_IP=$(address_on_network "$DATABASE_NETWORK_ALIAS")
CAPE_DB_IFACE=$(interface_with_address "$CAPE_DB_IP")
derive_guest_addresses
make_network_sysctls_writable
# Before anything else starts: a guest must never run with only the rooter's rules between it and the
# container. A failure here stops the container (set -e).
python3 -I /usr/local/lib/tartarus/guest-firewall init
# Likewise no program may start before its output is confined: the `cape` user parses hostile sample
# output and must reach the CAPE database and nothing else, not even a resolver, so the database's
# address is looked up here for it.
/usr/local/lib/tartarus/pin-host "$DATABASE_HOST" /etc/hosts
python3 -I /usr/local/lib/tartarus/container-egress init
install -m 0644 "$TEMPLATES/libvirtd.conf" /etc/libvirt/libvirtd.conf
# /run is a tmpfs, so the directory of the bus socket (see supervisord.conf) is gone at every start.
install -d /run/dbus
render_inetsim_config
render_cape_guest_network_overrides
grant_qemu_user_kvm_access
prepare_volumes
prepare_lan_sim_directory
migrate_cape_schema
create_cape_schema

# SYS_ADMIN was for the mount above. Out of the bounding set, no program started from here on can
# hold it again, whatever it executes: root in this container can then no longer remount /proc/sys.
exec setpriv --bounding-set -sys_admin --inh-caps -sys_admin supervisord -n -c /etc/supervisor/supervisord.conf
