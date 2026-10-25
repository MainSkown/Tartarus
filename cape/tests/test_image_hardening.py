"""What the image must not give the `cape` user, the one that parses a sample's output.

The proofs against the running container are in scripts/verify-cape-hardening.sh; these keep the
Dockerfile from regressing to what C2 found.
"""

import re
from pathlib import Path

CAPE = Path(__file__).resolve().parents[1]
DOCKERFILE = (CAPE / "Dockerfile").read_text()


def runtime_stage() -> str:
    return DOCKERFILE[DOCKERFILE.rindex("FROM ubuntu:24.04\n") :]


def test_cape_leaves_the_suricata_group_the_installer_adds():
    # In a privileged container gid 993 is also the host's `disk` group: it opens the raw disks.
    stage = runtime_stage()

    assert "gpasswd -d cape suricata" in stage
    assert stage.index("cape2.sh suricata") < stage.index("gpasswd -d cape suricata")


def test_cape_has_no_sudo_rule():
    assert "sudoers.d" not in DOCKERFILE
    assert "NOPASSWD" not in DOCKERFILE


def test_tcpdump_runs_for_the_pcap_group_with_capture_capabilities_only():
    stage = runtime_stage()

    assert "setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump" in stage
    assert re.search(r"chgrp pcap /usr/bin/tcpdump\s*&&\s*chmod 0750 /usr/bin/tcpdump", stage)
    assert "usermod -aG pcap cape" in stage


def test_the_pcap_group_has_a_gid_no_host_group_shares():
    # CAPE's own check wants cape in `pcap`; its image gid (994) is the host's `clock` group.
    assert re.search(r"groupmod --gid 640\d\d pcap", runtime_stage())


def copies_into_cape_tree() -> list[str]:
    return [
        line
        for line in DOCKERFILE.splitlines()
        if line.startswith("COPY") and "/opt/CAPEv2" in line
    ]


def test_the_rooter_runs_root_and_loads_code_cape_cannot_write():
    copies = copies_into_cape_tree()

    assert copies, "the image copies CAPE somewhere"
    assert not [line for line in copies if "--chown" in line]


def test_cape_owns_only_what_it_writes_while_running():
    stage = runtime_stage().replace("\\\n", " ")
    directories = {
        path
        for group in re.findall(r"install -d -o cape -g cape ((?:/\S+ ?)+)", stage)
        for path in group.split()
    }
    files = re.findall(r"install -o cape -g cape -m 0644 /dev/null (\S+)", stage)

    assert directories == {
        "/opt/CAPEv2/storage",
        "/opt/CAPEv2/storage/analyses",
        "/opt/CAPEv2/log",
        "/opt/CAPEv2/data/feeds",
        "/var/lib/cape-web",
    }
    assert files == ["/opt/CAPEv2/data/yara/index_memory.yarc"]


def test_the_image_installs_the_web_settings_and_a_secret_key_cape_need_not_write():
    stage = runtime_stage()

    assert "COPY cape/web/ /opt/CAPEv2/web/web/" in stage
    # settings.py writes secret_key.py when it is missing, which a root-owned tree would refuse.
    assert re.search(r"RUN .*secrets\.token_urlsafe.*> /opt/CAPEv2/web/web/secret_key\.py", stage)


def healthcheck() -> str:
    return DOCKERFILE[DOCKERFILE.index("HEALTHCHECK") : DOCKERFILE.index("ENTRYPOINT")].replace(
        "\\\n", " "
    )


def test_the_healthcheck_keeps_the_api_token_off_command_lines():
    check = healthcheck()

    # printf is a shell builtin and curl reads its headers from stdin, so no process is started
    # with the token among its arguments (every user in the container can read those).
    assert "printf" in check
    assert "curl" in check
    assert "-K -" in check
    assert "-H" not in check
    assert "CAPE_API_TOKEN" not in check.split("|")[-1]
