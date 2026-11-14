# Written for the classic builder as well as BuildKit: hosts without buildx get the classic one.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS cape-source
ARG CAPE_REF
RUN [ "${#CAPE_REF}" -eq 40 ] || { echo "CAPE_REF must be a full kevoreilly/CAPEv2 commit SHA" >&2; exit 1; }
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && git init -q /opt/CAPEv2 \
    && git -C /opt/CAPEv2 fetch -q --depth 1 https://github.com/kevoreilly/CAPEv2.git "$CAPE_REF" \
    && git -C /opt/CAPEv2 checkout -q FETCH_HEAD \
    && rm -rf /opt/CAPEv2/.git


# QEMU and SeaBIOS rebuild only when kvm-qemu.sh, the anti-VM strings or the QEMU version change, not on
# every CAPE_REF bump. To bump QEMU see "Updating QEMU and libvirt" in docs/specs/cape-integration.md.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS qemu-build
ARG ANTIVM_TABLET_VENDOR=Wacom
ARG ANTIVM_SCSI_VENDOR=ATA
ARG ANTIVM_ATAPI_VENDOR=HL-DT-ST
ARG ANTIVM_MICRODRIVE_VENDOR=Hitachi
ARG ANTIVM_BLOCK_FORMAT_NAME=samsung
ARG ANTIVM_ACPI_OEM_ID=ALASKA
ARG ANTIVM_ACPI_TABLE_ID=AMI
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        aptitude build-essential ca-certificates gpg lsb-release python3-pip sudo wget
WORKDIR /build
ARG QEMU_VERSION=11.1.3
ARG QEMU_SHA256=5a8289c7940dc77d3873c81a6c29ba3afe1446fc9d36e77fa1658cdbecb84b22
# kvm-qemu.sh downloads the tarball without a checksum, and only when /tmp does not already hold it:
# fetching it here first makes the pinned hash the check and stops the script from downloading its own.
RUN wget -q -O "/tmp/qemu-${QEMU_VERSION}.tar.xz" "https://download.qemu.org/qemu-${QEMU_VERSION}.tar.xz" \
    && echo "${QEMU_SHA256}  /tmp/qemu-${QEMU_VERSION}.tar.xz" | sha256sum -c -
COPY --from=cape-source /opt/CAPEv2/installer/kvm-qemu.sh ./
COPY cape/build/kvm-config.sh ./
# The script logs a failed compile or install and carries on, so assert the QEMU it installed is the pinned one.
RUN bash kvm-qemu.sh qemu \
    && qemu-system-x86_64 --version | grep -qF "version ${QEMU_VERSION}"
