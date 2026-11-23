"""DCERPC over the pipes: the service control manager and the share enumeration.

The client is impacket's own scmr and srvs code over an SMB connection to the real service, plus
hand-made PDUs for what no client sends. Nothing a client puts in a service's binary path may ever
run: the tests point it at a file-creating command and look for the file.
"""

import contextlib
import random
import struct
import time
from uuid import UUID

import pytest
from impacket import nt_errors
from impacket.dcerpc.v5 import scmr, srvs, transport
from impacket.dcerpc.v5.rpcrt import (
    RPC_C_AUTHN_LEVEL_CONNECT,
    RPC_C_AUTHN_LEVEL_PKT_PRIVACY,
    RPC_C_AUTHN_WINNT,
    DCERPCException,
)
from impacket.smbconnection import SessionError
from support import FakeClock
from test_service_smb_rpc_support import HOST, RecordingLog
from test_service_smb_support import DOMAIN, HOST_ADDRESS, PASSWORD, USER, SmbWorld

from lan_sim.services import smb_rpc
from lan_sim.services.smb_rpc import RpcServer
from lan_sim.services.smb_services import ServiceTable
from lan_sim.services.smb_svcctl import SvcctlInterface


@pytest.fixture
def world(tmp_path):
    with SmbWorld(tmp_path, shares=["Public"]) as running:
        yield running


def pipe(world, smb, name, interface, *, auth_level=None, password=PASSWORD):  # noqa: PLR0913
    rpc = transport.SMBTransport(HOST_ADDRESS, world.port, filename=f"\\{name}", smb_connection=smb)
    dce = rpc.get_dce_rpc()
    if auth_level is not None:
        dce.set_credentials(USER, password, DOMAIN)
        dce.set_auth_type(RPC_C_AUTHN_WINNT)
        dce.set_auth_level(auth_level)
    dce.connect()
    dce.bind(interface)
    return dce


def svcctl(world, smb, **options):
    dce = pipe(world, smb, "svcctl", scmr.MSRPC_UUID_SCMR, **options)
    return dce, scmr.hROpenSCManagerW(dce)["lpScHandle"]


def test_the_psexec_sequence_is_logged_and_nothing_is_started(world, tmp_path):
    marker = tmp_path / "pwned"
    smb = world.client()
    dce, scm = svcctl(world, smb)
    binary = f"touch {marker}"
    created = scmr.hRCreateServiceW(
        dce,
        scm,
        "evilsvc\x00",
        "Evil Service\x00",
        lpBinaryPathName=binary + "\x00",
        dwStartType=scmr.SERVICE_DEMAND_START,
    )
    handle = created["lpServiceHandle"]
    scmr.hRStartServiceW(dce, handle)
    status = scmr.hRQueryServiceStatus(dce, handle)
    assert status["lpServiceStatus"]["dwCurrentState"] in (
        scmr.SERVICE_RUNNING,
        scmr.SERVICE_START_PENDING,
    )
    scmr.hRDeleteService(dce, handle)
    scmr.hRCloseServiceHandle(dce, handle)
    time.sleep(0.2)
    assert not marker.exists()
    [creation] = world.requests("svcctl CreateService")
    assert creation["detail"] == f"evilsvc, {binary}"
    [start] = world.requests("svcctl StartService")
    assert "evilsvc" in start["detail"]
    assert binary in start["detail"]
    assert world.requests("svcctl DeleteService")


def test_the_manager_keeps_services_between_calls_and_connections(world):
    smb = world.client()
    dce, scm = svcctl(world, smb)
    scmr.hRCreateServiceW(dce, scm, "persist\x00", "persist\x00", lpBinaryPathName="C:\\x.exe\x00")
    again = world.client()
    dce2, scm2 = svcctl(world, again)
    opened = scmr.hROpenServiceW(dce2, scm2, "PERSIST\x00")
    assert opened["lpServiceHandle"]
    names = [s["lpServiceName"].rstrip("\x00") for s in scmr.hREnumServicesStatusW(dce2, scm2)]
    assert "persist" in names
    assert "Spooler" in names


def test_creating_a_service_twice_and_opening_a_missing_one_fail_with_win32_codes(world):
    smb = world.client()
    dce, scm = svcctl(world, smb)
    scmr.hRCreateServiceW(dce, scm, "dup\x00", "dup\x00", lpBinaryPathName="a\x00")
    with pytest.raises(DCERPCException) as duplicate:
        scmr.hRCreateServiceW(dce, scm, "dup\x00", "dup\x00", lpBinaryPathName="a\x00")
    assert duplicate.value.get_error_code() == 1073, str(duplicate.value)
    with pytest.raises(DCERPCException) as missing:
        scmr.hROpenServiceW(dce, scm, "ghost\x00")
    assert missing.value.get_error_code() == 1060


def test_a_binary_path_too_big_for_one_fragment_is_reassembled(world):
    smb = world.client()
    dce, scm = svcctl(world, smb)
    path = "C:\\" + "a" * 9000 + ".exe"
    scmr.hRCreateServiceW(dce, scm, "big\x00", "big\x00", lpBinaryPathName=path + "\x00")
    [creation] = world.requests("svcctl CreateService")
    assert creation["detail"].startswith("big, C:\\aaaa")


def test_a_bind_with_ntlm_authentication_at_connect_level_is_served(world):
    smb = world.client()
    _dce, scm = svcctl(world, smb, auth_level=RPC_C_AUTHN_LEVEL_CONNECT)
    assert scm
    logins = [r for r in world.records("login-attempt") if r["success"]]
    assert len(logins) == 2


