# SMB service notes (fake LAN, lan-sim/lan_sim/services/smb*.py)

Run: `cd lan-sim && uv run --with pytest pytest -q tests/test_service_smb*.py`; whole suite `uv run --with pytest pytest -q`.

## Plan (each step ends in a check that can fail)
1. Wire layer (`smb_wire.py`): NBSS framing, SMB2 header, compound split, SMB1 negotiate detection. Check: parser tests, fuzz with a bounded time.
2. Signing (`smb_signing.py`): HMAC-SHA256, AES-CMAC, KDF, 3.1.1 preauth hash. Check: known answers computed with impacket's own code.
3. Negotiate + session setup + NTLM + signed session (`smb.py`). Check: impacket `SMBConnection` per dialect with response signatures verified by a hook in the test.
4. Virtual store (`smb_store.py`), tree connect, create/read/write/close/query/set info. Check: impacket listPath, putFile, getFile, caps, traversal.
5. DCERPC (`smb_rpc.py`), svcctl (`smb_svcctl.py`), srvsvc. Check: impacket scmr and srvs calls, psexec sequence, nothing executed.
6. Hardening: fuzz whole connection, caps, no host file. Optional docker cross-check.

## Done
- Step 1: smb_wire.py (217 lines) + tests/test_service_smb_wire.py, 21 tests pass (failed first with ModuleNotFoundError).
- Step 2: smb_signing.py + tests/test_service_smb_signing.py (known answers against impacket crypto), 13 pass. 34 with wire.
- Step 4a: smb_store.py (in-memory store, strict names, caps, budget) + tests/test_service_smb_store.py, 45 pass.

- Step 3: smb.py (connection loop, SMB1 negotiate, compounds, NTLM session setup, signing, tree connect, ioctl) + smb_messages/smb_info/smb_types/smb_files/smb_state/smb_services/smb_pipes(stub). tests/test_service_smb.py 12 pass: impacket login per dialect 2.0.2/2.1/3.0/3.1.1 with every response signature verified by the test hook (mutation: wrong KDF label and corrupted response signature both fail the tests), wrong password and unknown user refused+logged, bad request signature refused, SMB1 refusal, SMB1->SMB2 upgrade, garbage.
- Step 4: tests/test_service_smb_files.py (list, put, get, 20 MiB cap, session cap, traversal, rename/delete, persistence across connections, no host file, drop mid-write) 30 tests; whole smb set 120 pass.
- Step 5: smb_rpc.py (DCERPC engine, auth bind at connect level, bind_nak for sealed), smb_svcctl.py, smb_srvsvc.py, smb_pipes.py, smb_services.py; tests/test_service_smb_rpc.py 19 pass (impacket scmr psexec sequence, nothing executed, persistence across connections, fragmented 9000-char path, authenticated bind ok/wrong pw/sealed refused, srvsvc share enum + listShares, pipe refusals, engine fuzz). smb set total 139 pass.

## Decisions
- impacket's SMB3 client does NOT verify response signatures: the tests wrap `SMB3.recvSMB` and verify with the client's own key.
- Read budget: no framework hook; `Connection.limits` is a plain field of a non-frozen dataclass, so smb.py replaces it with a larger `max_bytes_read_per_connection` only AFTER a verified login (unauthenticated stays at 64 KiB). Needs a proper `Connection.raise_read_budget` in the framework later.
- svcctl log name follows the brief ('svcctl CreateService'), SCHEMA.md example says 'svcctl.CreateService': mismatch to report.

- Step 6: tests/test_service_smb_messages.py (29), tests/test_service_smb_hostile.py (10: signed compounds, unauthenticated/unsigned refusals, oversize frame, SMB1 2.002, random signed requests over an authenticated connection, authenticated read budget end), tests/test_service_smb_units.py (25). serve() catches SmbFormatError/RpcFormatError/NtlmFormatError and logs `malformed-smb`. Mutation checks (accept any password, no request signature check, no name check, no file cap, no session cap, wrong hash, wrong svcctl log name, no read budget lift) each fail a test. ruff check and format clean for the whole lan-sim; whole suite 845 passed (203 are SMB).
- nmap cross-check (momos-manual-pentest-tools image, host network, port is ephemeral): `-sV` sends the SMB1-only probe, gets the SMB1 reply with dialect 0xFFFF (status success, flags 0x98/0xC801 like Windows) but does not name the service on a non-standard port; `--script +smb-protocols,+smb2-security-mode,+smb2-capabilities,+smb2-time --script-args smbport=PORT` lists dialects 2.0.2, 2.1.0, 3.0.0, 3.0.2, 3.1.1 (no SMB1), "signing enabled and required", time. smbclient is not in any local image: not run.

## Not done / limits
- Real Windows client never run against this build (the spike's Windows guests were shut off); compound chains, QUERY_DIRECTORY classes and signing on 3.0/3.1.1 are proven with impacket and hand-built messages only.
- sc.exe (sealed RPC) is refused with bind_nak and logged as `svcctl bind`; wmiexec has no DCOM here. Both end cleanly.
- Capabilities are all off (no DFS, leasing, large MTU, encryption); I/O is limited to 64 KiB per request.
- No MIC verification of the NTLM AUTHENTICATE (ntlm.py does not expose it); the NTLMv2 proof is verified.
- Stored state (files, services) is per lan session and host, kept in memory for the 4 most recent sessions; nothing frees it when a session ends (needs a close hook in the framework).

## Running
- nothing

## Next
- planner review of the diff; shared-module changes listed in the report (Connection.raise_read_budget, session-close hook, SCHEMA name).
