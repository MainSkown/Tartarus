# S0d findings: cloning the existing guest by hand

Date: 2026-10-15. Everything here was observed on the real stack (cape and postgres running, nothing
else), by hand, with no product code written or changed. Scratch files (scripts, screenshots, raw
outputs, the timeline) are in
`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/7ecb9355-8642-4512-8a41-80cb1a8c2d4d/scratchpad/s0d/`.

## Answer

**Yes. A new Windows guest can be made from `win` without reinstalling**, using exactly the design of
decision 15: `qemu-img convert` of the source's base disk, a copy of the nvram, a new domain with a new
UUID/MAC/serials and a fresh swtpm, a cold boot, then IP and computer name through the agent. The clone
booted cleanly (no repair screen, no chkdsk, no activation or Secure Boot complaint, no prompt), the agent
answered 53 s after `virsh start`, the autologon user logged in, the new name and the new static IP
survived reboots, the snapshot was taken, and a revert of that snapshot brings the agent back in 1 s at
the new IP with the new MAC and name. Nothing was blocked and nothing needed a human.

The whole thing took **11 min 49 s** wall-clock from "start convert" (15:28:21) to "snapshot taken"
(15:40:10), against 13.6 min for a full build. That figure includes about 6 minutes of my own diagnostic
queries between steps; the machine time of the steps themselves is about **3.5 minutes** (table below).

Two surprises that change decision 15's text, details below: (1) `win`'s base disk comes up with the NIC on
**DHCP, not on the static address** `provision.ps1` set, whatever the MAC; (2) the agent's PowerShell is
**32-bit**, so `manage-bde`, `query` and the 64-bit registry view are missing unless the Sysnative path is used.

## Per-phase timings and disk

| Phase | Wall-clock | Disk / notes |
|---|---|---|
| `qemu-img convert -O qcow2` of `win.qcow2` to `win2.qcow2` | 11 s | `du` 17,348,272 KB (16.5 GiB), apparent 17,764,319,232 B; source `win.qcow2` is 17,470,864 KB `du`, 17,905,025,024 B apparent. `qemu-img check` clean |
| nvram copy | under 1 s | 540,672 B |
| `virsh define` + `virsh start` | 3 s | swtpm state dir created for the new UUID (20 KB) |
| Cold boot to agent answering (still at `.10`) | 53 s (first screenshot at 22 s already shows the Welcome/autologon screen; desktop with Edge at 37 s) | |
| Reconfigure through the agent (rename, IP, `Restart-Computer`) | script ran 15:34:06 to 15:34:14 (rename 0 s, IP 3 s, 3 s sleep) | |
| Reboot back to agent at `.11` | not timed exactly; upper bound 42 s (agent answered on the first probe of a later loop that started 15:34:56) | clean shutdown, no Kernel-Power 41 on the next boot |
| ACPI shutdown | 7 s | |
| Boot to agent (static `.11`) | 24 s | |
| Idle | 60 s | as `build-guest.sh` |
| `snapshot-create-as` external disk+memory | 2 s | `win2-clean.mem` 3,134,602,583 B (3,061,140 KB `du`); overlay 452 KB |
| Revert test (extra) | 1 s to restore, agent answered at once | |

Total for `win2` at the end: `win2.qcow2` 17,891,496 KB `du` (apparent 18,362,466,304 B; **+543 MB** written into the base
by the work above: boots, rename, BitLocker conversion running in the background), `win2-clean.mem`
3,061,140 KB, overlay about 28 MB after the revert test: **about 21.0 GB (19.5 GiB)**, against decision 5's "about 22 GB".

## The exact command sequence that worked

All on the host in the repo root, `V="docker compose exec -T cape virsh -c qemu:///system"`.