def test_a_bind_with_the_wrong_password_gets_no_service(world):
    smb = world.client()
    with pytest.raises((DCERPCException, SessionError)):
        _dce, _scm = svcctl(world, smb, auth_level=RPC_C_AUTHN_LEVEL_CONNECT, password="nope")
    failed = [r for r in world.records("login-attempt") if not r["success"]]
    assert len(failed) == 1


def test_a_sealed_bind_as_sc_exe_makes_is_refused_without_hanging(world):
    smb = world.client()
    started = time.monotonic()
    with pytest.raises((DCERPCException, SessionError)):
        svcctl(world, smb, auth_level=RPC_C_AUTHN_LEVEL_PKT_PRIVACY)
    assert time.monotonic() - started < 5
    assert world.requests("svcctl bind")


def test_share_enumeration_lists_the_shares_with_their_types(world):
    smb = world.client()
    dce = pipe(world, smb, "srvsvc", srvs.MSRPC_UUID_SRVS)
    response = srvs.hNetrShareEnum(dce, 1)
    shares = {
        entry["shi1_netname"].rstrip("\x00"): entry["shi1_type"]
        for entry in response["InfoStruct"]["ShareInfo"]["Level1"]["Buffer"]
    }
    assert set(shares) == {"ADMIN$", "C$", "IPC$", "Public"}
    assert shares["Public"] == srvs.STYPE_DISKTREE
    assert shares["IPC$"] == srvs.STYPE_IPC | srvs.STYPE_SPECIAL
    assert shares["ADMIN$"] == srvs.STYPE_SPECIAL


def test_the_clients_own_list_shares_works(world):
    smb = world.client()
    names = {share["shi1_netname"].rstrip("\x00") for share in smb.listShares()}
    assert {"ADMIN$", "C$", "IPC$"} <= names


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("wkssvc", nt_errors.STATUS_NOT_SUPPORTED),
        ("lsarpc", nt_errors.STATUS_NOT_SUPPORTED),
        ("samr", nt_errors.STATUS_OBJECT_NAME_NOT_FOUND),
        ("evilpipe", nt_errors.STATUS_OBJECT_NAME_NOT_FOUND),
    ],
)
def test_other_pipes_are_refused(world, name, status):
    smb = world.client()
    tree = smb.connectTree("IPC$")
    with pytest.raises(SessionError) as refused:
        smb.createFile(tree, name)
    assert refused.value.getErrorCode() == status


# --- the engine on hand-made PDUs ----------------------------------------------------------------


SCM_UUID = "367ABB81-9844-35F1-AD32-98F038001003"


def header(ptype, body, *, flags=3, call_id=1, auth=b""):
    frag = 16 + len(body) + len(auth)
    return (
        struct.pack("<BBBB4sHHI", 5, 0, ptype, flags, b"\x10\x00\x00\x00", frag, 0, call_id) + body
    )


def bind_pdu(abstract_uuid=SCM_UUID, version=2, transfer="8a885d04-1ceb-11c9-9fe8-08002b104860"):
    context = struct.pack("<HBB", 0, 1, 0)
    context += UUID(abstract_uuid).bytes_le + struct.pack("<HH", version, 0)
    context += UUID(transfer).bytes_le + struct.pack("<HH", 2, 0)
    return header(11, struct.pack("<HHIBBH", 4280, 4280, 0, 1, 0, 0) + context)


def server():
    return RpcServer(
        SvcctlInterface(ServiceTable(), RecordingLog()), HOST, FakeClock(), RecordingLog()
    )


def test_a_bind_is_acknowledged_for_the_known_interface():
    [ack] = server().process(bind_pdu())
    assert ack[2] == 12
    result = struct.unpack_from("<H", ack, len(ack) - 24)[0]
    assert result == 0


def test_a_bind_for_another_interface_is_rejected_in_the_ack():
    [ack] = server().process(
        bind_pdu(abstract_uuid="12345678-1234-abcd-ef00-0123456789ab", version=0)
    )
    assert ack[2] == 12
    assert struct.unpack_from("<H", ack, len(ack) - 24)[0] != 0


def test_a_request_before_any_bind_faults_instead_of_hanging():
    request = header(0, struct.pack("<IHH", 0, 0, 15))
    [fault] = server().process(request)
    assert fault[2] == 3


def test_a_big_endian_bind_is_not_accepted():
    pdu = bytearray(bind_pdu())
    pdu[4] = 0x00
    with pytest.raises(smb_rpc.RpcFormatError):
        server().process(bytes(pdu))


def test_truncated_and_inconsistent_pdus_are_format_errors():
    good = bind_pdu()
    for cut in range(0, len(good) - 1):
        with pytest.raises(smb_rpc.RpcFormatError):
            server().process(good[:cut])
    with pytest.raises(smb_rpc.RpcFormatError):
        server().process(good + b"\x00")


def test_random_and_mutated_pdus_never_raise_anything_else():
    generator = random.Random(7)  # noqa: S311 - a seeded generator makes the fuzz repeatable
    seeds = [bind_pdu(), header(0, struct.pack("<IHH", 0, 0, 15) + b"\x00" * 40)]
    engine = server()
    engine.process(bind_pdu())
    started = time.monotonic()
    for _ in range(3000):
        blob = bytearray(generator.choice(seeds))
        for _ in range(generator.randrange(1, 6)):
            blob[generator.randrange(len(blob))] = generator.randrange(256)
        if generator.random() < 0.5:
            struct.pack_into("<H", blob, 8, len(blob))
        with contextlib.suppress(smb_rpc.RpcFormatError):
            engine.process(bytes(blob))
    for _ in range(2000):
        with contextlib.suppress(smb_rpc.RpcFormatError):
            engine.process(generator.randbytes(generator.randrange(0, 120)))
    assert time.monotonic() - started < 20
