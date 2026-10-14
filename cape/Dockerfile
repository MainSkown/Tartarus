# Written for the classic builder as well as BuildKit: hosts without buildx get the classic one.
FROM ubuntu:24.04 AS cape-source
ARG CAPE_REF
RUN [ "${#CAPE_REF}" -eq 40 ] || { echo "CAPE_REF must be a full kevoreilly/CAPEv2 commit SHA" >&2; exit 1; }
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && git init -q /opt/CAPEv2 \
    && git -C /opt/CAPEv2 fetch -q --depth 1 https://github.com/kevoreilly/CAPEv2.git "$CAPE_REF" \
    && git -C /opt/CAPEv2 checkout -q FETCH_HEAD \
    && rm -rf /opt/CAPEv2/.git


# QEMU and SeaBIOS rebuild only when kvm-qemu.sh or the anti-VM strings change, not on every CAPE_REF bump.
FROM ubuntu:24.04 AS qemu-build
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
COPY --from=cape-source /opt/CAPEv2/installer/kvm-qemu.sh ./
COPY build/kvm-config.sh ./
RUN bash kvm-qemu.sh qemu
RUN bash kvm-qemu.sh seabios
COPY build/runtime-packages.sh ./
RUN mkdir /out \
    && cp /tmp/qemu-*_builded.deb /out/qemu.deb \
    && cp /usr/share/qemu/bios.bin /usr/share/qemu/bios-256k.bin /out/ \
    && ./runtime-packages.sh /usr/bin/qemu-system-x86_64 /usr/bin/qemu-img /usr/lib/qemu/* > /out/runtime-packages


# VNC only: Tartarus never uses guacd for RDP, SSH or telnet.
FROM ubuntu:24.04 AS guacd-build
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
COPY build/runtime-packages.sh ./
RUN ./runtime-packages.sh /usr/local/sbin/guacd /usr/local/lib/libguac*.so > /out/runtime-packages


FROM ubuntu:24.04 AS cape-build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git libfuzzy-dev libjansson-dev libmagic-dev libre2-dev \
        libssl-dev libvirt-dev pkg-config python3 python3-dev unzip
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
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
COPY build/runtime-packages.sh /build/
RUN find .venv -name '*.so*' -type f -print0 | xargs -0 /build/runtime-packages.sh > /build/venv-runtime-packages


FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1
COPY --from=qemu-build /out/qemu.deb /out/runtime-packages /tmp/qemu/
COPY --from=guacd-build /out/runtime-packages /tmp/guacd/
COPY --from=cape-build /build/venv-runtime-packages /tmp/cape/
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl cron dnsmasq-base gettext-base iproute2 iptables libvirt-clients \
        libvirt-daemon-system lsb-release nftables p7zip-full procps python3 software-properties-common \
        sudo supervisor swtpm swtpm-tools tcpdump unzip upx-ucl xorriso inetsim \
        $(cat /tmp/qemu/runtime-packages /tmp/guacd/runtime-packages /tmp/cape/venv-runtime-packages) \
        /tmp/qemu/qemu.deb \
    && rm -rf /tmp/qemu /tmp/guacd /tmp/cape
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
# libvirt 10.0 aborts every firmware lookup on the loongarch64 descriptor QEMU 9.2 installs
# ("unknown architecture"), so keep only the x86_64 descriptors.
RUN find /usr/share/qemu/firmware -name '*.json' ! -name '*x86_64*' -delete

RUN groupadd --system cape \
    && useradd --system --gid cape --home-dir /home/cape --create-home --shell /bin/bash cape \
    && (getent group kvm || groupadd --system kvm) \
    && usermod -aG libvirt,kvm cape \
    && echo "cape ALL=NOPASSWD: /usr/bin/tcpdump" > /etc/sudoers.d/tcpdump \
    && chmod 440 /etc/sudoers.d/tcpdump

COPY --from=cape-build --chown=cape:cape /opt/CAPEv2 /opt/CAPEv2
RUN bash /opt/CAPEv2/installer/cape2.sh suricata \
    && suricata-update --suricata /usr/bin/suricata --suricata-conf /etc/suricata/suricata.yaml -o /etc/suricata/rules/ \
    && rm -rf /var/lib/apt/lists/*

# Domain definitions live with the disks on the guest-images volume, so a recreated container
# keeps the guest, its snapshot and its CAPE registration.
RUN rm -rf /etc/libvirt/qemu \
    && mkdir -p /var/lib/libvirt/definitions /var/lib/libvirt/tartarus/kvm.conf.d /opt/CAPEv2/custom/conf \
    && install -d -o cape -g cape /opt/CAPEv2/storage /opt/CAPEv2/storage/analyses \
    && ln -s /var/lib/libvirt/definitions /etc/libvirt/qemu \
    && ln -s /var/lib/libvirt/tartarus/kvm.conf.d /opt/CAPEv2/custom/conf/kvm.conf.d

# In an interactive analysis the analyzer injects the monitor into everything Explorer starts, and a
# Store app (the Windows 11 Notepad) then hangs in ntdll waits and never opens a window. The
# analyzer is zipped from this directory and uploaded to the guest for every task, so patching it here
# fixes that without touching the guest. The patch fails the build if CAPE_REF moved its anchors.
COPY patches/skip-packaged-apps.py /tmp/skip-packaged-apps.py
RUN python3 /tmp/skip-packaged-apps.py /opt/CAPEv2/analyzer/windows/analyzer.py \
    && python3 -c "import ast; ast.parse(open('/opt/CAPEv2/analyzer/windows/analyzer.py').read())" \
    && grep -q 'skips_packaged_app(filepath, self.analyzer.package_name)' /opt/CAPEv2/analyzer/windows/analyzer.py \
    && rm /tmp/skip-packaged-apps.py

COPY libvirt/qemu.conf /etc/libvirt/qemu.conf
COPY supervisord.conf /etc/supervisor/conf.d/cape.conf
COPY templates/ /usr/local/lib/tartarus/templates/
COPY bin/ /usr/local/lib/tartarus/
COPY entrypoint.sh /usr/local/bin/cape-entrypoint
COPY --chown=cape:cape conf/ /opt/CAPEv2/custom/conf/

HEALTHCHECK --interval=15s --timeout=10s --start-period=120s --retries=5 \
    CMD virsh -q -c qemu:///system list >/dev/null \
        && curl -fsS -o /dev/null -H "Authorization: Token ${CAPE_API_TOKEN}" http://127.0.0.1:8000/apiv2/cuckoo/status/
ENTRYPOINT ["cape-entrypoint"]
