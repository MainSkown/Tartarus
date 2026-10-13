#!/usr/bin/env bash
# Prints the Debian packages that provide the shared libraries the given binaries link against.
# kvm-qemu.sh packages QEMU as a .deb with no Depends, so the runtime stage installs these instead.
set -euo pipefail

# dpkg -S prints "pkg[:arch][, pkg2]: path", plus "diversion by ..." lines that name no owner.
package_owning() {
    local library=$1
    { dpkg -S "$library" 2>/dev/null || dpkg -S "/usr$library" 2>/dev/null || dpkg -S "${library#/usr}" 2>/dev/null; } |
        grep -v '^diversion by'
}

ldd "$@" 2>/dev/null |
    awk '$2 == "=>" && $3 ~ /^\// {print $3}' |
    sort -u |
    while read -r library; do
        package_owning "$library" || echo "unowned: $library" >&2
    done |
    cut -d: -f1 |
    tr ', ' '\n\n' |
    grep -vxE 'qemu|' |
    sort -u
