# S0c findings: Tamper Protection and "Defender off" (2026-10-15)

Done by the planner with the user watching, on the existing guest `win` (in an interactive analysis) and on
the cloned `win2` (restored from its snapshot, outside CAPE, no monitor). Nothing in the repo or in either
guest's snapshot was changed; `win` and `win2` were left shut off, `win2` unregistered, test analysis 223
deleted.

## Verdict

**"Defender off" can be built with no manual step.** One scripted click on Windows Security's Tamper
Protection toggle (through UI Automation, from the agent, in the logged-in user's session) turns
Tamper Protection off; the Defender policy keys that M0b's `provision.ps1` already writes then take effect;
the state survives a memory save and restore and a real reboot. The manual pause of decision 11 stays only as
the fallback for when the toggle cannot be found.

## What was observed

| # | Test | Where | Result |
|---|---|---|---|
| 1 | `Set-MpPreference -DisableRealtimeMonitoring $true` as elevated `Analyst`, Tamper Protection on | `win`, interactive analysis | "no error", nothing changes: `RealTime=True Tamper=True` before and after (as in M0b) |
| 2 | Registry write `HKLM\...\Windows Defender\Features\TamperProtection = 4`, elevated | `win` | Refused (access denied); value stays `1` |
| 3 | Open Windows Security from the desktop (Start menu, or through the agent) | `win`, interactive analysis | **Never draws a window**; `SecHealthUI.exe` runs, `Responding=True`. The shell then froze (the Start menu would not open) and ending the run hung in process termination for about 4 minutes, until the guest was shut off. The analyzer logged `Interactive mode: not injecting into packaged app SecHealthUI.exe`, so the M1 patch skips the injection and the app still does not show; the monitor in the surrounding processes is the likely cause (not proven) |
| 4 | The same, outside any analysis | `win2` restored from snapshot, no monitor | **The window opens normally** (page "Ustawienia ochrony przed wirusami i zagrożeniami", real-time protection on) |
| 5 | Toggle `Ochrona przed naruszeniami` (Tamper Protection) with UI Automation `TogglePattern.Toggle()` through the agent | `win2` | `ToggleState On → Off`; `Get-MpComputerStatus`: `IsTamperProtected=False`; registry `TamperProtection=4` |
| 6 | State right after the toggle | `win2` | `RealTimeProtectionEnabled=False` (without our asking), `AMServiceEnabled=True`, `AMRunningMode=Normal`, `Get-MpPreference.DisableRealtimeMonitoring=True` |
| 7 | Why real-time went off: policy keys | `win2` | `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection`: `DisableRealtimeMonitoring=1`, `DisableBehaviorMonitoring=1`, written by `provision.ps1:104-106` in M0b and ignored while Tamper Protection was on; they apply once it is off. `DisableAntiSpyware` is absent (Windows drops it) |
| 8 | EICAR (assembled at runtime from two halves) written to `C:\Users\Public` with Tamper off | `win2` | File still present after 12 s; no detection logged |
| 9 | `Set-MpPreference -DisableRealtimeMonitoring $false` with Tamper off | `win2` | "no error", nothing changes (`RealTime=False`, preference stays `True`): policy wins. Toggling the real-time switch in the GUI throws "Nierozpoznany błąd" (locked by policy) |
| 10 | Memory save and restore (`virsh save` / `virsh restore`, the mechanism of a snapshot revert) | `win2` | Unchanged: `RealTime=False Tamper=False pref=True TamperProtection(reg)=4` |
| 11 | A real reboot (`shutdown /r`, uptime 64 s afterwards, new Kernel-General start event) | `win2` | **Unchanged**: `RealTime=False Tamper=False pref=True TamperProtection=4`. (The user expected it often does not survive a restart; on this guest it did.) |
| 12 | The user's chain: `Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope CurrentUser -Force`, then `Set-MpPreference -DisableRealtimeMonitoring $true` (lines 3 and 4, which fetch and run code from the internet, were not run) | `win2` restored from snapshot, Tamper on | Command 1 sets the `CurrentUser` execution policy to `Bypass` and nothing else; Defender unchanged after it. Command 2: "no error", unchanged. The chain does not touch Tamper Protection |
| 13 | Is the Tamper toggle findable language-independently? | `win2` (pl-PL) | **No distinct identifier**: the page's five toggles all have `AutomationId=settingToggle`, `Class=ToggleSwitch`; the name is localized. Tamper Protection is the **fifth**, after real-time, dev-drive, cloud-delivered, sample submission |

## Consequences for the plan

1. **Decision 11:** the Windows profile's Defender-off build gets a scripted `tamper-off` step (open the
   page, find the toggle, toggle it, then **verify by `IsTamperProtected` becoming False**, which is language
   independent; take the toggle by its known localized names first, by position second). The user pause
   is the fallback if the verification fails.
2. **Snapshot ordering:** the policy keys must already be set when Tamper Protection goes off; the snapshot is
   taken after the toggle, as the user said. (Persistence across reboot and revert was measured, so the
   order matters only because the snapshot must contain the state.)
3. **Decision 10 / "Defender on from an off guest" (clones):** `Set-MpPreference` cannot do it, because
   policy wins. The route to test in C4 is: with Tamper off, delete the two policy keys, toggle Tamper back
   on, verify `RealTimeProtectionEnabled=True` and that EICAR is removed. **Not tested here.**
4. **Interactive analyses:** Windows Security cannot be used from the desktop of a monitored run, and trying
   to ends in a frozen shell and a slow shutdown. Another entry for the "Store apps" cost list in
   cape-integration (SecHealthUI, a packaged app outside `WindowsApps`' name pattern in practice: the patch
   skips it, yet it fails). Not fixed in M6; the wizard's own desktop has no monitor.
5. **Clones:** `win2`'s snapshot still has Edge windows open from S0d's browsing (INetSim pages in two
   tabs). A cloned guest should not carry open application windows from the source's session; the clone's
   own snapshot step is taken after a clean reboot, which closes them (C4 test: the snapshot taken by the
   clone pipeline shows an empty desktop).

## Could not verify

- A **UI language other than Polish** (the toggle's name, the page's layout, whether it is still the fifth
  toggle on another Windows build or after a Windows Update).
- That toggling by UI Automation works from a **freshly built** guest at the point of provisioning (first
  logon, before the guest has been used); it was done on a clone of the M0b guest.
- Turning Defender **on** again (item 3), and whether Defender in the `off` state still blocks anything the
  policy keys do not cover (cloud, SmartScreen is off by provisioning).
- Whether a guest with Tamper Protection off behaves differently under an analysis (capemon works with Defender
  on, M0b; not run with it off).
- Windows Update or a later Defender platform update turning Tamper Protection back on (updates are disabled
  in the guest, but the update settings were not checked).
