# Tartarus rules

Rules written for Tartarus itself, kept apart from `../default/` (SigmaHQ's rules under the DRL 1.1
licence, copied unmodified) and `../custom/` (yours).

| Rule | Level | Why it exists |
|---|---|---|
| `tartarus_selftest_registry_marker.yml` | informational | The end-to-end sample (`benign.exe`) writes `HKCU\Software\Tartarus\SelfTest` on every run; this rule fires on it so `make e2e` can check Sigma detections live and in the final index. |
| `lan_connect_smb.yml` | informational | A process that is not a system one connects to SMB (445) on a fake LAN host (T1021.002). |
| `lan_connect_rdp.yml` | low | The same over RDP (3389, T1021.001). |
| `lan_connect_winrm.yml` | low | The same over WinRM (5985, 5986, T1021.006). |
| `lan_connect_ssh.yml` | low | The same over SSH (22, T1021.004). |
| `lan_connect_mssql.yml` | low | The same over MSSQL (1433, T1210). |
| `lan_admin_share_access.yml` | medium | The sample connects to `ADMIN$`, `C$` or `IPC$` on a fake host (T1021.002). |
| `lan_executable_written_to_admin_share.yml` | high | An `.exe`, `.dll`, `.bat` or `.ps1` is written to `ADMIN$` or `C$` on a fake host (T1570, T1021.002). |
| `lan_service_created_over_smb.yml` | high | `svcctl CreateService` against a fake host, the PsExec way (T1569.002, T1021.002). |
| `lan_credential_spray.yml` | high | One user name is tried on many fake hosts, from the derived `lan-credential-spray` event (T1110.003). |
| `lan_sweep.yml` | medium | One process contacts many fake hosts on one port, from the derived `lan-sweep` event (T1046). |
| `lan_fan_out.yml` | medium | One process reaches many fake hosts over several services, from the derived `lan-fan-out` event (T1021, T1210). |

The `lan_*` rules read the events of the fake local network (`docs/features/fake-lan.md`); they fire only
on an analysis run with a preset. Their thresholds are the ingest's (`backend/app/ingest/lan_derived.py`), not the
rules'. They are `experimental`: the numbers are starting values to tune on real runs.

These are Tartarus's own work and carry no upstream licence obligations. The backend reads this
directory with the rest of `rules/sigma/`; the rules can be switched off on the Rules page like any other.
