# Tartarus rules

Rules written for Tartarus itself, kept apart from `../default/` (SigmaHQ's rules under the DRL 1.1
licence, copied unmodified) and `../custom/` (yours).

| Rule | Level | Why it exists |
|---|---|---|
| `tartarus_selftest_registry_marker.yml` | informational | The end-to-end sample (`benign.exe`) writes `HKCU\Software\Tartarus\SelfTest` on every run; this rule fires on it so `make e2e` can check Sigma detections live and in the final index. |

These are Tartarus's own work and carry no upstream licence obligations. The backend reads this
directory with the rest of `rules/sigma/`; the rules can be switched off on the Rules page like any other.
