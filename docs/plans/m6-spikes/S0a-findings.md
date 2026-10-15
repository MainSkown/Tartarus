# S0a findings: reading an installation ISO without extracting `install.wim`

Run 2026-10-15 in the running `tartarus-cape` container (Ubuntu 24.04, privileged, 7-Zip 23.01, host kernel
7.1.8-arch1-3, host disk NVMe/ext4). ISO: `data/iso/Win11_25H2_Polish_x64_v2.iso`, 8,345,856,000 bytes, UDF,
`sources/install.wim` is 7,437,390,947 bytes. Everything below was measured; what was not is under "Could not verify".
Nothing in the repo (Dockerfile, compose, backend, frontend, guest) was changed; `wimtools` was installed in the
running container only for the experiment and removed again; the stack is stopped.

## Recommendation

**Loop-mount the image read-only and run `wiminfo` on the mounted `install.wim` (or `install.esd`).**

| Approach | Time | Reads | Scratch | Verdict |
|---|---|---|---|---|
| loop mount (UDF) + `wiminfo` | **0.039 s** for wiminfo alone; **0.06 s cold / 0.04 s warm** for mount + wiminfo + umount (page cache dropped first) | 4.6 MiB at the loop device (5.9 MiB total counter) | none | **use this** |
| `wiminfo` on the same file, XML form (`--xml`) | 0.034 s | same | none | same data, machine-readable |
| 7-Zip alone, no mount (`7z l iso`, `7z e iso <small file> -so`) | 0.03 s to list 1064 files | negligible | none | gives arch (`idwbinfo.txt`) and UI language (`lang.ini`) only; **not editions, not the build number** |
| 7-Zip on the mounted WIM (`7z e install.wim '[1].xml'`) | 2.3 s | 81 MiB (it reads all ten images' metadata) | none | works, same 26,952-byte XML, but slower and needs the mount anyway |
| fallback: `7z e iso sources/install.wim` to scratch, then `wiminfo` | **6.4 s** extract (cold cache, NVMe, 1.1 GB/s) + 0.027 s wiminfo | 7.4 GB read and written | **7.0 GiB** | works, `wiminfo` output byte-identical (apart from the path) and the file is byte-identical to the mounted one; only for a host where the loop mount is unavailable |

So the 7 GB extraction is not needed, the cache the plan proposes by (name, size, mtime) buys essentially nothing
(a scan is 40 to 60 ms; ten ISOs would be about half a second), and the scan needs no progress bar. A cache is
still harmless (`stat` is about a microsecond) and would only matter on a slow disk (see "Could not verify");
decision 4 can drop "shown with progress" for the mount path.

`wiminfo` on `boot.wim` is **not** a substitute: it has no editions, and it reports **build 26100** while the
`install.wim` of this 25H2 ISO says **26200**. Never take the build from `boot.wim`.

## What the loop mount needed (this is the part that is not obvious)

1. **The package is `wimtools`, not `wimlib-tools`** (Ubuntu 24.04: `wimtools` 1.14.4, plus `libwim15t64` and
   `libfuse3-3`, about 2 MB installed; `apt-get install wimlib-tools` answers `Unable to locate package`). It also
   provides `wimcapture`, `wimlib-imagex`, `wiminfo`.
2. **No loop device node existed.** At container start `/dev` has only `/dev/loop-control`. The first
   `mount -o loop,ro -t udf ...` failed with `mount: ... failed to setup loop device for ...` (exit 32). After
   `mknod /dev/loop0 b 7 0` it worked. The container's `/dev` is a snapshot taken when the container is created;
   after `docker compose restart cape` it showed `loop0..loop2` (the host had created them meanwhile) but not the
   ones I had `mknod`ed, so **nodes must be created at run time**.
3. **The next free loop index is not always 0.** A second, different image failed with the same message while
   `loop0` was in use, because the kernel handed out `loop1` and there was no node for it. If the host itself uses
   loop devices (snaps, flatpak, AppImage) the free index can be well above 8, so a fixed `mknod loop0..loop7` in
   the entrypoint is not enough. The flow that worked in all cases (tested with `loop0..loop3` occupied, so the
   next free was `loop4` with no node):

   ```
   dev=$(losetup -f); [ -b "$dev" ] || mknod "$dev" b 7 "${dev#/dev/loop}"
   dev=$(losetup --find --show --read-only "$ISO")
   mount -o ro "$dev" "$MP"          # no -t: UDF is detected for the Microsoft ISO, iso9660 for a plain one
   ...
   umount "$MP"; losetup -d "$dev"
   ```

   (`mount -o loop,ro file dir` also auto-detects, and re-uses the loop device when the same file is already
   attached; the explicit `losetup` form gives deterministic cleanup.)
4. **The `udf` kernel module is the host's.** The container cannot load modules itself; the mount triggered the
   host's autoload (`lsmod` on the host showed `udf` 155 KB, used by `loop`/`cdrom`). I did not observe whether it
   was loaded before my first mount. On this Arch kernel it exists as `udf.ko.zst`; a host without it would make
   every UDF mount fail with `mount: unknown filesystem type 'udf'` (not reproduced, see below).
5. **Auto-detection is right on the real ISO.** `mount` without `-t` picks `udf` for the Microsoft ISO (the
   ISO9660 view would show only README); `findmnt` reported `udf`. With `-t iso9660` I did not try it.
6. **The `:ro` bind mount of `/data/iso` causes no problem.** `findmnt` shows `ro,noatime`; `losetup -r` / `mount -o ro`
   on a file there worked, and `7z` reads it fine. Nothing is written to the ISO or to `/data/iso`.
7. No capability beyond what `privileged: true` already grants was needed; no change to compose.

## Exact commands

```
# list (no mount, 0.03 s), if ever wanted for a file listing
7z l "$ISO"
# the scan
dev=$(losetup -f); [ -b "$dev" ] || mknod "$dev" b 7 "${dev#/dev/loop}"
dev=$(losetup --find --show --read-only "$ISO")
mount -o ro "$dev" "$MP"
wiminfo "$MP/sources/install.wim"            # or install.esd; text form, 0.039 s
wiminfo --xml "$MP/sources/install.wim"      # same data as XML (26,952 bytes), see below
umount "$MP"; losetup -d "$dev"
# fallback, 6.4 s, 7.0 GiB scratch
7z e "$ISO" sources/install.wim -o"$SCRATCH" -y && wiminfo "$SCRATCH/install.wim"
```

`wiminfo --xml` (and `--extract-xml FILE`, byte-identical) writes **UTF-16LE with a BOM**
(`ff fe 3c 00 57 00 ...`); decode with `.decode("utf-16")`. Its architecture is the numeric `<ARCH>` (9 = amd64;
the fixtures used 12 = ARM64); the text form prints `x86_64`, `ARM64`, and so on. Either parses with the standard
library; the text form is `Key: value` lines per `Index:` block with `Languages:` space-separated and a trailing
space, the XML form is stable and explicit. The XML also carries `<LANGUAGES><LANGUAGE>`, `<DEFAULT>`,
`<VERSION><BUILD>`, `<EDITIONID>`, `<NAME>`, `<INSTALLATIONTYPE>`. Windows 10 vs 11 is not a field: use the
build (`>= 22000` is Windows 11) or the name.

## Parsed result for the user's ISO

Image: version 68864, 10 images, LZX, `Part Number 1/1`, size 7,437,363,995 bytes. Common to every image:
Architecture `x86_64` (`<ARCH>9`), Languages `pl-PL`, Default Language `pl-PL`, Major.Minor `10.0`,
**Build 26200**, Service Pack Build 8037, Installation Type `Client`, Product Type `WinNT`, Product Suite
`Terminal Server`, System Root `WINDOWS`, branch `ge_release`. Also from `sources/idwbinfo.txt`: `BuildArch=amd64`,
`BuildType=fre`; from `sources/lang.ini`: `[Available UI Languages] pl-pl = 3`, fallback `en-us`. The volume label
(`xorriso`/`blkid`) is `CCCOMA_X64FRE_PL-PL_DV9`, which also says x64 and pl-PL (a hint only, do not parse it).

| Index | Name | Edition ID | Total bytes (uncompressed) |
|---|---|---|---|
| 1 | Windows 11 Home | Core | 23,615,813,816 |
| 2 | Windows 11 Home N | CoreN | 22,988,803,989 |
| 3 | Windows 11 Education | Education | 24,658,035,009 |
| 4 | Windows 11 Education N | EducationN | 24,011,726,064 |
| 5 | **Windows 11 Pro** | Professional | 24,661,507,674 |
| 6 | Windows 11 Pro N | ProfessionalN | 24,032,866,375 |
| 7 | Windows 11 Pro Education | ProfessionalEducation | 24,658,085,647 |
| 8 | Windows 11 Pro Education N | ProfessionalEducationN | 24,011,751,833 |
| 9 | Windows 11 Pro for Workstations | ProfessionalWorkstation | 24,658,136,285 |
| 10 | Windows 11 Pro N for Workstations | ProfessionalWorkstationN | 24,011,777,602 |

Index 5 (Pro) is what M0b hard-coded, so the scan agrees with the proven build. Raw `wiminfo` block for index 5:

```
Index:                  5
Name:                   Windows 11 Pro
Description:            Windows 11 Pro
Display Name:           Windows 11 Pro
Display Description:    Windows 11 Pro
Directory Count:        33200
File Count:             145217
Total Bytes:            24661507674
Hard Link Bytes:        10337269720
Creation Time:          Sat Mar 07 00:08:24 2026 UTC
Last Modification Time: Sat Mar 07 00:42:32 2026 UTC
Architecture:           x86_64
Product Name:           Microsoft® Windows® Operating System
Edition ID:             Professional
Installation Type:      Client
Product Type:           WinNT
Product Suite:          Terminal Server
Languages:              pl-PL 
Default Language:       pl-PL
System Root:            WINDOWS
Major Version:          10
Minor Version:          0
Build:                  26200
Service Pack Build:     8037
Service Pack Level:     0
Flags:                  Professional
WIMBoot compatible:     no
```

`Name`, `Description`, `Display Name` are the same string for all ten; `Flags` equals the Edition ID. One trap in
the XML: `<PKEYCONFIGVERSION>` says `10.0.26100.7019`; ignore it, `<VERSION><BUILD>` is the build.
The ISO also contains a root entry `__chunk_data` (Microsoft's ISO tooling), harmless.

## Edge cases (small fixtures I built; scan = auto-detect mount, then look for `sources/install.wim`, then `.esd`)

Fixtures were made in the container with `xorriso -as mkisofs` and `wimcapture ... --image-property
WINDOWS/EDITIONID=...` (and `WINDOWS/ARCH`, `WINDOWS/VERSION/BUILD`, `WINDOWS/LANGUAGES/LANGUAGE`, `[2]` for a
second language, `WINDOWS/LANGUAGES/DEFAULT`). `wimcapture` writes those properties into the XML, so the parser
can be tested with a fake image that has multiple languages and ARM64; the fixtures were deleted afterwards (the
two `wimcapture`/`xorriso` lines above regenerate them). They are ISO9660, so the UDF path was only tested on the
real ISO and on a truncated copy of it.

| Case | What happened (exact) | Map to |
|---|---|---|
| Real UDF Windows ISO | mount rc 0, fstype `udf`, `wiminfo` rc 0 | normal |
| Small ISO9660 + `sources/install.wim` (2 images, 2 languages `en-US de-DE`, one `x86_64`, one `ARM64`) | mount rc 0, fstype `iso9660`, `wiminfo` rc 0; `Languages:  en-US de-DE ` | normal; the parser must accept several languages and any architecture |
| `sources/install.esd` instead (a *solid* WIM that `wimcapture --solid` made, not a Microsoft ESD) | `wiminfo` rc 0, `Compression: LZMS`, same fields | same code path; just try `install.wim` then `install.esd`. A real ESD was **not** tested |
| Windows-shaped ISO with only `sources/boot.wim` | mount ok; no `install.wim`/`install.esd` | "This looks like Windows media but has no install.wim or install.esd" (the 7z/`ls` check, not an error code) |
| Non-Windows ISO (files + `boot/`) | mount ok; no `sources/` directory | "Not a Windows installation image" |
| `install.wim` of a non-Windows directory (no `WINDOWS` properties) | `wiminfo` rc 0, `Index/Name` only, **no `Edition ID`, `Build`, `Architecture` lines** | "image has no Windows metadata"; the parser must treat the missing keys as non-Windows, not crash |
| `install.wim` that is random bytes | `wiminfo` rc **43**: `Invalid magic characters in header` / `The file did not begin with the magic characters that identify a WIM file.` | "install.wim is not a valid Windows image" |
| `install.wim` cut short (100,000 of 204,864 bytes) | `wiminfo` rc **65**: `Error reading data from WIM file: Invalid argument` / `Unexpectedly reached the end of the file.` | "damaged or incomplete image" |
| ISO truncated (60 MB of the real UDF, 100 KB of the ISO9660 fixture) | mount **succeeds** (UDF anchor is near the start); `wiminfo` rc **50**: `Error reading header: Input/output error` / `Could not read data from a file.` | "image is incomplete or unreadable; is the file still being copied?" Also what a half-copied ISO in `data/iso` looks like; `7z` says `Unexpected end of archive` |
| Empty file (0 bytes) | `mount` rc 32: `can't read superblock on /dev/loopN` | "not an ISO image" |
| Text file named `.iso` | `mount` rc 32: `can't read superblock` | "not an ISO image" |
| 1 MB of random bytes | `mount` rc 32: `wrong fs type, bad option, bad superblock on /dev/loopN, missing codepage or helper program` | "not an ISO image" |
| Directory named `x.iso`, dangling symlink | `mount` rc 32: `failed to setup loop device` | check `os.path.isfile` and size > 0 before mounting; "not a readable file" |
| Any of the three non-ISOs with `blkid -p` / `7z l` | `blkid` rc 2, empty output; `7z`: `Cannot open the file as archive`, rc 2 | a cheap pre-check if wanted: `blkid -p` rc 0 means a recognised filesystem |
| `mount` when no free loop device node exists | rc 32 `failed to setup loop device` (identical to the dangling-symlink message) | an infrastructure error, not the user's fault: create the node first (above), and report "could not attach the image" distinctly from "not an ISO" |
| Host kernel without `udf` | **not reproduced** | see below |

The fallback `7z e iso sources/install.wim` behaves differently on errors: for an ISO that lacks the member it
printed `Files: 0` and exited **0** (so check that the output file exists); for the truncated UDF it printed
`Headers Error`, `Unexpected end of archive` and `ERROR: Data Error : sources/install.wim`; for a non-ISO
`Cannot open the file as archive`, rc 2.

The scan must distinguish by *step*, not by wiminfo's text: (1) not a file / empty, (2) mount fails, (3) no
`install.wim`/`.esd`, (4) `wiminfo` rc 43 or 65 or 50, (5) rc 0 but no Windows metadata. Use `wiminfo`'s exit codes
(43, 50, 65 seen) and keep stderr for the log, not the UI.

## Page cache and cache cost

A second read is not meaningfully faster: mount + wiminfo + umount took 0.06 s with the page cache dropped
(`echo 3 > /proc/sys/vm/drop_caches`, allowed in the privileged container, affects the whole host) and 0.039 to
0.040 s warm. Keying a result cache on `(name, size, mtime)` costs one `stat` (about 1 µs); the key for the user's
ISO is `Win11_25H2_Polish_x64_v2.iso 8345856000 1791852244`. Given 40 to 60 ms per ISO, a cache is not needed on
this hardware; it is a few lines, so keep it only if a slower disk is a concern. An ISO still being copied has a
changing size and mtime, so such a cache would not serve a stale result for it.

## Cleanup, restarts, concurrency

- **Always `umount` and `losetup -d`.** After `umount`, the loop device detaches asynchronously (it was gone within
  about a second; `losetup -a` immediately after `umount` once still listed it). With `mount -o loop` the device is
  auto-cleared; with `losetup --find --show` (explicit) it stays attached until `losetup -d`, which I used.
- **`umount` while a process has the directory open** fails: `umount: ...: target is busy` (rc 32); `umount -l`
  then succeeded and the loop device detached once the process ended. Run `wiminfo` with a timeout and `cd /`
  before unmounting.
- **Container restart mid-scan** (`docker compose restart cape` with an ISO mounted): 7.6 s; afterwards the mount
  was gone (the mount namespace dies with the container), the host's `losetup -a`, which listed the ISO before,
  was empty, and `/dev/loop*` came back as a snapshot. So a container restart cannot leak a mount or a loop device;
  the leftover is only empty mount-point directories in the container filesystem (I used `/run`, a tmpfs in
  compose, which is cleared by a restart).
- **A killed control service with the container still running** leaves the mount and the loop device behind (I
  simulated it by not unmounting). Cleanup at the start of the next scan worked:
  `findmnt -rno TARGET | grep '^/run/scan/' | sort -r | xargs -r -n1 umount`, then no mounts and no loop devices.
- **Concurrent scans of the same file** share one loop device (util-linux re-uses it); of different files each
  needs its own device and node (the creation-on-demand above). Scans are cheap, so serialise them with a lock.
- The loop device is a **host-global** resource (the container shares the host kernel's loop devices): nothing
  clashes because the kernel hands out a free index, but `losetup -a` on the host shows the container's
  attachments while they are alive.

## What has to change

- **`cape/Dockerfile`**: add `wimtools` to the apt install list that already holds `p7zip-full` and `xorriso`
  (line 88 to 89). Nothing else: `util-linux` (`mount`, `losetup`, `findmnt`), `p7zip-full` and `xorriso` are
  there; `bsdtar` and `isoinfo` are not installed and are not needed (`bsdtar` cannot read UDF anyway).
- **Compose**: no change. `cape` is already `privileged: true` and `/data/iso` is already mounted `:ro`.
- **Code (C3)**: the loop-device-node creation, `losetup --find --show --read-only`, auto-detect mount, `umount`,
  `losetup -d`, a lock, a `try/finally`, startup cleanup of `/run/scan/*`, and the error mapping above. All of this
  is shell-level plumbing around a pure `wiminfo` parser, which is the testable part. This replaces the spec text
  "extracting the 7 GB image once, to scratch space inside a throwaway container" in
  `docs/specs/cape-integration.md` (Inputs) and the S0a hedge in decision 4.
- If decision 17's "media inspector" interface (media file in, `[{profile, variant, version, language, arch}]`
  out) is used: for the Windows inspector `variant` is the index plus `Name` plus `Edition ID`, and `version` is
  the build (26200); it should also return the index (needed by the answer file) and the languages as a list.

## Could not verify

- A **real Microsoft `install.esd`**: only a `wimcapture --solid` file (LZMS) was available; encrypted ESDs from
  older Windows Update downloads were not tested.
- A **UDF image with an ISO9660-only README view other than the retail Windows ISO**, and any UDF ISO smaller than
  8 GB: no tool in the image makes UDF (`mkudffs`, `genisoimage` are absent), so the UDF path was tested on the
  real ISO and on a 60 MB truncation of it only.
- **A host kernel without the `udf` module** (the error text, whether the host autoloads it from inside the
  container when it is not loaded): not reproducible without unloading modules on the host, which I did not do. I
  also do not know whether `udf` was loaded before my first mount.
- **A slow disk (HDD, network share)** for the cold read: the host here is NVMe, so cold numbers (0.06 s scan, 6.4 s
  extraction) will be worse elsewhere; the page-cache drop affects the whole host.
- **Windows 10 and other-language ISOs**: only the one Polish Windows 11 25H2 ISO exists here.
- Behaviour when the **host loop devices are exhausted** (no free index at all) and when `/dev/loop-control` is
  missing.
- **A cache invalidation test** (touching the file): the key was only computed, no cache was implemented.
- `7z` reading a WIM *inside* the ISO without any extraction: 7-Zip's CLI has no nested-open mode (`-t#` is a
  signature scanner that listed boot-sector fragments); I did not stream `7z e -so` into a second `7z` because it
  would read all 7 GB, as the task said not to.
