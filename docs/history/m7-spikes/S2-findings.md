# S2 findings: the two anti-VM tells, empty optical drives and the display adapter

Spike on the real stack, 2026-10-17. Source guest `lab3` (Defender off, only ever read: cloned from), sample
`benign.exe` (the self-test sample), guest OS Windows 11 25H2, **pl-PL**. No file in the repo was changed except
this one. Experiments changed files only inside the running `cape` container (the domain template, once the
`snapshot` step), and both were put back from the repo afterwards (`diff` against `guest/domain/domain.xml.tpl`
and `guest/steps/snapshot` is empty). Every `s2-` guest and all 13 analyses the spike made (244 to 256) were
deleted through the API; `win`, `lab1`, `lab3` and `lab5` are `ready` and `apiv2/machines/list` lists the four
(all `poweroff`). Scratch scripts and raw outputs are in the session scratchpad (`.../scratchpad/s2/`), not in
the repo.

## Verdict

1. **The drives ship.** A run-mode domain without the two cdrom `<disk>`s (the `sata` controller kept) boots,
   the agent answers, `Win32_CDROMDrive` comes back empty, the external snapshot takes, CAPE's revert and a
   capemon analysis behave exactly as on an unmodified guest, the desktop draws, and a clone of the result works.
   One loose end that the template alone does not fix: Windows keeps **two non-present CD-ROM device nodes** (a
   ghost PnP entry and `Enum\SCSI\CdRom&...` registry keys) for the drives it saw before; a pre-snapshot step
   with `pnputil /remove-device` removes them and the removal survives snapshot and revert (measured).
2. **No display candidate meets the ship criterion; no display fragment ships.** The question was whether any
   emulated adapter makes Windows show something other than "Microsoft Basic Display Adapter". None does. Every
   candidate that boots and draws (`vga`, `bochs`, `virtio`, `qxl`) binds the same inbox Basic Display driver and
   reads the same name; `virtio` and `qxl` only change the PCI id to a more obvious one (`1AF4:1050` virtio,
   `1B36:0100` Red Hat QXL). The one candidate with a real vendor id (`ati-vga`, `1002:5046`) fails: Code 43
   and a black screen. The standard VGA cannot have its PCI ids set in this QEMU build at all. Plainly: **only
   the drives ship.**
3. **The facts check must not fail the self-test on `video.name`** while no fix exists: the clean baseline
   guest reads `Podstawowa karta graficzna Microsoft` (the Polish name of the Basic Display Adapter), so such a
   check would fail every guest ever built. Details and the exact strings are in "Recommendation".

## Method

- **Guests.** Each variant is a real clone of `lab3` made through the public API
  (`POST /api/guests/lab3/clone {"name": "s2-..."}`), so it goes through the whole pipeline: `preflight`,
  `copy`, `define`, `reconfigure`, `tamper-off`, `snapshot`, `register`, then the backend's self-test (a
  capemon analysis of `benign.exe` plus the guest facts). To change the hardware of a variant, the container's
  `/usr/local/lib/tartarus/domain/domain.xml.tpl` was swapped with `docker cp` before the clone started (the
  `snapshot` step redefines the domain from the same template, so the guest boots and is snapshotted on the
  variant hardware). The five-guest cap (`MAX_GUESTS` counts `building`, `testing` and `ready`) lets exactly **one**
  `s2-` guest exist next to `win`, `lab1`, `lab3` and `lab5`; "at most two" was not possible, and a clone of an
  `s2-` guest through the API is refused with a 409 (see "Clone of a drive-less guest").