```bash
# 0. identity (the script's own generator) and the label for the paths
scripts/build-guest.sh identity > win2.identity
set -a; . win2.identity; set +a            # GUEST_UUID GUEST_MAC SMBIOS_SERIAL SMBIOS_BOARD_SERIAL SMBIOS_DISK_SERIAL

# 1. copy the base disk (NOT win-clean.mem, NOT the overlay) and the nvram, fix ownership
docker compose exec -T cape sh -c '
  qemu-img convert -O qcow2 /var/lib/libvirt/images/win.qcow2 /var/lib/libvirt/images/win2.qcow2 &&
  chown libvirt-qemu:kvm /var/lib/libvirt/images/win2.qcow2 &&
  cp -p /var/lib/libvirt/nvram/win_VARS.fd /var/lib/libvirt/nvram/win2_VARS.fd'

# 2. define and cold-boot (render-domain run = no CDs, boot from disk)
GUEST_LABEL=win2 scripts/build-guest.sh render-domain run > win2.xml
docker compose cp win2.xml cape:/tmp/win2.xml
$V define /tmp/win2.xml && $V start win2

# 3. wait for the agent at the SOURCE's address (here DHCP gave .10; see "static IP" below)
until [ "$(docker compose exec -T cape curl -s -o /dev/null -w '%{http_code}' -m 3 http://192.168.150.10:8000/)" = 200 ]; do sleep 2; done

# 4. store reconfig.ps1 and run it ASYNC through the 64-bit PowerShell; the agent connection drops when the IP changes
docker compose exec -T cape curl -s -F 'filepath=C:\Windows\Temp\reconfig.ps1' -F file=@/tmp/reconfig.ps1 http://192.168.150.10:8000/store
docker compose exec -T cape curl -s -F async=1 \
  -F 'command=C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Windows/Temp/reconfig.ps1' \
  http://192.168.150.10:8000/execute
# reconfig.ps1 (scratchpad/s0d/reconfig.ps1): Rename-Computer -NewName LAPTOP-4Q8R2MZ -Force;
#   adapter = Get-NetAdapter -Physical | ? Status -ne Disabled | select -First 1   (provision.ps1's lookup, unchanged)
#   Remove-NetIPAddress / Remove-NetRoute (IPv4) on it; New-NetIPAddress .11/24 -DefaultGateway .1; Set-DnsClientServerAddress .1;
#   Start-Sleep 3; Restart-Computer -Force
# the agent answers at 192.168.150.11:8000 once Windows is back.

# 5. clean ACPI shutdown, boot, wait for the agent at .11, idle 60 s, snapshot, power off
$V shutdown win2   # wait until domstate is "shut off"
$V start win2      # wait for the agent at .11
sleep 60
$V snapshot-create-as win2 tartarus-clean "Tartarus clean baseline" --atomic \
  --memspec "file=/var/lib/libvirt/images/win2-clean.mem,snapshot=external" \
  --diskspec "sda,snapshot=external,file=/var/lib/libvirt/images/win2-clean.qcow2"
$V destroy win2
```

Helper used for every agent call: copy a `.ps1` into the container, `POST /store` it to
`C:\Windows\Temp\<name>.ps1`, `POST /execute` with `command=...powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/Windows/Temp/<name>.ps1`,
read `stdout` from the JSON.

Where the base disk is: `win` has no `win-clean.qcow2` on disk. The snapshot XML names it, but each revert
replaces the overlay with `win.<epoch>` (here `win.1792021253`, 784 MiB, `backing file: win.qcow2`). The base
is therefore found as the backing file of the domain's current disk (`qemu-img info --backing-chain`), not by name.

## What the screen and the guest showed