RUN bash kvm-qemu.sh seabios
COPY cape/build/runtime-packages.sh ./
RUN mkdir /out \
    && cp /tmp/qemu-*_builded.deb /out/qemu.deb \
    && cp /usr/share/qemu/bios.bin /usr/share/qemu/bios-256k.bin /out/ \
    && ./runtime-packages.sh /usr/bin/qemu-system-x86_64 /usr/bin/qemu-img /usr/lib/qemu/* > /out/runtime-packages


# VNC only: Tartarus never uses guacd for RDP, SSH or telnet.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS guacd-build
ARG GUACAMOLE_VERSION=1.6.0
ARG GUACAMOLE_SHA256=8bc45675da96d7b6f39728160181e3d4ff3c08f460f6d26de5805b642bf13f2b
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl libcairo2-dev libjpeg-turbo8-dev libpng-dev libssl-dev \
        libtool-bin libvncserver-dev libwebp-dev uuid-dev
WORKDIR /build
RUN curl -fsSLo guacamole-server.tar.gz \
        "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/source/guacamole-server-${GUACAMOLE_VERSION}.tar.gz" \
    && echo "${GUACAMOLE_SHA256}  guacamole-server.tar.gz" | sha256sum -c - \
    && tar xzf guacamole-server.tar.gz
RUN cd "guacamole-server-${GUACAMOLE_VERSION}" \
    && ./configure --prefix=/usr/local --disable-guacenc --disable-guaclog \
        --without-rdp --without-ssh --without-telnet --without-websockets --without-pulse \
    && make -j"$(nproc)" \
    && make install DESTDIR=/out/root \
    && make install \
    && ldconfig
COPY cape/build/runtime-packages.sh ./
RUN ./runtime-packages.sh /usr/local/sbin/guacd /usr/local/lib/libguac*.so > /out/runtime-packages


# Ubuntu 24.04 ships libvirt 10.0, which cannot drive QEMU 11: it reverts a snapshot with a migration to an fd
# and saves memory with the `detach` migrate parameter, and QEMU 11.0 removed both (libvirt stopped needing
# them in 12.1.0). Built here with exactly the drivers the container runs, at the paths Ubuntu's package used.
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS libvirt-build
ARG LIBVIRT_VERSION=12.9.0
ARG LIBVIRT_SHA256=dcf579d8a949f4cbf56820529d48f200382a48ea12855ffded7c16a189353cd7
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl gettext libacl1-dev libattr1-dev libcap-ng-dev libglib2.0-dev \
        libgnutls28-dev libjson-c-dev libnl-3-dev libnl-route-3-dev libreadline-dev libtirpc-dev \
        libxml2-dev libxml2-utils meson ninja-build pkg-config python3 python3-docutils xsltproc xz-utils
WORKDIR /build
RUN curl -fsSLo libvirt.tar.xz "https://libvirt.org/sources/libvirt-${LIBVIRT_VERSION}.tar.xz" \
    && echo "${LIBVIRT_SHA256}  libvirt.tar.xz" | sha256sum -c - \
    && tar xJf libvirt.tar.xz
# Nothing else runs in the container: no apparmor or selinux (qemu.conf sets security_driver = "none"), no
# other hypervisor and no node-device, interface or nwfilter driver, one storage backend (the directory
# pool the access-control proof defines). The monolithic libvirtd is what supervisord starts, so clients
# connect to its socket, not to a per-driver daemon. Libvirt 12 prefers nftables for the network's firewall
# rules; the rooter and guest-firewall are written against the iptables rules libvirt 10 added. The
# documentation build is on because it writes libvirt-api.xml, which libvirt-python generates its
# bindings from; the manual itself is not shipped.
RUN meson setup build "libvirt-${LIBVIRT_VERSION}" --buildtype=release \
        --prefix=/usr --sysconfdir=/etc --localstatedir=/var -Drunstatedir=/run \
        --libdir=lib/x86_64-linux-gnu --libexecdir=lib/libvirt \
        -Dqemu_user=libvirt-qemu -Dqemu_group=kvm \
        -Dpolkit=enabled -Dnls=disabled -Ddocs=enabled -Dtests=disabled -Dbash_completion=disabled \
        -Ddriver_libvirtd=enabled -Dlibvirtd=enabled -Ddriver_remote=enabled -Dremote_default_mode=legacy \
        -Ddriver_qemu=enabled -Ddriver_network=enabled -Ddriver_storage=enabled -Dstorage_dir=enabled \
        -Dfirewall_backend_priority=iptables -Dfirewalld=disabled -Dfirewalld_zone=disabled \
        -Dapparmor=disabled -Dsecdriver_apparmor=disabled -Dapparmor_profiles=disabled \
        -Dselinux=disabled -Dsecdriver_selinux=disabled \
        -Ddriver_lxc=disabled -Ddriver_libxl=disabled -Ddriver_ch=disabled -Ddriver_bhyve=disabled \
        -Ddriver_esx=disabled -Ddriver_vbox=disabled -Ddriver_vmware=disabled -Ddriver_openvz=disabled \
        -Ddriver_hyperv=disabled -Ddriver_vz=disabled -Ddriver_test=disabled \
        -Ddriver_nodedev=disabled -Ddriver_interface=disabled -Ddriver_nwfilter=disabled -Ddriver_secret=disabled \
        -Dudev=disabled -Dpciaccess=disabled -Dnetcf=disabled \
        -Dstorage_disk=disabled -Dstorage_fs=disabled -Dstorage_gluster=disabled -Dstorage_iscsi=disabled \
        -Dstorage_iscsi_direct=disabled -Dstorage_lvm=disabled -Dstorage_mpath=disabled -Dstorage_rbd=disabled \
        -Dstorage_scsi=disabled -Dstorage_vstorage=disabled -Dstorage_zfs=disabled \
        -Daudit=disabled -Dblkid=disabled -Dcurl=disabled -Dfuse=disabled -Dglusterfs=disabled \
        -Dlibiscsi=disabled -Dlibpcap=disabled -Dlibssh=disabled -Dlibssh2=disabled -Dnumactl=disabled \
        -Dopenwsman=disabled -Dsanlock=disabled -Dsasl=disabled -Dwireshark_dissector=disabled \
        -Ddtrace=disabled -Dnumad=disabled -Dpm_utils=disabled -Dnbdkit=disabled -Dnss=disabled \
        -Dhost_validate=disabled -Dlogin_shell=disabled -Dssh_proxy=disabled -Dsysctl_config=disabled \
        -Dinit_script=none \
    && meson compile -C build \
    && DESTDIR=/out/root meson install -C build --strip \
    && rm -rf /out/root/usr/share/doc /out/root/usr/share/man
COPY cape/build/runtime-packages.sh ./
# The tree is not installed in this stage, so the loader is told where libvirt's own libraries are;
# scripts among the installed files would make ldd fail, so only ELF files are listed.
RUN find /out/root -type f -exec sh -c 'head -c4 "$1" | grep -q ELF' _ {} \; -print0 \
        | LD_LIBRARY_PATH=/out/root/usr/lib/x86_64-linux-gnu xargs -0 ./runtime-packages.sh > /out/runtime-packages


FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS cape-build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git libfuzzy-dev libjansson-dev libmagic-dev libre2-dev \
        libssl-dev pkg-config python3 python3-dev unzip
# libvirt-python builds against the headers and the library of the libvirt that runs in the image, which needs
# its own runtime libraries to link.
COPY --from=libvirt-build /out/runtime-packages /tmp/libvirt/
COPY --from=libvirt-build /out/root/usr /usr
RUN apt-get update && apt-get install -y --no-install-recommends $(cat /tmp/libvirt/runtime-packages) \
    && rm -rf /var/lib/apt/lists/* /tmp/libvirt && ldconfig
COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/uv
COPY --from=cape-source /opt/CAPEv2 /opt/CAPEv2
WORKDIR /opt/CAPEv2
ENV UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev
# cape2.sh installs libvirt-python separately, pinned to the libvirt it runs against.
RUN uv pip install --python .venv/bin/python "libvirt-python==$(pkg-config --modversion libvirt)"
RUN .venv/bin/python utils/community.py -waf -cr
# Run by the control service, not by CAPE's own memory module (see docs/history/m8-spikes/S3-findings.md).
# `vol --help` imports every plugin, so a wheel the venv cannot run fails the build, not the first analysis.
COPY cape/build/volatility3.requirements /build/
RUN uv pip install --python .venv/bin/python --no-deps --require-hashes -r /build/volatility3.requirements
RUN .venv/bin/vol --help >/dev/null
COPY cape/build/runtime-packages.sh /build/
RUN find .venv -name '*.so*' -type f -print0 | xargs -0 /build/runtime-packages.sh > /build/venv-runtime-packages
# Reads the Windows installation media for the guest wizard without mounting it (pycdlib: pure Python,
# no dependencies). Built here because this stage has uv and the final image has no pip; the final
# stage copies the tree into the system python3's dist-packages, where the engine's child process
# (`python3 -I`) finds it, minus the scripts and man pages the wheel also carries. The hash of the wheel
# is the only thing fetched.
COPY cape/build/pycdlib.requirements /build/
RUN uv pip install --python /usr/bin/python3.12 --target /build/pycdlib --no-deps --require-hashes \
        -r /build/pycdlib.requirements \
    && rm -rf /build/pycdlib/bin /build/pycdlib/share \
    && chmod -R a+rX /build/pycdlib


FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1
COPY --from=qemu-build /out/qemu.deb /out/runtime-packages /tmp/qemu/
COPY --from=guacd-build /out/runtime-packages /tmp/guacd/
COPY --from=libvirt-build /out/runtime-packages /tmp/libvirt/
COPY --from=cape-build /build/venv-runtime-packages /tmp/cape/
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl cron dbus dmidecode dnsmasq-base gettext-base iproute2 iptables lsb-release nftables \
        p7zip-full polkitd procps python3 software-properties-common sudo supervisor swtpm swtpm-tools \
        tcpdump unzip upx-ucl xorriso inetsim \
        $(cat /tmp/qemu/runtime-packages /tmp/guacd/runtime-packages /tmp/libvirt/runtime-packages \
            /tmp/cape/venv-runtime-packages) \
        /tmp/qemu/qemu.deb \
    && rm -rf /tmp/qemu /tmp/guacd /tmp/libvirt /tmp/cape
COPY --from=libvirt-build /out/root/ /
# INetSim 1.3.2 runs Net::DNS::Nameserver->main_loop in a forked child; Net::DNS 1.44 turned
# main_loop into start_server, which croaks in a subprocess, so the DNS service dies at start.
# loop_once is the single-process loop main_loop used to be.
RUN sed -i 's/\$server->main_loop;/$server->loop_once(10) while 1;/' /usr/share/perl5/INetSim/DNS.pm \
    && grep -q 'loop_once(10) while 1;' /usr/share/perl5/INetSim/DNS.pm
COPY --from=qemu-build /out/bios.bin /out/bios-256k.bin /usr/share/qemu/
COPY --from=guacd-build /out/root/usr/local /usr/local
RUN ldconfig
# Windows 11 needs Secure Boot with Microsoft keys enrolled. Ubuntu's ovmf package ships exactly
# that (OVMF_*_4M.ms.fd), but installing the package collides with the custom qemu.deb over a
# firmware JSON descriptor, so take only the two firmware images from it instead.
RUN cd /tmp && apt-get download ovmf \
    && dpkg-deb -x ovmf_*.deb /tmp/ovmf \
    && mkdir -p /usr/share/OVMF \
    && cp /tmp/ovmf/usr/share/OVMF/OVMF_CODE_4M.secboot.fd /usr/share/OVMF/OVMF_CODE_4M.ms.fd \
    && cp /tmp/ovmf/usr/share/OVMF/OVMF_VARS_4M.ms.fd /usr/share/OVMF/OVMF_VARS_4M.ms.fd \
    && rm -rf /tmp/ovmf /tmp/ovmf_*.deb

# The users and groups Ubuntu's libvirt packages created, which libvirt (built with these names) and the
# network definition expect. libvirt-qemu's uid and gid 64055 are the ones Debian reserved for it.
RUN groupadd --system cape \
    && useradd --system --gid cape --home-dir /home/cape --create-home --shell /bin/bash cape \
    && groupadd --system libvirt \
    && (getent group kvm || groupadd --system kvm) \
    && groupadd --system --gid 64055 libvirt-qemu \
    && useradd --system --uid 64055 --gid kvm --groups libvirt-qemu --no-create-home \
        --home-dir /var/lib/libvirt --shell /usr/sbin/nologin libvirt-qemu \
    && groupadd --system libvirt-dnsmasq \
    && useradd --system --gid libvirt-dnsmasq --no-create-home --home-dir /var/lib/libvirt/dnsmasq \
        --shell /usr/sbin/nologin libvirt-dnsmasq \
    && usermod -aG libvirt,kvm cape
# A device node keeps its host gid inside the container, so an image group with the same number opens
# that device: cape's 995 was a host's `audio` group (the microphone). Every group a program here runs
# with moves into Debian's reserved 64xxx block, as pcap does below, and its files follow it.
RUN gid=64020; for group in cape libvirt kvm libvirt-dnsmasq inetsim swtpm polkitd messagebus tcpdump; do \
        old=$(getent group "$group" | cut -d: -f3) \
        && groupmod --gid "$gid" "$group" \
        && find / -xdev -gid "$old" -exec chgrp -h "$group" {} + \
        || exit 1; \
        gid=$((gid + 1)); \
    done

# Root-owned: the rooter runs as root and imports this tree, so the `cape` user that parses hostile
# data must not be able to rewrite it. What cape writes while running is listed further down.
COPY --from=cape-build /opt/CAPEv2 /opt/CAPEv2
RUN bash /opt/CAPEv2/installer/cape2.sh suricata \
    && suricata-update --suricata /usr/bin/suricata --suricata-conf /etc/suricata/suricata.yaml -o /etc/suricata/rules/ \
    && rm -rf /var/lib/apt/lists/*

# cape2.sh adds its user to the suricata group, which inside a privileged container is also the host's
# `disk` group (gid 993): its members open the host's raw disks. Nothing cape runs needs the group.
RUN gpasswd -d cape suricata
# CAPE's sniffer starts tcpdump itself; file capabilities replace a sudo rule that let cape run it as
# root with any argument (`-z <script>`). Chmod and chgrp first: a change of owner drops file capabilities.
# CAPE's startup check wants the user in group `pcap`.
RUN groupmod --gid 64010 pcap && usermod -aG pcap cape \
    && chgrp pcap /usr/bin/tcpdump && chmod 0750 /usr/bin/tcpdump \
    && setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump

# Domain definitions live with the disks on the guest-images volume, so a recreated container
# keeps the guest, its snapshot and its CAPE registration.
RUN rm -rf /etc/libvirt/qemu \
    && mkdir -p /var/lib/libvirt/definitions /var/lib/libvirt/tartarus/kvm.conf.d /opt/CAPEv2/custom/conf \
    && install -d -o cape -g cape /opt/CAPEv2/storage /opt/CAPEv2/storage/analyses /opt/CAPEv2/log /opt/CAPEv2/data/feeds /var/lib/cape-web \
    && install -o cape -g cape -m 0644 /dev/null /opt/CAPEv2/data/yara/index_memory.yarc \
    && ln -s /var/lib/libvirt/definitions /etc/libvirt/qemu \
    && ln -s /var/lib/libvirt/tartarus/kvm.conf.d /opt/CAPEv2/custom/conf/kvm.conf.d

# In an interactive analysis the analyzer injects the monitor into everything Explorer starts, and a
# Store app (the Windows 11 Notepad) then hangs in ntdll waits and never opens a window. The
# analyzer is zipped from this directory and uploaded to the guest for every task, so patching it here
# fixes that without touching the guest. The patch fails the build if CAPE_REF moved its anchors.
COPY cape/patches/skip-packaged-apps.py /tmp/skip-packaged-apps.py
RUN python3 /tmp/skip-packaged-apps.py /opt/CAPEv2/analyzer/windows/analyzer.py \
    && python3 -c "import ast; ast.parse(open('/opt/CAPEv2/analyzer/windows/analyzer.py').read())" \
    && grep -q 'skips_packaged_app(filepath, self.analyzer.package_name)' /opt/CAPEv2/analyzer/windows/analyzer.py \
    && rm /tmp/skip-packaged-apps.py

# An interactive analysis also injects the DCOM launcher service, and the monitor left there stalls every
# process the agent starts once the analyzer has exited, which costs the run its event-log exports.
COPY cape/patches/leave-dcom-launch-alone.py /tmp/leave-dcom-launch-alone.py
RUN python3 /tmp/leave-dcom-launch-alone.py /opt/CAPEv2/analyzer/windows/analyzer.py \
    && python3 -c "import ast; ast.parse(open('/opt/CAPEv2/analyzer/windows/analyzer.py').read())" \
    && grep -q 'self.MONITORED_DCOM = True' /opt/CAPEv2/analyzer/windows/analyzer.py \
    && rm /tmp/leave-dcom-launch-alone.py

# Python's zipfile cannot read AES zips, and CAPE's `zip` package then falls back to a 7z.exe the guest does
# not have. The analyzer's bin directory is where CAPE keeps the tools it uploads (autoit3.exe, loader.exe),
# so the standalone x86 console build goes there (the guest's Python is 32-bit; x86 runs on 64-bit Windows),
# named 7z.exe because CAPE's lookup matches that name. The "extra" package is LZMA2, which this image's 7z
# unpacks. 26.03 is the newest release that was a month old when this was pinned (26.04 came out 2026-10-05).
ARG SEVEN_ZIP_VERSION=2603
ARG SEVEN_ZIP_SHA256=191894e6acb3647ffb69ce630479ff318523b2e2b9890aa7f05c1127c2e59b8f
COPY cape/patches/zip-bundled-7zip.py /tmp/zip-bundled-7zip.py
RUN curl -fsSLo /tmp/7z-extra.7z "https://www.7-zip.org/a/7z${SEVEN_ZIP_VERSION}-extra.7z" \
    && echo "${SEVEN_ZIP_SHA256}  /tmp/7z-extra.7z" | sha256sum -c - \
    && 7z x -o/tmp/7z-extra /tmp/7z-extra.7z 7za.exe License.txt \
    && install -m 0644 /tmp/7z-extra/7za.exe /opt/CAPEv2/analyzer/windows/bin/7z.exe \
    && install -m 0644 /tmp/7z-extra/License.txt /opt/CAPEv2/analyzer/windows/bin/7-Zip-License.txt \
    && rm -rf /tmp/7z-extra /tmp/7z-extra.7z \
    && python3 /tmp/zip-bundled-7zip.py /opt/CAPEv2/analyzer/windows/modules/packages/zip.py \
    && python3 -c "import ast; ast.parse(open('/opt/CAPEv2/analyzer/windows/modules/packages/zip.py').read())" \
    && grep -q '"bin", "7z.exe"' /opt/CAPEv2/analyzer/windows/modules/packages/zip.py \
    && rm /tmp/zip-bundled-7zip.py

# The cape user has no libvirt write permission (cape/libvirt/polkit): reverting a guest, powering it off
# and dumping its memory go through the root machine broker, so CAPE's machinery is patched to ask it.
# The checks fail the build if CAPE_REF moved the code and one of the three writes is still there.
COPY cape/bin/machine_broker_client.py /opt/CAPEv2/lib/cuckoo/common/
COPY cape/patches/machinery-through-broker.py /tmp/machinery-through-broker.py
RUN python3 /tmp/machinery-through-broker.py /opt/CAPEv2/lib/cuckoo/common/abstracts.py \
    && python3 -c "import ast; ast.parse(open('/opt/CAPEv2/lib/cuckoo/common/abstracts.py').read())" \
    && ! grep -qF 'revertToSnapshot(' /opt/CAPEv2/lib/cuckoo/common/abstracts.py \
    && ! grep -qF 'vm.destroy()' /opt/CAPEv2/lib/cuckoo/common/abstracts.py \
    && ! grep -qF 'coreDump(' /opt/CAPEv2/lib/cuckoo/common/abstracts.py \
    && rm /tmp/machinery-through-broker.py

# Host-side auxiliary that exports the guest's Sysmon and Defender logs through the agent at the end of
# a run. CAPE imports every module in this directory; auxiliary.conf enables it by file name. It reads
# the Sysmon config from the profiles copied below.
COPY cape/auxiliary/event_logs.py /opt/CAPEv2/modules/auxiliary/event_logs.py

# The media scan's reader of disc images, built in cape-build. A layer of its own, after the slow ones,
# so adding it does not re-resolve the packages the proven libvirt and QEMU were installed with. The
# import fails the build if the tree is not where the system python3 looks.
COPY --from=cape-build /build/pycdlib/ /usr/local/lib/python3.12/dist-packages/
RUN python3 -I -c "import pycdlib"

# Builds the guest self-test's benign sample on request (the profile names the compiler); a layer of
# its own, after the slow ones, for the same reason as the pycdlib layer.
RUN apt-get update && apt-get install -y --no-install-recommends gcc-mingw-w64-x86-64 \
    && rm -rf /var/lib/apt/lists/*

COPY cape/libvirt/qemu.conf /etc/libvirt/qemu.conf
# libvirt reads its hooks directory once, at start; the hook binds each started guest's port (guest-firewall).
COPY cape/libvirt/qemu-hook /etc/libvirt/hooks/qemu
RUN chmod 0755 /etc/libvirt/hooks/qemu
# What the `cape` user may ask libvirtd (libvirtd.conf turns the polkit access driver on). polkitd reads
# /etc/polkit-1/rules.d as its own user, so the file must be world-readable whatever the checkout's mode.
COPY cape/libvirt/polkit/50-tartarus-libvirt.rules /etc/polkit-1/rules.d/
COPY cape/libvirt/dbus-system.conf /etc/dbus-1/tartarus-system.conf
RUN chmod 0644 /etc/polkit-1/rules.d/50-tartarus-libvirt.rules /etc/dbus-1/tartarus-system.conf
COPY cape/supervisord.conf /etc/supervisor/conf.d/cape.conf
COPY cape/templates/ /usr/local/lib/tartarus/templates/
COPY cape/bin/ /usr/local/lib/tartarus/
# Beside the scripts, which put their own directory on the import path.
COPY cape/guest_engine/ /usr/local/lib/tartarus/guest_engine/
COPY guest/profiles/ /usr/local/lib/tartarus/profiles/
COPY guest/steps/ /usr/local/lib/tartarus/steps/
COPY guest/domain/ /usr/local/lib/tartarus/domain/
COPY guest/personas/ /usr/local/lib/tartarus/personas/
COPY cape/entrypoint.sh /usr/local/bin/cape-entrypoint
COPY cape/conf/ /opt/CAPEv2/custom/conf/
# CAPE's web process serves only the REST API, without debug pages; see web/local_settings.py.
COPY cape/web/ /opt/CAPEv2/web/web/
RUN python3 -c "import secrets; print('SECRET_KEY = %r' % secrets.token_urlsafe(50))" > /opt/CAPEv2/web/web/secret_key.py

# The token reaches curl on stdin: printf is a builtin, so it is never among any process's arguments.
HEALTHCHECK --interval=15s --timeout=10s --start-period=120s --retries=5 \
    CMD virsh -q -c qemu:///system list >/dev/null \
        && printf 'header = "Authorization: Token %s"\n' "$CAPE_API_TOKEN" \
        | curl -fsS -o /dev/null -K - http://127.0.0.1:8000/apiv2/cuckoo/status/
ENTRYPOINT ["cape-entrypoint"]