- **Per guest.** `virsh snapshot-revert <guest> tartarus-clean --running` (what CAPE and the self-test do),
  wait for the agent, then a probe script run through the same `guest_agent.py` the steps use (it runs in the
  agent's 64-bit PowerShell; the user is `Alice`, elevated). The probe collected `Win32_VideoController`,
  `Win32_PnPSignedDriver` (display class), `Get-PnpDevice -Class Display/CDROM/DiskDrive/HDC`, `Win32_CDROMDrive`,
  `Win32_LogicalDisk DriveType=5`, `[IO.DriveInfo]`, `Win32_PnPEntity` for every `PCI\` device, `Enum\PCI` and
  `Enum\SCSI` registry keys, the DriverStore directory names and `pnputil /enum-drivers /class Display`. Also
  `virsh dumpxml`, `virsh domdisplay`, `info pci` through `qemu-monitor-command --hmp`, and `virsh screenshot`
  (the VNC framebuffer; checked non-black and looked at).
- **Capemon.** The self-test analysis of every clone (tag `self-test`, INetSim, 60 s) compared with the
  baseline's, using the S1 collector (`GET /analyses/{id}`, `/processes`, `/network`, `/registry`,
  `/detections`, `/artifacts`, `/pcap`, `events/search` and `events/facets`). Two ordinary analyses on the
  baseline and on the drive-less guest gave the spread between identical runs.
- **Desktop.** An interactive analysis (`timeout 120`) on each guest, then a Playwright script (outside the repo,
  `frontend/node_modules/playwright`) that opens `/analyses/{id}`, waits for the Guacamole canvas to light up
  (more than 100 000 pixels brighter than 60 of 765), clicks the Start button at the same guest coordinates
  `desktop-flow.spec.ts` uses (441, 775), and checks the canvas checksum changed. That is the real browser to
  `/ws/analyses/{id}/desktop` to `guacd` to VNC path; the repo's own `desktop-flow.spec.ts` was not run.
- **Baseline.** An unmodified clone of `lab3` (`s2-base`, the template as in the repo) measured the same things
  first, so every comparison below is between two clones made the same day from the same source.

## Drives (decision 6/7, part a)

### What changed

The two `<disk device='cdrom'>` blocks (units 1 and 2 on SATA controller 0) are removed from the run-mode
domain; the system disk (`sda`, controller 0, unit 0) and `<controller type='sata' index='0'/>` stay. The rendered
test template was the repo's `domain.xml.tpl` minus exactly these lines:

```xml
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${installer_source}
      <target dev='sdb' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='1'/>
    </disk>
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      ${extra_source}
      <target dev='sdc' bus='sata'/>
      <readonly/>
      <address type='drive' controller='0' bus='0' target='0' unit='2'/>
    </disk>
```

### What a sample reads

| | with the drives (`s2-base`, today) | without (`s2-nd`, `s2-nd2`, `s2-gc`) |
|---|---|---|
| `Win32_CDROMDrive` | 2 rows: `HL-DT-ST HL-PQ-SV WB8`, drive `D:` and `E:`, `MediaLoaded` false; `SCSI\CDROM&VEN_HL-DT-ST&PROD_HL-PQ-SV_WB8\4&35424867&0&010000` and `...020000` | **none**; `FACT cdrom.name=` (empty, read with the real `guest-facts.ps1` on `s2-gc`) |
| `Win32_LogicalDisk DriveType=5`, `Get-Volume` CD-ROM, `[IO.DriveInfo]` | `D:`, `E:` | none; only `C:\ Fixed` |
| `Get-PnpDevice -Class CDROM` | 2, `Present` true | **2 ghosts**, `Present` false, `Status` Unknown (kept from the source's disk) |
| `HKLM\SYSTEM\CurrentControlSet\Enum\SCSI` | `CdRom&Ven_HL-DT-ST&Prod_HL-PQ-SV_WB8`, `Disk&Ven_SAMSUNG&Prod_MZ76E120` | **the same two keys** (the CdRom key has 2 instances) |
| after `pnputil /remove-device` on the two ghosts, then a snapshot | | no CDROM devices, `Enum\SCSI` holds only the Disk key, `Services\cdrom\Enum` count 0 (measured on `s2-gc` after a real snapshot and revert) |

The ghost removal ran as the agent's own user (`Alice`, elevated): `Device removed successfully.` for both
instance ids. The sata AHCI controller stays (`Standardowy kontroler SATA AHCI`, `PCI\VEN_8086&DEV_2922`), so
nothing about the system disk changes.

### Does everything still work

| Check | Result (measured) |
|---|---|
| Boot, agent | The clone boots on the drive-less domain; `reconfigure` ran on it (hostname, static IP, new `MachineGuid`, reboot, verified) and so did `tamper-off` and `snapshot`. |
| Snapshot | `virsh snapshot-list s2-nd`: `tartarus-clean`, state `running` (external, as before). `dumpxml` of the clone: system disk `sda` on an overlay (`s2-nd.<epoch>`) over `s2-nd.qcow2`, `<controller type='sata' index='0'>`, no cdrom, `<video><model type='vga' vram='16384' heads='1' primary='yes'/>`. |
| Revert | `virsh snapshot-revert ... --running` returned in 2 s and the agent answered within the same second (baseline: 3 s and 3 s). Four more reverts on other variants: 1 s each. |
| Self-test | `all checks passed` on `s2-nd` (analysis 247): 2 processes, 2 file, 3 registry events, report, DNS answered. |
| Capemon vs baseline | See "Analyses" below: lane counts, process count, the 12 signatures, 13 detections, artifact names identical to the baseline's. |
| Desktop | Canvas lit after 2.0 s, 1 022 831 lit pixels (baseline: the same), a click on Start changed the frame. `virsh screenshot` mean brightness 0.980 (the Edge window is white; baseline 0.980). |

### Clone of a drive-less guest

- **A clone of an old guest (with drives) is re-rendered without them.** `s2-nd` is that: `lab3` has the drives,
  the clone path re-renders the domain from the template (`define`) and `snapshot` re-renders it again
  (`define_domain run`), so the clone has no drives and its own fresh snapshot. This is how decision 7 plays out
  for real.
- **A clone of a drive-less guest** could not go through the API: with `win`, `lab1`, `lab3`, `lab5` and `s2-nd`
  the cap of five is reached ("there are already 5 guests that are building, testing or ready"). The same steps
  were run by hand instead, with the repo's own scripts in the container against a context file and a private
  registry directory (`TT_GUEST_DIR=/tmp/s2-reg/s2-nd2`, so the live registry was never touched): `copy`
  (resolved `s2-nd.qcow2` as the base of the overlay, copied the nvram, found no cdrom in the source domain
  without complaint), `define`, `reconfigure` (verified hostname, IP and a new `MachineGuid`) and `snapshot`;
  then revert and probe. Result: the same facts as `s2-nd` (no `Win32_CDROMDrive`, the same 2 ghosts), revert in
  1 s, agent in the same second. Not done on that copy: `tamper-off`, `register` and a CAPE analysis (it was
  never registered). It was removed (`virsh undefine --nvram --tpm --snapshots-metadata`, images deleted).

### Do a build's install and provision steps still need the drives (read only, no build run)

Yes, and the change keeps them. `guest/profiles/windows/steps/install` calls
`render_domain install --media "$MEDIA_PATH" --extra-media "$ANSWER_ISO"` then `define_rendered install`: the
first drive holds the Windows media (`<boot dev='cdrom'/>` first) and the second the answer-file disc
(`autounattend.xml`, provisioning scripts, the agent), so a build **must** have both while it installs. `provision`
and `cleanup.ps1` only talk to the agent. `define` renders install mode only for `BUILD_KIND=build` with an
`installer` medium; a `disk_image` build and every clone render run mode. The domain is redefined in run mode
by the `snapshot` step (`define_domain run`), which is where the media leave. Consequence for a new build: Windows
has seen the two drives during install and provisioning, so the same two ghosts will be there after the snapshot
step's reboot (inferred from the clone case, **not run**; a build is 14 minutes).

## Display (decision 6/7, part b)

### Candidates and exact changes

All five were rendered on top of the drive-less template. Only the `<video>` element (and for `ati-vga` the
`<domain>` namespace and a trailing `<qemu:commandline>`) changed:

```xml
<!-- vga (today) -->        <video><model type='vga' vram='16384' heads='1'/></video>
<!-- bochs -->              <video><model type='bochs' vram='16384' heads='1'/></video>
<!-- virtio -->             <video><model type='virtio' heads='1'/></video>
<!-- qxl -->                <video><model type='qxl' ram='65536' vram='65536' vgamem='16384' heads='1' primary='yes'/></video>
<!-- ati-vga -->
<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>
  ...
  <video><model type='none'/></video>
  ...
  <qemu:commandline>
    <qemu:arg value='-device'/>
    <qemu:arg value='ati-vga,model=rage128p,bus=pcie.0,addr=0x10'/>
  </qemu:commandline>
</domain>
```

libvirt added `primary='yes'` and a PCI address itself. The `ati-vga` device needs `bus=pcie.0,addr=0x10`:
without it QEMU puts it in slot 1 and libvirt's first `pcie-root-port` fails on the same slot ("slot 1 function 0
not available for pcie-root-port, in use by ati-vga").

### What this QEMU can set (QEMU 9.2.2, the anti-VM build)

`qemu-system-x86_64 -device VGA,help` lists no `x-pci-vendor-id`, `x-pci-device-id`, `x-pci-sub-vendor-id` or
`x-pci-sub-device-id` (nor does `bochs-display`, `qxl-vga`, `virtio-vga`, `vmware-svga`, `cirrus-vga`). Only
`ati-vga` has an id property, `x-device-id` (default 20550 = `0x5046`), and its vendor is fixed to ATI
(`1002`). `cape/build/kvm-config.sh` only fills string placeholders of CAPE's `kvm-qemu.sh` (tablet, SCSI, ATAPI
and microdrive vendors, a block format name, the ACPI OEM id and table id): no PCI id of any display device. So
**a standard VGA with a real vendor's PCI ids cannot be made by a device property, a `<qemu:commandline>` or
`-global`**; it would need a patch to QEMU's `hw/display/vga-pci.c` in the image's `qemu-build` stage (rebuilding
the image was out of bounds, and a vendor id alone would not change the name, see below).

### What a sample reads, per candidate

Common to all (read on all five guests): `Win32_VideoController.Name = Podstawowa karta graficzna Microsoft`,
`AdapterCompatibility = (Standardowe typy ekranu)`, `DriverVersion = 10.0.26100.1`, `VideoProcessor` empty,
`AdapterRAM = 0`, `InfSection = MSBDA`, `Win32_PnPSignedDriver`: `DeviceName = Microsoft Basic Display Adapter`
(not localised), provider `Microsoft`, `display.inf`, `Win32_PnPEntity.Service = BasicDisplay`. The
`Win32_DesktopMonitor` is `Standardowy monitor inny niż PnP`. The DriverStore holds no vendor display driver
(`pnputil /enum-drivers /class Display`: "No published driver packages were found on the system"; of 714
FileRepository folders the display-related ones are `basicdisplay`, `display`, `displaymux`, `displayoverride`;
nothing of Intel, NVIDIA, AMD, QXL, virtio-gpu or VMware).

| Candidate | `PNPDeviceID` the sample reads | PCI ids (`info pci`) | Desktop (Guacamole) | Capemon analysis | Snapshot revert | Clone |
|---|---|---|---|---|---|---|
| `vga` (today, baseline `s2-base`, `s2-nd`) | `PCI\VEN_1234&DEV_1111&SUBSYS_11001AF4&REV_02` | `1234:1111`, class VGA controller, subsystem `1af4:1100` | draws, 1 022 831 lit px, click on Start changes the frame | 514 / 511 events, 2 processes, 12 signatures | 3 s and 2 s | `lab3` into it: yes (`s2-base`, `s2-nd`); a clone of it: yes, by hand (`s2-nd2`) |
| `bochs` (`bochs-display`) | **identical** to `vga`: `VEN_1234&DEV_1111&SUBSYS_11001AF4&REV_02` | `1234:1111`, class *Display controller* (the only difference, not shown by Windows' Name) | same | 518 events, same set | 1 s | `lab3` into it: yes |
| `virtio` (virtio-vga) | `PCI\VEN_1AF4&DEV_1050&SUBSYS_11001AF4&REV_01` (worse: it names virtio); the old `1234:1111` stays as a non-present ghost display device | `1af4:1050` | draws, same lit px, click changes frame | 516 events, same set | 1 s | `lab3` into it: yes |
| `qxl` | `PCI\VEN_1B36&DEV_0100&SUBSYS_11001AF4&REV_05` (worse: Red Hat QXL); old `1234:1111` ghost | `1b36:0100`; no QXL driver in the guest (Basic Display bound) | draws, same lit px, click changes frame | 512 events, same set | 1 s | `lab3` into it: yes |
| standard VGA with a real vendor's ids | **cannot be built** (no id properties in this QEMU) | | | | | |
| `ati-vga` (rage128p, `1002:5046`) | `PCI\VEN_1002&DEV_5046&SUBSYS_11001AF4&REV_00`, `Status = Error`, `ConfigManagerErrorCode = 43`; `CurrentHorizontalResolution` and `VideoModeDescription` empty | `1002:5046` | **black**: `virsh screenshot` 640x480, mean brightness 0.002 (a blank-disk OVMF boot shows 1280x800 for `vga` and 640x480 for `ati-vga`: OVMF has no video driver, hence no firmware framebuffer, for this device) | not run | the guest runs and the agent answers (192.168.150.117, on DHCP) | not run |

Notes on the table:

- The `ati-vga` row was measured by hand on a throwaway overlay (`qemu-img create -b s2-qx.qcow2`, backing file
  untouched) booted cold with the nvram copied, not through the pipeline, because it fails at the first
  criterion (the screen). The agent answered; the probe read Code 43 and no resolution.
- "Desktop" for the four that draw: the same Playwright script, the same screenshot, 1 022 831 lit pixels each.
  The black bars above and below the 1280x800 picture are the panel's letterboxing and are there on the
  baseline as well.
- Analyses are the self-test analyses of each clone, all compared with the baseline (below).
- The three clones that already ran the candidates' hardware through `reconfigure`, `tamper-off` and the
  `snapshot` step passed the backend self-test (`all checks passed`) each.

### Analyses (capemon, the break-list item)

Self-test analysis of each clone (benign.exe, INetSim, 60 s; "events" is `events_search_total`):

| Guest | analysis | events | processes | api / file / network / process / registry | signatures | detections | artifact names vs baseline | screenshots | pcap bytes |
|---|---|---|---|---|---|---|---|---|---|
| `s2-base` (drives, `vga`) | 244 | 514 | 2 | 466 / 2 / 28 / 15 / 3 | 12 | 13 | (reference) | 5 | 37 795 |
| `s2-base`, a second ordinary run | 245 | 511 | 2 | 466 / 2 / 25 / 15 / 3 | 12 (same set) | 13 (same) | same | 4 | 35 319 |
| `s2-nd` (no drives, `vga`) | 247 | 515 | 2 | 467 / 2 / 28 / 15 / 3 | 12 (same set) | 13 (same) | same | 4 | 39 344 |
| `s2-nd`, ordinary run | 248 | 514 | 2 | 466 / 2 / 28 / 15 / 3 | 12 (same set) | 13 (same) | same | 8 | 41 059 |
| `s2-bo` (`bochs`) | 250 | 518 | 2 | 469 / 2 / 29 / 15 / 3 | 12 (same set) | 13 (same) | same | 4 | 42 220 |
| `s2-vi` (`virtio`) | 252 | 516 | 2 | 467 / 2 / 29 / 15 / 3 | 12 (same set) | 13 (same) | same | 7 | 41 558 |
| `s2-qx` (`qxl`) | 254 | 512 | 2 | 467 / 2 / 25 / 15 / 3 | 12 (same set) | 13 (same) | same | 10 | 32 394 |
| `s2-gc` (no drives + ghost cleanup, `vga`) | 256 | 510 | 2 | 466 / 2 / 24 / 15 / 3 | 12 (same set) | not compared | not compared | not compared | not compared |

The spread between the two baseline runs (events 514 / 511, network lane 28 / 25) is as large as between any
candidate and the baseline. The interactive analyses (246, 249, 251, 253, 255) ended at arbitrary points when
`POST /finish` was called after the desktop probe, so their counts (359 to 731 events) show nothing about the
hardware and were not compared.

## What a driver would take (reasoning only, nothing downloaded)

To make Windows read a real GPU name (`Intel(R) UHD Graphics ...`, `NVIDIA GeForce ...`, `AMD Radeon ...`), a
vendor display driver has to bind to the device. Three things are in the way, in order:

1. **The id.** An `.inf` matches hardware ids (`PCI\VEN_8086&DEV_xxxx`). The device would have to carry that id,
   and this QEMU cannot give the standard VGA one (see above). The only emulated display with a real vendor
   is `ati-vga`, and Windows 11 ships no driver for it (none is in the DriverStore; I know of no WDDM driver for a Rage 128 Pro
   or RV100, from memory): measured, it falls to Basic Display with Code 43 and no output.
2. **The silicon.** Even with the right id patched into QEMU, an Intel, NVIDIA or AMD driver probes registers,
   GuC/HuC firmware, a video BIOS and power management that no QEMU device emulates. It fails with Code 43 at
   best and can bugcheck in `dxgkrnl` at worst; it would never give a working desktop. The same holds for
   `vmware-svga`, `qxl` and `virtio-gpu`: their drivers (VMware Tools' `vm3d`, Red Hat's `qxldod` and
   `viogpudo`) are not in the guest (checked: no published display driver), and from memory they name the product
   ("VMware SVGA 3D", "Red Hat QXL controller", "Red Hat VirtIO GPU DOD controller"), which would be a worse tell
   than Basic Display; that was not observed.
3. **Delivery.** The guest has no internet, so a driver would have to reach it through the build's `fetch` step:
   an entry in `guest/profiles/windows/manifest.sha256` (`<sha256>  <name>  <url>`, verified on the host, then
   copied into the answer ISO by `install`'s `stage_payload`) and a `pnputil /add-driver` in provisioning. The
   source would be a vendor download or a Microsoft Update Catalog `.cab`, pinned by hash; its licence for
   redistribution was not checked. None of this helps without 1 and 2.

The one path that gives a real name and works is passing a physical GPU through with `vfio-pci` (the device is in
`qemu-system-x86_64 -device help`). It needs IOMMU groups, takes the card from the host and cannot run
alongside another guest on the same card; it is a different feature and was not investigated.

A cosmetic rewrite was tried in one `s2-qx` session (reverted afterwards): setting `FriendlyName` under
`HKLM\SYSTEM\CurrentControlSet\Enum\PCI\<id>` succeeds as the elevated agent user and `Get-PnpDevice` then
returns the new name (`Intel(R) UHD Graphics 620`), but `Win32_VideoController.Name` did not change, and
`VideoProcessor`, `AdapterRAM` and `DriverVersion` are still empty or 0 or `10.0.26100.1`. I did not find the key
WMI reads for `Name` (no `0000` subkey under the display class key), so a name rewrite stays an open idea, not a
result.

## Recommendation

### 1. Run-mode domain: no optical drives

Ship the removal. For the template this is the two disk blocks above replaced by one placeholder filled only in
install mode; keep `<controller type='sata' index='0'/>`:

```xml
    <disk type='file' device='disk'> ... unchanged ... </disk>
    ${install_drives}
    <controller type='sata' index='0'/>
```

with `install_drives` a fragment (the two `<disk device='cdrom'>` blocks, `${installer_source}` and
`${extra_source}` filled from the paths) in install mode and an empty string in run mode (`_fill` already drops a
block line whose block is empty, as it does for `${boot}` on BIOS). Install mode, and so `install`, keeps both
drives. Tests that will change: `cape/tests/test_render_domain.py` (`test_run_mode_boots_the_disk_and_ejects_every_cdrom`
asserts no cdrom *source*; it should assert no cdrom disk at all, and install mode two), and the comment block at
the top of `domain.xml.tpl` ("The two optical drives are always present") which would then be wrong.
`scripts/tests/test_generic_steps.sh` only checks the boot device and media sources.

### 2. Ghost drives: a pre-snapshot step

Add `agent.pre_snapshot` to the Windows profile (the hook exists, is `null` today, and runs after the agent
answers and before the idle) with a step that removes every non-present CD-ROM node:

```powershell
foreach ($d in Get-PnpDevice -Class CDROM | Where-Object { -not $_.Present }) { pnputil /remove-device $d.InstanceId }
```

Verified with the real `snapshot` step on `s2-gc` (a clone of `lab3`, so with the ghosts in its disk): after the
snapshot and a revert there is no CDROM node and no `Enum\SCSI\CdRom` key. The check was done by patching the
container's generic `snapshot` step to run the script before the idle; **the profile hook itself was not run**
(profiles are read once at engine start, so a profile edit needs the service restarted, which the spike did not
do). The step belongs in the Windows profile, not in the generic `snapshot`.

### 3. Display: no fragment

Keep `<video><model type='vga' vram='16384' heads='1'/></video>` as it is. Do not add `hardware.display` to the
profile schema for this milestone. None of `bochs`, `virtio`, `qxl`, `ati-vga` is better than `vga`, and
`virtio` and `qxl` are worse (`VEN_1AF4`, `VEN_1B36` name the hypervisor in the `PNPDeviceID`).

### 4. What the facts check treats as a tell

- **`cdrom.name`: fail the self-test when it is not empty.** Observed today with drives: `HL-DT-ST HL-PQ-SV WB8;
  HL-DT-ST HL-PQ-SV WB8` (two names joined by `; ` by `guest-facts.ps1`); observed without: an empty value.
  The test of a clean fact set is `cdrom.name=`.
- **`video.name`: do not fail the verdict on the Basic Display Adapter.** It is what every guest reads, and
  the name is **localised**: `Podstawowa karta graficzna Microsoft` on the pl-PL guests, `Microsoft Basic Display
  Adapter` on an English one (the not-localised value is `Win32_PnPSignedDriver.DeviceName`, which printed
  `Microsoft Basic Display Adapter` even on this Polish system). Matching on the name alone would be
  language-dependent.
- To keep a regression visible, extend the facts script with a language-independent fact, the display adapter's
  `PNPDeviceID` (`Win32_VideoController.PNPDeviceID`) and fail only on the vendors that are worse than today:
  `PCI\VEN_1AF4` (virtio-vga), `PCI\VEN_1B36` (QXL), `PCI\VEN_15AD` (VMware), `PCI\VEN_80EE` (VirtualBox),
  `PCI\VEN_1013` (Cirrus) and any display device whose `ConfigManagerErrorCode` is not 0 (`ati-vga` gave 43).
  `PCI\VEN_1234&DEV_1111` (the QEMU standard VGA, what ships) and the Basic Display name are *known* tells:
  report them (`video.name`, `video.pnp`) without failing, so the Guests card can show them. The plan text in
  `m7-foundations.md` ("fails the self-test when either tell comes back") should say so; as written it would
  fail every new guest.

### 5. Guests built before the change

They keep their drives and their snapshot: `win` (adopted), `lab1`, `lab3` and `lab5` were not touched and are
`ready`. Their memory snapshot holds the hardware as it was; redefining their domain without the drives under it
was **not tried** (decision 7's reason is the standard libvirt/QEMU rule, not measured here), so do not.
A clone of any of them is rendered from the new template and retakes its own snapshot: that is `s2-nd`
(a clone of `lab3`), which has no drives, a fresh external snapshot and passed the self-test. It carries two ghost
CD-ROM nodes unless the pre-snapshot step of 2 runs (it does for a clone, since the clone also goes through
`snapshot`). The Guests page cannot tell "old hardware" from "new" until something records it: nothing does today
(the guest record has no hardware version), which is worth a line in the spec if the analyst should be told.

## Side observations (not in the questions)

- **Six of the eleven PCI devices carry the QEMU subsystem id `1af4:1100`** in their `PNPDeviceID`
  (`SUBSYS_11001AF4`): the host bridge `8086:29C0`, SATA `8086:2922`, USB xHCI `8086:000D`, LPC `8086:2918`, SMBus
  `8086:2930` and the VGA (six `Enum\PCI` keys on the baseline). The e1000e NIC and the root ports correctly use
  Intel's own (`SUBSYS_00008086`). A sample enumerating PCI sees Red Hat's subsystem id on most devices; no
  property to change it was looked for here.
- `win2`, a libvirt domain with its images (about 18 GB) that is not a guest the API knows, exists on the stack
  from before; the plan says to delete spare guests before spiking. It was left alone.
- Registering or deleting a guest restarts `cape` through supervisord (its uptime reset after each `s2-`
  delete, as designed); nothing else restarted.
- Each clone took about 8 to 9 minutes counted by polling the job (not timed to the second).

## Not verified

- **A real new build** (install mode with the drives, then run mode at the `snapshot` step): only the step
  code was read. That the build's ghosts appear and that the pre-snapshot step removes them is inferred from the
  clone case, not run.
- **That an existing memory snapshot cannot be restored after the drives are removed** (the premise of decision
  7) was not tested; no guest of the four was touched.
- **The literal `make verify-guest`** was not run: `scripts/verify-guest.sh` is built for the `win` guest at
  `.10`. Its checks were reproduced on the `s2-` guests (agent after revert, snapshot restore, capemon analysis,
  guest facts), not the script.
- The repo's **`desktop-flow.spec.ts`** was not run; a small Playwright script with the same click did the
  equivalent (canvas lit, Start click changes the frame). Keyboard capture and the end-of-run message were not
  tested on the candidates.
- **A CAPE analysis on a clone of a drive-less guest** (`s2-nd2` was never registered) and the API clone path for
  it (blocked by the cap of five).
- **Defender on:** every variant came from `lab3`, which is Defender off; `lab1` and `lab5` (Defender on) were not
  cloned. Nothing here depends on it, but it was not run.
- **The profile `pre_snapshot` hook** (see 2), and its time cost in the snapshot step.
- The `ati-vga` guest through the pipeline (clone, snapshot, revert, analysis): only booted cold on an overlay.
  `vmware-svga`, `cirrus-vga`, `ramfb` and a `vfio-pci` GPU were not tried.
- Whether a rewrite of the display adapter's registry values can change `Win32_VideoController.Name`
  (only `FriendlyName` was tried, and it does not).
- English or Windows 10 guests: only pl-PL Windows 11 was measured, so the English `Name` string is the
  documented one, not an observed one.
- Whether a sample sees the ghost CD-ROM keys or the `1af4:1100` subsystem ids as tells, and with what weight, is
  not known; the values read are exact, their effect on a given sample is a judgement.