Screenshots (all `virsh screenshot`, which already writes PNG; copied out with `docker compose cp`):
- `w000.png`, 22 s after start: the standard Windows 11 lock/autologon screen, user "Analyst", spinner, "Zapraszamy!" (Welcome). No recovery, "preparing automatic repair", chkdsk, "setting up devices", activation, Secure Boot or hardware-change screen.
- `w015.png`/`w031.png`: desktop with Edge open on the INetSim default page (`www.msftconnecttest.com/redirect`, Windows' captive-portal probe answered by INetSim), taskbar normal.
- `after-reboot.png`, `after-revert.png`: the same desktop at 13:37 and 13:40; two Edge tabs.
- I did not capture the first 20 seconds after `virsh start` (firmware logo, Windows boot logo).

Inside the guest:
- **Cold boot of a crash-consistent copy:** Kernel-Power 41 ("restarted without a clean shutdown") and EventLog 6008 ("previous shutdown at 02:26:54 on 13.10.2026 was unexpected") at the first boot only. Ntfs event 98 "volume healthy, nothing to do" for C: and the recovery volume, no chkdsk, no volsnap or disk or NDIS errors. After the rename reboot and after the ACPI shutdown there was no 41. The only Level 2 events at every boot, in the source's image too: `luafv` fails to start (UAC is off) and DistributedCOM 10001 (CLSID `{6FA05A24-...}`), both unrelated to cloning.
- **Autologon:** yes. `AutoAdminLogon=1`, `DefaultUserName=Analyst`, `DefaultDomainName` empty, `AutoLogonCount=996`, so the rename does not touch it. After the rename `Win32_ComputerSystem.UserName` is `LAPTOP-4Q8R2MZ\Analyst`. The `CAPE Agent` scheduled task has principal `Analyst` (local, no machine prefix), stays `Running` and came back by itself after the rename reboot.
- **New TPM:** Windows noticed. At 13:29:31 `TPM-WMI 519 "The TPM has been cleared. Reason: SRK has changed"`, then 1027 ownership taken, 1025 "provisioned and ready" at 13:29:36 (about 45 s after boot, no prompt, no restart needed). `Get-Tpm`: present, ready, enabled, activated, owned, `ManufacturerIdTxt IBM`, version 8217.4131.22.13878 (swtpm). The same 519/1027/1025 trio appears on the first boot of every clone.
- **Secure Boot:** `Confirm-SecureBootUEFI` True after the copy, with the copied nvram.
- **BitLocker:** `VolumeStatus EncryptionInProgress`, `ProtectionStatus Off`, `KeyProtector {}` (no TPM protector, so nothing was sealed to the old TPM and a fresh TPM cannot lock the clone out). Percentage 83.8% at 3 minutes of uptime, 84% four minutes later: a device-encryption conversion that was already in progress in the source image keeps running in the clone and writes to the disk. I did not look at `win`'s own state (it stayed off), so I cannot say whether this is new or inherited; it is inherited from the base disk by construction.
- **Activation:** `slmgr /xpr` says "notification mode" (not activated), no product key was ever given. Not a clone effect; not compared with `win`.
- **Adapter:** after the MAC change Windows kept the same adapter instance: name `Ethernet`, `ifIndex 3`, `InterfaceGuid {0B58BB21-E9D2-4E55-94A4-3821DD181163}`, only one adapter in the class key (no ghost "#2"). The DHCPv6 client logged event 1009 "MAC 0x001422C89700 not found in DUID, new DUID generated" on the first boot with the new MAC, so Windows did notice the change; it just did not treat it as new hardware.
- **provision.ps1's lookup** (`Get-NetAdapter -Physical | Where-Object Status -ne 'Disabled' | Select-Object -First 1`) returned `Ethernet`, ifIndex 3, status Up, the new MAC, on every clone. The reconfigure step does not need to find the adapter by hardware.

### Static IP: the surprise
On the first boot the adapter had `Dhcp Enabled`, `PrefixOrigin Dhcp`, `IPv4 192.168.150.10`, lease from `192.168.150.1`
(libvirt's dnsmasq, whose only DHCP address is `.10`, 10-minute lease, `dhcp-lease-max=1`). The agent was
therefore reachable at `.10` only because of DHCP. `provision.log` of the source says the static address was set ("adapter 'Ethernet' set to 192.168.150.10")
and the spec says the guest is static, so I tested whether the MAC change caused this:
- **win2y:** a second throwaway clone of `win.qcow2` with the **same MAC as `win`** (`00:14:22:c8:97:00`), new UUID. It also came up on DHCP (`Dhcp Enabled`, lease for `c8:97:00`). So the MAC change is not the cause.
- **win2x:** a throwaway clone of `win2.qcow2` (static `.11` set after the first boot) with a third MAC `00:14:22:87:7f:4c`. It came up with `.11`, `Dhcp Disabled`, `Manual`, same adapter GUID. So a MAC change does not drop a static address either.

Conclusion from the two experiments: **the base disk of `win` cold-boots with the NIC on DHCP**, independent of the identity. Why
the static address set by `provision.ps1` is not what the base disk holds I did not find out (the source's own
network-profile log shows its 02:26:54 boot identifying the network in the same second, which looks static; the clone's took 3 s,
which looks like DHCP). Whether `win` itself, cold-booted, would also be on DHCP I did not test (it must stay untouched).
Both throwaway clones and their files were removed (`undefine --nvram --tpm`, files deleted).

### What differs between `win` and `win2` (guest-facts via the agent on win2)
`win` was never booted (it must stay untouched), so its column is its domain XML from before the work, which is what QEMU gives the guest;
`win2y`, which had `win`'s MAC but nothing else of `win`'s identity, confirmed that the guest reports what the XML says.

| Item | `win` (domain XML) | `win2` (inside the guest) |
|---|---|---|
| SMBIOS system and chassis serial (`bios.serial`) | AGGI4Q1 | TFJJ71C |
| Baseboard serial | /AGGI4Q1/CN4I3G1JW6OB6V/ | /TFJJ71C/CNFA6YCCTN6FHQ/ |
| SMBIOS UUID | 03f22cad-8664-4dc2-ba2f-a93e3ba26471 | C03BF709-868E-40A6-AC74-762DA11E687A |
| Disk serial (Win32_DiskDrive and Get-PhysicalDisk) | S4EWNX0X67M3L | S4EWNX0SQBYK3 |
| MAC | 00:14:22:c8:97:00 | 00:14:22:78:7B:25 |
| Computer name | DESKTOP-7A3K2P9 (as built) | DESKTOP-7A3K2P9 at first boot, LAPTOP-4Q8R2MZ after reconfigure |
| IPv4 | 192.168.150.10 | 192.168.150.11 static |

Everything else in `guest-facts.ps1` is identical between the pre-reconfigure and final runs except `nic.ipv4` and `os.hostname`
(diff in scratchpad), and the model strings, CPU, hypervisor bit False, Secure Boot, TPM, OS build 26200.8037, Defender (enabled, real-time on, tamper protected True), firewall off, UAC 0, Python 3.11.9 32-bit and Pillow 10.4.0 are as in M0b.

**What does NOT differ, because it lives in the disk (not measured on `win`, equal by construction):**
`MachineGuid 712bbf6c-505e-41cc-a415-1af601ea1889`, the machine SID `S-1-5-21-1241114940-491779823-959845992`, `Analyst`
SID `...-1000`, SQM `MachineId {D581B593-...}`, `HwProfileGuid {0897474a-...}`, InstallDate, ProductId `00330-80000-00000-AA819`,
the C: volume GUID, the network profile name, the adapter GUID, `C:\tartarus`, the account `Analyst`, and the event log, which
still holds the source's history (the old name `DESKTOP-7A3K2P9`, the build-time name `ANALYST-NE4F5KN`, the 41/6008 pair, the TPM-cleared event, and the source's snapshot moment in the 6008 text). I did not try to change
MachineGuid or the SID.

### Computer name and IP: persistence
Both survived two reboots (the one in the reconfigure script and the ACPI shutdown/boot) and a snapshot revert.
`hostname`, `$env:COMPUTERNAME`, `Win32_ComputerSystem.Name`, the registry (`ActiveComputerName`, `ComputerName`, Tcpip `Hostname`, `NV Hostname`)
and NetBIOS (`nbtstat -n`: `LAPTOP-4Q8R2MZ <00>` and `<20>`) all show the chosen name after the reboot. The DHCP view I could not check for the new name: the lease on `.10` carried the old name
(`DESKTOP-7A3K2P9`) and the clone with a static address does not use DHCP any more.

`Rename-Computer` needed only: an elevated session (the agent's task runs the guest user with the highest privileges, and it worked from the 64-bit PowerShell
launched by the agent), `-NewName`, `-Force` to skip the confirmation; a workgroup machine needs no credentials. It takes effect only after a reboot (the script rebooted straight away, so I did not look at the name in between; after the reboot all views agreed). I only ran it from the 64-bit PowerShell; I did not run it or `New-NetIPAddress` from the agent's default 32-bit PowerShell.

## Workarounds and quirks (every step that was not straight-line)
1. **The agent's PowerShell is 32-bit** (the agent is 32-bit Python 3.11; `Is64BitProcess=False`). Under WOW64, `manage-bde` and `query` are "not recognized" and registry reads of `HKLM\SOFTWARE` are redirected. Used `C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe` for everything after the first query. `guest-facts.ps1` as written runs fine in 32-bit (it is what `verify-guest.sh` does).
2. **Changing the IP kills the HTTP call**, so the reconfigure script is started with `async=1` and logs to `C:\Windows\Temp\reconfig.log`, fetched afterwards via `/retrieve`.
3. The base disk has no stable name (see above): resolve it from the backing chain.
4. `time` is not available in the container's `sh` (first attempt failed harmlessly before anything ran); `virsh screenshot` already produces PNG (no conversion needed).
5. Nothing needed a human, a key press or a screenshot-driven decision.

## HANDOFF for S0b

- Domain `win2` (libvirt, defined, **shut off**), UUID `c03bf709-868e-40a6-ac74-762da11e687a`, MAC `00:14:22:78:7b:25`, network `tt-guest`, SMBIOS serial `TFJJ71C`, board `/TFJJ71C/CNFA6YCCTN6FHQ/`, disk serial `S4EWNX0SQBYK3`.
- Static IP **192.168.150.11/24**, gateway and DNS `.1`, DHCP off on the adapter. Computer name `LAPTOP-4Q8R2MZ`. User `Analyst` / `Tartarus1!` with autologon. The agent starts at logon: `http://192.168.150.11:8000` from inside the cape container.
- Snapshot `tartarus-clean` (external disk and memory, taken 13:40:08 guest time, `state running`). Files in `/var/lib/libvirt/images`: `win2.qcow2` (base, now a backing file, never write it), `win2-clean.mem`, and the current overlay `win2.1792071621` (28 MB; it replaced the snapshot's `win2-clean.qcow2` when I tested a revert, exactly as `win` has `win.1792021253`). Nvram `/var/lib/libvirt/nvram/win2_VARS.fd`; swtpm state `/var/lib/libvirt/swtpm/c03bf709-.../tpm2`.
- Revert works: `virsh snapshot-revert win2 tartarus-clean`, 1 s, agent at `.11` immediately (no CAPE involved).
- **Not registered with CAPE**, `kvm.conf.d` untouched (`win.conf` only), CAPE and its container not restarted by me (the container was already about 1 minute old when I began; `supervisorctl status cape` showed an uptime of 15 minutes at the end).
- Nothing is running: both `win` and `win2` are shut off, the throwaway domains `win2x` and `win2y` and their disks, nvram and TPM state are deleted. `win` is untouched: `virsh dumpxml win` and `snapshot-list win` are byte-identical before and after, and the sha256 of `win.qcow2` (`29d04a0b...`), `win-clean.mem` (`104888b9...`), the live overlay `win.1792021253` (`f468fa5d...`), `win_VARS.fd` (`39e3de79...`) and its `tpm2-00.permall` (`1d775fbb...`) match, sizes unchanged. (`win-clean.qcow2` does not exist on disk, see above.)
- Traces I left inside win2's disk (they are in the snapshot): `C:\Windows\Temp\q*.ps1`, `reconfig.ps1`, `reconfig.log`, `guest-facts.ps1`, plus the event log of this session. Not a pristine artifact, fine for a registration and analysis test.
- Both guests share the DHCP range quirk below: only `.10` is offered by libvirt's DHCP.
- Helper scripts in the scratchpad: `gps.sh` (32-bit run), `g64.sh` (Sysnative run), `reconfig.ps1`, `shot.sh`.

## Things that must change in decision 15 or 16

1. **"Reconfigure boots the copy at the source's old address"** is not what happens for `win`: it boots on **DHCP** and gets `.10` only because libvirt's DHCP range is the single address `.10`. For a clone whose source has a static address on its base disk (tested with `win2`, `.11`) it boots at that address. Reconfigure must therefore not assume the static address: wait for the agent on the address the source's `guest.json` says **and** on `.10`, or read it from the lease, and it must always set the static address explicitly (it does). Consequences to settle: (a) the exclusion rule of decision 7 has to be about **the address the clone boots at**, not "the source": a clone of `win2` boots at `.11`, a clone of `win` at `.10`, and a clone made while another guest is running an analysis at that address would clash; (b) DHCP gives `.10` to only one MAC for 10 minutes (`dhcp-lease-max=1`), so two `win`-based clones in quick succession could be refused an address until the lease expires (not tested, only inferred from `start-guest-network`'s own comment and the single-address range); (c) the claim in the spec's networking row that the Windows guest "uses a static IP" is not true of `win`'s base disk as far as this experiment shows, and the risk it names (the rooter DNATing DHCP renewals during an analysis) was not examined here; flag it to S0b/C-wave.
2. **Find the adapter as `provision.ps1` already does**: confirmed enough. Windows keeps name, GUID and index when only the MAC changes; the "find it by hardware" fallback in decision 15 is not needed for this case.
3. **Run reconfigure with the 64-bit PowerShell** (`C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe`) and `async=1` for the step that changes the IP. The step must read its own log with `/retrieve` afterwards. The same applies to `guest-facts.ps1` extensions in decision 16 (a scan of services, scheduled tasks and firewall rules works in 32-bit PowerShell, but anything using `manage-bde`, `query` or the 64-bit registry view does not).
4. **Find the base disk from the backing file of the current overlay**, not as `<name>.qcow2`/`<name>-clean.qcow2` (the latter does not exist after a revert).
5. **Decision 15 says "nothing of the source's hardware identity survives"**: true for hardware; not for the software identity. `MachineGuid`, the machine SID, the SQM id, InstallDate, ProductId, volume GUID, the old computer name and the "unexpected shutdown / TPM cleared" events in the event log all carry over, so a clone and its source (and every clone of the same source) share them. If that matters for decision 16's "nothing says Tartarus / nothing links the guests", reconfigure needs more steps (at least `MachineGuid`; the SID would need sysprep-like tooling), which were not tested here.
6. **TPM handling is right**: a fresh swtpm per new UUID is created by libvirt on `define`+`start` (no extra step), and Windows handles it itself (SRK changed, TPM cleared and reprovisioned automatically, no prompt). No TPM-sealed secret exists in the image (BitLocker has no protector), so a new TPM cannot lock the clone out. Do not copy the swtpm state. **nvram handling is right**: copying `win_VARS.fd` kept Secure Boot on and the boot entry valid with no message.
7. **BitLocker conversion** is in progress and unprotected in the source image; each clone resumes it and spends disk writes on it (+543 MB in this run). Decision 5's disk numbers and the snapshot's content depend on the moment the source was snapshotted; worth a line, and possibly turning device encryption off at provisioning in the build (not tested).
8. D15 says Defender **on** from a source that has it off is scripted and "S0d checks that it takes": **not tested**, as instructed (it waits for S0c).

## Could not verify

- That `win` itself, cold-booted from its own disk, comes up on DHCP (I only booted copies; `win` was not started). The DHCP result is solid for copies of `win.qcow2` with the same and with a different MAC.
- Why the static address of `provision.ps1` is not in the base disk's effective configuration (I did not read the SYSTEM hive offline).
- The first 20 s of the boot screen (before the Welcome screen) and the exact time from `Restart-Computer` to the agent (upper bound 42 s).
- Whether `slmgr` "notification mode", the BitLocker conversion, the Edge captive-portal window and the 41/6008 events are the same on `win` (they are in its base disk, so presumably identical; not compared).
- The DHCP/NetBIOS name as seen from the DHCP server after the rename (the clone is static after the rename).
- `Rename-Computer` and `New-NetIPAddress` from the agent's 32-bit PowerShell; `MachineGuid` change; Defender on/off; an analysis (CAPE task) on the clone and on a registration (S0b); any run with `win` and `win2` powered on together.
- A real analysis behaving like the source's was not attempted (the plan's S0d row mentions it after registration; registration was out of scope here).
