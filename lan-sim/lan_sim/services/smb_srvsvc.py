"""The server service's share enumeration: what `smbclient -L` and `nxc --shares` ask for."""

from collections.abc import Callable
from typing import NamedTuple
from uuid import UUID

from impacket.dcerpc.v5 import srvs
from impacket.dcerpc.v5.dtypes import NULL

from lan_sim.services.smb_rpc import FAULT_OP_RANGE_ERROR, RpcFaultError

OPNUM_SHARE_ENUM = 15
ERROR_INVALID_LEVEL = 124
STYPE_DISK, STYPE_HIDDEN_DISK, STYPE_HIDDEN_IPC = 0, 0x80000000, 0x80000003


class ShareEntry(NamedTuple):
    name: str
    share_type: int
    remark: str


class SrvsvcInterface:
    uuid = UUID("4B324FC8-1670-01D3-1278-5A47BF6EE188").bytes_le
    major_version = 3
    pipe_name = "srvsvc"

    def __init__(self, shares: Callable[[], list[ShareEntry]]) -> None:
        self._shares = shares

    def call(self, opnum: int, stub: bytes) -> bytes:
        if opnum != OPNUM_SHARE_ENUM:
            raise RpcFaultError(FAULT_OP_RANGE_ERROR)
        level = srvs.NetrShareEnum(stub)["InfoStruct"]["Level"]
        shares = self._shares()
        response = srvs.NetrShareEnumResponse()
        reported = level if level in (0, 1) else 1
        response["InfoStruct"]["Level"] = reported
        response["InfoStruct"]["ShareInfo"]["tag"] = reported
        container = (
            srvs.SHARE_INFO_1_CONTAINER() if reported == 1 else srvs.SHARE_INFO_0_CONTAINER()
        )
        entries = shares if level in (0, 1) else []
        container["EntriesRead"] = len(entries)
        container["Buffer"] = [_info(entry, reported) for entry in entries] or NULL
        response["InfoStruct"]["ShareInfo"][f"Level{reported}"] = container
        response["TotalEntries"] = len(entries)
        response["ResumeHandle"] = NULL
        response["ErrorCode"] = 0 if level in (0, 1) else ERROR_INVALID_LEVEL
        return bytes(response.getData())


def _info(entry: ShareEntry, level: int):
    if level == 0:
        info = srvs.SHARE_INFO_0()
        info["shi0_netname"] = entry.name + "\x00"
        return info
    info = srvs.SHARE_INFO_1()
    info["shi1_netname"] = entry.name + "\x00"
    info["shi1_type"] = entry.share_type
    info["shi1_remark"] = entry.remark + "\x00"
    return info
