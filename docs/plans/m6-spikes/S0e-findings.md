# S0e findings: the Linux guest profile on paper

Spike S0e of [M6](../m6-guest-wizard.md). Question: is the guest-profile seam of decision 17 (a
`profile.json` schema, step files, a step contract with a generic pause, everything else generic)
expressive enough for a Linux guest analysed by CAPE, and what would break?

**Method.** Paper only. CAPE's source was read out of `tartarus-cape:latest` (`docker create` +
`docker cp`, never started, never executed) at the image's CAPE commit, which is the default of
`CAPE_REF` in `docker-compose.yml`: `9f806acd24ae23ee9a52cf4f1e82657635f07659`. Paths below are
`/opt/CAPEv2/...` inside that image. Nothing was run in a guest, the stack was not started by me, no
product file was touched. Anything inferred instead of read is listed in "Could not verify".

## 0. Verdict

**The seam is right in its shape (data + step files + a generic pause) and wrong in six places that
matter before C2.** A Linux profile is expressible *if* decision 17 is amended; as written it is
not, because it was drawn by generalising Windows' one-ISO, one-answer-file, one-pass-install flow.
The big ones, in order:

1. **There is no model for how a guest gets its software.** Windows builds from pinned, hash-verified
   files on a CD. A Linux guest needs `strace`, `sudo`, `python3` modules and (for screenshots, the
   desktop, document packages) a lot of distro packages, and the guest network is isolated. The
   generic `manifest.sha256` + `download_into_cache` step cannot express an apt closure.
2. **"Media" is not always an installer.** A cloud image is an installed disk: no install step, no
   installer ISO, the disk comes from copying the media. `pipeline`, the inspector contract and
   `define`/disk creation assume "blank disk + installer".
3. **`firmware` is one enum that conflates boot mode, Secure Boot, TPM, machine type, disk bus and
   NIC model**, and the domain is a `string.Template` with no conditionals. Generic steps must
   derive the disk target, nvram and TPM from the domain, not from the profile.
4. **`finish-run` and the Windows analyzer's "finish folder" are hard-coded** (`C:\Windows\Temp`,
   backslash join, fixed agent URL). The trick itself *does* apply to Linux (analyzer.py:335-344).
5. **`packages` cannot be a static list**: which CAPE packages work depends on what is installed in
   the guest, and four of CAPE's Linux packages are broken or unreachable at the pinned commit.
6. **Windows-shaped vocabulary leaks into the generic layer**: `edition`, `username` / `computer
   name`, "install CD", step names `install`/`provision` gating the desktop, `INTERACTIVE_OPTIONS`,
   the decision-16 substring gate (`cape` matches `landscape`, `escape`).

Separately, and not a seam problem: **CAPE says Linux is not officially supported**, the monitor is
`strace` text (not capemon BSON), the Linux analyzer ends when the sample exits, and no Linux
analysis has ever run in this repo (M0a registered a `platform = linux` Cirros guest only as a
probe, with no agent). Building a Linux profile is a research-grade project; the seam only needs to
not make it impossible.

## 1. What CAPE's Linux support requires (read from the pinned source)

### 1.1 Status: unsupported / community-grade, by CAPE's own words

| Statement | Where |
|---|---|
| `Linux guests don't have official CAPE support!` | `docs/book/src/installation/guest/linux.rst:5` |
| `.. This has not been tested recently:` | `linux.rst:8` |
| `# For advanced users only, can be buggy, linux analysis is work in progress for fun` / `enabled = no` | `conf/default/web.conf.default:100-101` (`[linux]`) |
| The submit path refuses ELF unless that is on: `"Linux binaries analysis isn't enabled"` | `lib/cuckoo/common/web_utils.py:990-991` |
| Tracee (eBPF) and Sysmon-for-Linux are "community feature", off, and need Docker / a Microsoft package in the guest | `linux.rst:103-117`; `conf/default/auxiliary.conf.default:19,27` (`sysmon_linux = no`, `tracee_linux = no`) |

Tartarus' `cape/conf/web.conf` today only sets `[guacamole]`, so `[linux] enabled = no` holds: **a
Linux submission through the API is refused until the profile (or the image) turns it on.**

### 1.2 What the guest needs

| Need | Evidence |
|---|---|
| Native 64-bit `python3` ("32-bit Python on a 64-bit system is not required and is highly discouraged"; it "will swap out the native 64-bit system Python ... breaks the operating system"). Agent refuses < 3.6; docs prefer 3.10 < v < 3.13. | `linux.rst:37-41,57-63`; `agent/agent.py:38-39`; `requirements.rst:13-21` ("For other platforms the version of Python can be 64-bit (x64)") |
| Agent is stdlib-only (`re2` optional). Listens on `0.0.0.0:8000` by default. | `agent.py:5-31,33-36,829-838` |
| **Root.** "It is a **MUST** to launch agent.py/w with elevated privileges." The agent reports `is_user_admin = os.getuid() == 0` on `GET /` but does not enforce it. | `docs/.../guest/agent.rst:17`; `agent.py:344-352,375-378` |
| **`sudo` and `strace`.** The "monitor" is literally `sudo strace -o /dev/stderr -s 800 {strace_args} -ttf {target}`, started with a bare environment `{"XAUTHORITY": "/root/.Xauthority", "DISPLAY": ":0"}` and `shell=True`. The docs still say `systemtap-runtime` (stale: no code path uses it; `host/platform/linux.py` has a systemtap parser, but the analyzer emits strace). | `analyzer/linux/lib/core/packages.py:244-250`; `linux.rst:54,62` |
| Optional pip packages `pyinotify Pillow pyscreenshot pyautogui` (docs add `--break-system-packages`, PEP 668). `dbus_next` ships inside `analyzer/linux/dbus_next`. | `linux.rst:47,55,63`; `modules/auxiliary/filecollector.py:12-18`, `human.py:11-17`, `lib/api/screenshot.py:13-40` |
| **Screenshots need a GNOME Shell on D-Bus** (`org.gnome.Shell`, impersonating `gnome-screenshot`) or an xdg-desktop-portal; otherwise "screenshots are disabled". `screenshots_linux = yes` by default. | `lib/api/screenshot.py:113-125,226-234`; `auxiliary.conf.default:16`; `modules/auxiliary/screenshots.py:51-57` |
| **`nohuman=yes` (which Tartarus passes for interactive runs) wraps the sample in `xterm -hold -e`**, so it needs `xterm` and an X display `:0` whose cookie is `/root/.Xauthority` (an X11 session; a stock Ubuntu Wayland session has no such file). | `lib/core/packages.py:246-247`; `backend/app/cape/client.py:25` `INTERACTIVE_OPTIONS = "interactive=1,nohuman=yes"` |
| Static IP ("CAPE doesn't support DHCP"), firewall off, NTP off (the analyzer sets the clock with `date -s`), auto-update off, `snapd` masked; optional purge of update-manager, whoopsie, cups, avahi. | `network.rst:52`; `linux.rst:70-95`; `analyzer.py:163-167` |
| Runtimes the packages call by absolute path: `/usr/bin/{python3,perl,node,java,pwsh,libreoffice,xpdf,firefox,xdg-open,dpkg,7z,file,bash,sh}`. | `modules/packages/*.py`; `lib/common/abstracts.py:132-157`; `modules/packages/archive.py:31-43` |

### 1.3 How the agent runs and is started

- **Start:** CAPE documents `sudo crontab -e` + `@reboot python3 /path/to/agent.py` (`linux.rst:65-68`).
  Anything that starts it as root at boot works; a systemd unit is the natural fit. No Linux-specific
  agent code exists: the same `agent.py` as Windows (`sys.platform == "win32"` branches only add
  mutex/browser-extension features and an `icacls` call, `agent.py:60-72,579-580`).
- **Wait for it:** the host does `socket.create_connection((ip, 8000), 1)` until it connects
  (`lib/cuckoo/core/guest.py:171-181`), then `GET /` and reads `version` and `features`
  (`guest.py:316-319` region). The agent answers `{"message": "CAPE Agent!", ...}` and sends the HTTP
  header `Server: CAPE Agent` (`agent.py:114,378`): a guest-visible string (decision 16 allow-list).
- **Per task** (`guest.py:208-216,319-382`): `GET /pinning` (pin to the host IP) -> `GET /environ` ->
  `POST /mkdtemp` with `dirpath="/"` (so the analyzer lives in a random folder **at the filesystem
  root** on Linux, `determine_system_drive()` returns `"/"`) -> `POST /extract` the analyzer zip ->
  `POST /store` `analysis.conf` and the sample to `/tmp/<task id>/<name>` (`determine_temp_path()`
  returns `"/tmp"`) -> `POST /execpy` async -> poll `GET /status`. The analyzer finishes by
  `POST http://127.0.0.1:8000/status complete` (`analyzer.py:480-491`).
- **Agent API for our own steps:** `/store`, `/retrieve`, `/execute`, `/mkdir`, `/remove`, `/extract`,
  `/environ`, `/system` (returns `platform.system()` = `Linux`), `/status` (`agent.py:449-657`). On
  Linux `/execute` uses `shlex.split`, so POSIX quoting works (the Windows `C:/` workaround is not
  needed). `shell=` with a list is broken on POSIX (`Popen(list, shell=True)` runs only the first
  element), so a reconfigure step should `/store` a script and `/execute` it, never use `shell`.
  `/execute` refuses calls from localhost except `date` (`agent.py:664-670`); calls from the host
  address are allowed.

### 1.4 Machine registration

`conf/default/kvm.conf.default:22-80` and `lib/cuckoo/common/abstracts.py:150-215`:

| Key | Linux value / rule |
|---|---|
| `platform` | `linux` (also `windows`, `darwin`) |
| `arch` | `x64` or `x86`. `filter_machines_by_arch` is `Machine.arch IN task_archs`, and an `x86` task also matches `x64` machines (`lib/cuckoo/core/data/machines.py:238-248`). |
| `tags` | The `kvm.conf.default:38-41` note ("One of winxp, win7, win10, win11 MUST be included for Windows VMs") is Windows-only. A task's non-arch tags must all be on the machine (`machines.py:262-273`). The stricter `_machine_can_service_task` in `abstracts.py:282-322` (which wants the arch tag on Linux machines) has **no callers** at this commit, so the arch tag is not needed. |
| `snapshot`, `interface`, `ip`, `label`, `resultserver_ip/port`, `reserved` | as for Windows |
| `[kvm] dsn`, `machines` | unchanged; one `kvm.conf.d` registration lists all machines |

M0a already proved CAPE accepts such a registration and reverts a snapshot for it
(`scripts/verify-cape.sh:94-133`: Cirros, `platform = linux`, `arch = x64`, BIOS `pc` machine, IDE
disk, virtio NIC). It never ran an agent or an analysis.

**Platform gate at submit time** (this is the part most likely to surprise a "Submit dialog lists
every ready guest" design): `web.conf [general] dynamic_platform_determination = yes` is the default
(`web.conf.default:66-67`), and then `download_file` sets `platform` from the *sample*:
`File.get_platform()` returns `linux` only for file types containing `Bourne-Again`, `POSIX shell
script` or `ELF`, `darwin` for `Mach-O`, and **`windows` for everything else**
(`lib/cuckoo/common/objects.py:170-171,873-883`; `web_utils.py:975-989`). With `machine=<label>` it then
refuses a mismatch: `"Wrong platform, {machine.platform} VM selected for {platform} sample"`
(`web_utils.py:1003-1004`). So a Python, Perl, `.deb` or `.jar` sample sent to a Linux guest is
classified `windows` and refused, unless `dynamic_platform_determination = no` (a global switch that
also changes Windows behaviour) or the request carries the right `platform`. Not tested here.

### 1.5 Analysis packages for Linux (`analyzer/linux/modules/packages/`)

`choose_package_class` imports `modules.packages.<name>` and takes the class whose name equals
`name.capitalize()` (`lib/core/packages.py:21-56`); with no `package` it guesses from the file type
(`packages.py:59-99`), falling back to `generic`.

| Name | Class / what it runs | State at the pinned commit |
|---|---|---|
| `generic` | `Generic` -> `sh -c <file>` (chmod +x first) | works for ELF |
| `bash` | `Bash` -> `/bin/bash <file>` | works |
| `python`, `python_whl`, `perl`, `js`, `jar`, `deb` | python3 / `python3 -m pip install` / perl / `/usr/bin/node` / `/usr/bin/java -jar` (or `-cp`) / `dpkg -i` | need that runtime in the guest |
| `doc`, `pdf`, `ff`, `xdg_open` | `libreoffice --writer`, `xpdf`, `firefox`, `xdg-open` | need that app and a display |
| `archive` | `Archive(lib.common.abstracts.Package)`, 7z extract + run interesting files | needs `7z`/`7zz`, `file` (`archive.py:31-43,59-66`) |
| `zip`, `wget` | both call a local `_fileinfo()` that does `raw[raw.index(":") + 2:]` on **bytes** with a `str` (`zip.py:127-131`, `wget.py:15-19`) | **TypeError by inspection** (`b'a: b'.index(':')` raises); `zip` also reached by `.tgz`/`.gz` guessing |
| `ps1` | file defines `class Pwsh`, but the loader wants `Ps1` (`ps1.py`, `packages.py:50-56`) | **unreachable by name**; `.ps1` guessing selects `ps1` and fails with "Could not find an appropriate analysis package" (`analyzer.py:248-249`) |
| URL analysis | `analyzer.py:236-237` suggests `url` for any non-file category; **there is no `url` package** | unsupported |

`PackageName` in Tartarus is a free `[A-Za-z0-9_]{1,64}` string, so the backend would forward any of these.

### 1.6 What the monitor outputs, and where it lands

- The analyzer streams strace's **stderr text** over the ResultServer `FILE` protocol to the name
  `logs/strace.log` (`lib/core/packages.py:191,209-217`; `lib/common/results.py:139-160`). It is a plain
  text file: lines like `<pid> HH:MM:SS.ffffff syscall(args) = ret`, with `<unfinished ...>` /
  `<... resumed>` pairs (`modules/processing/strace.py:331-345`). **No BSON, no per-pid `logs/<pid>.bson`.**
  It lands in `storage/analyses/<id>/logs/strace.log` (`core/resultserver.py:84` lists `logs`).
- Other uploads use the same whitelist as Windows: `files/`, `shots/`, `memory/`, `tlsdump/`, `sysmon/`,
  `tracee/` (`resultserver.py:64-84`), plus `analysis.log` through the `LOG` protocol (`results.py:163-171`).
  The Linux analyzer also dumps process memory of each new child to `memory/<pid>.dmp`
  (`analyzer.py:97-135`) and uploads the TLS key log `/sslkeylog.log` as `tlsdump/tlsdump.log`.
- CAPE parses it with `modules/processing/strace.py` (key `behavior`, `os = "linux"`), reading
  `logs/strace.log` and the data file `/opt/CAPEv2/data/linux/linux-syscalls.json` (`strace.py:220,503`).
  **It is disabled by default** (`conf/default/processing.conf.default:65-70`: `[strace] enabled = no`,
  `platform = linux`; the loader skips a module whose `platform` does not match the task's,
  `lib/cuckoo/core/plugins.py:303-308`). Tartarus' `cape/conf/` has no `processing.conf`, so it would
  need `[strace] enabled = yes`.
- The Tartarus live collector tails `logs/*.bson` (`backend/app/live/collector.py:24`
  `LOG_SUFFIX = ".bson"`); a Linux run produces none, so a Linux run is "report only" until a Linux
  collector and normaliser exist, exactly the "outside the seam" case of decision 17.

### 1.7 How the analyzer ends, and whether `finish-run` applies

**Yes, the trick applies, with a different directory.** `analyzer/linux/analyzer.py:335-344`:

```python
complete_folder = hashlib.md5(f"cape-{self.config.id}".encode()).hexdigest()
complete_analysis_pattern = os.path.join(os.environ.get("TMP", "/tmp"), complete_folder)
...
    if os.path.isdir(complete_analysis_pattern):
        log.info("Analysis termination requested by user")
        break
```

So `POST /mkdir dirpath=/tmp/<md5("cape-<task id>")>` ends a Linux analysis within a second or so (the
loop sleeps 1 s, `analyzer.py:392`), provided `TMP` is unset or `/tmp` in the agent's environment (the
analyzer inherits the agent's environment through `/execpy`, `agent.py:737-770`). The Windows analyzer
checks `%TMP%` and `%SystemRoot%\Temp`. What is *not* generic in `cape/bin/finish-run`:
`GUEST_TEMP_DIRECTORY = "C:\\Windows\\Temp"` joined with `"\\"`, the docstring, `DEFAULT_AGENT_URL`
(`.10:8000`).

Other ways a Linux analysis ends, which differ from Windows and matter for "interactive":

| Condition | Effect |
|---|---|
| The strace'd process exits and `PROCESS_LIST` is empty | `"Process list is empty, terminating analysis"` (`analyzer.py:365-367`). **A Linux analysis stops when the sample does**, unless `enforce_timeout` is set (`analyzer.py:330-332`), which the API accepts (`web_utils.py:1750`). |
| `timeout` seconds elapsed | `analyzer.py:339-341` |
| Package `check()` returns False | `analyzer.py:379-381` |
| No PID from the package | `ValueError("No PID available to monitor.")` (`analyzer.py:319-322`) |

The Linux analyzer never reads `interactive`; its equivalent is `enforce_timeout`. `backend/app/cape/client.py:25`
hard-codes `interactive=1,nohuman=yes`.

### 1.8 ResultServer and network

Same as Windows: the guest connects out to `ip:port` from `analysis.conf` (`results.py:67-82`), the
host side is `192.168.150.1:2042`, tcpdump on `tt-guest`, rooter/INetSim routing by guest IP. Nothing
Linux-specific in `analysis_manager.py` (`grep platform` finds only the `GuestManager` constructor,
`analysis_manager.py:432`). Static IP is mandatory (`network.rst:52`). Package installation inside the
guest at build time needs a reachable package source, which the isolated `tt-guest` network does not
provide (see section 4, point A).

### 1.9 Other Linux-visible facts that a profile has to live with

- **The sample runs as root**, as a child of `sudo strace ... -ttf <cmd>` under `sh -c`, with an
  environment of exactly `DISPLAY` and `XAUTHORITY` (no `HOME`, `PATH`, `USER`): `TracerPid` in
  `/proc/self/status`, `ptrace(PTRACE_TRACEME)` failing, the parent chain and the empty environment
  are tells no profile can remove. Mention on the card next to the existing "removes the cheap checks".
- The analyzer is extracted to `/<random>` at the filesystem root for each task and the sample to
  `/tmp/<id>/`; the `FileCollector` auxiliary puts inotify watches on every top-level directory except
  `proc sys usr dev var lib lib64 run` (`filecollector.py:76-97`). CAPE's own traces, not ours.
- `human_linux = no` by default; `human.py` needs `pyautogui` + `Xlib`.
- The CAPE agent file contains `CAPE` (server string, response message): decision 16's "allow-list of
  files the CAPE agent itself needs" applies; a build-time patch of those two strings (like the
  Dockerfile's `cape/patches/`) would close it for both OSes. Optional.

## 2. The Linux profile, filled in

The first Linux profile is **Ubuntu Server 24.04 via autoinstall** (cloud-init NoCloud seed). The same
directory layout serves a Debian profile later (section 5, change 9). The draft uses decision 17's
field list; fields marked `NEW`/`CHANGED` are my proposed amendments (section 5).

```jsonc
{
  "schema_version": 1,                                   // NEW: the plan says "versioned"; make it a field
  "id": "ubuntu",
  "display_name": "Ubuntu (autoinstall)",
  "family": "linux",                                     // label/icon only; nothing may branch on it (see change 11)
  "cape": {
    "platform": "linux",
    "arch": "x64",                                       // CAPE's word; never "amd64"
    "tags": ["linux", "ubuntu"],                         // arch is NOT a tag; OS-version tag added from the media (e.g. ubuntu2404)
    "web_conf": { "linux.enabled": "yes" },              // NEW: host-global switches this profile needs (see change 6)
    "processing": ["strace"]                             // NEW: processing modules that must be on
  },
  "hardware": {                                          // CHANGED: replaces the single "firmware" enum
    "machine": "q35",
    "boot": "uefi",                                      // "uefi" | "bios"
    "secure_boot": true,                                 // the image only ships OVMF_CODE_4M.ms.fd / OVMF_VARS_4M.ms.fd
    "tpm": false,                                        // a Linux guest does not need one; less to clone
    "disk_bus": "sata",
    "nic_model": "e1000e",                               // same persona as Windows; virtio_net/vda would show 1af4 IDs
    "clock": "utc",
    "persona": "dell-optiplex-7090"                      // NEW: SMBIOS/OUI/serial format shared with Windows (rule 3)
  },
  "resources": {
    "vcpus": 2,
    "ram_mb": 4096,                                      // 2048 is enough with desktop = none
    "disk_gb": 40,
    "min_disk_gb": 20,                                   // 12 with desktop = none
    "scratch_gb": 6                                      // CHANGED: preflight's "+ 20 GB" was Windows-specific
  },
  "media": [                                             // CHANGED: a list, with a kind
    { "kind": "installer",  "inspector": "debian-family-iso" },
    { "kind": "disk_image", "inspector": "known-cloud-image" }
  ],
  "options": [
    { "key": "desktop",  "label": "Desktop", "type": "enum", "values": ["gnome", "none"], "default": "gnome",
      "help": "GNOME is what CAPE's screenshots, the desktop view and interactive runs need. 'none' is a console-only server: smaller, faster to build, no screenshots." },
    { "key": "locale",   "label": "Locale",  "type": "string", "default": "en_US.UTF-8", "help": "..." },
    { "key": "keyboard", "label": "Keyboard layout", "type": "string", "default": "us", "help": "..." },
    { "key": "timezone", "label": "Time zone", "type": "string", "default": "UTC", "help": "..." },
    { "key": "runtimes", "label": "Runtimes for analysis packages", "type": "multi",
      "values": ["java", "node", "perl", "libreoffice", "xpdf", "firefox", "pwsh", "p7zip"], "default": ["p7zip"],
      "help": "A package is offered at submission only when its runtime is installed." },
    { "key": "decoys",   "label": "Make it look used", "type": "bool", "default": true, "help": "..." }
  ],
  "identity": {                                          // CHANGED: replaces "username and computer-name patterns"
    "account":  { "label": "Username",  "pattern": "^[a-z_][a-z0-9_-]{0,30}$", "reserved": ["root","daemon","bin","sys","sync","games","man","lp","mail","news","uucp","proxy","www-data","backup","list","irc","nobody","ubuntu","admin"], "generator": "first_name" },
    "machine":  { "label": "Hostname",  "pattern": "^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$", "reserved": ["localhost"], "generator": "<first_name>-<pc|laptop|desktop>" },
    "password": { "min": 8, "max": 64, "charset": "printable-ascii" },
    "giveaways": "shared",                               // the one list, plus profile extras
    "giveaway_match": "token"                            // CHANGED: "cape" must not match landscape/escape (see change 8)
  },
  "clone": {
    "options_changeable": ["decoys", "locale", "keyboard", "timezone"],
    "identity_changeable": ["machine"],
    "resources_changeable": true,
    "inherited": ["media", "account", "password", "desktop", "runtimes", "disk_gb"]
  },
  "pipeline": {                                          // CHANGED: keyed by media kind; steps are objects, not bare names
    "build": {
      "installer": [
        { "step": "preflight" },
        { "step": "fetch_payload",   "owner": "profile" },
        { "step": "define" },
        { "step": "remaster_media",  "owner": "profile" },
        { "step": "install",         "owner": "profile", "desktop": true,  "timeout_s": 2400 },
        { "step": "provision",       "owner": "profile", "desktop": true,  "timeout_s": 1800 },
        { "step": "sanitize",        "owner": "profile" },
        { "step": "snapshot" },
        { "step": "register" }
      ],
      "disk_image": [
        { "step": "preflight" },
        { "step": "fetch_payload",   "owner": "profile" },
        { "step": "define" },                              // copies + resizes the image instead of creating a blank disk
        { "step": "provision",       "owner": "profile", "desktop": true,  "timeout_s": 1200 },
        { "step": "sanitize",        "owner": "profile" },
        { "step": "snapshot" },
        { "step": "register" }
      ]
    },
    "clone": [
      { "step": "preflight" }, { "step": "copy" }, { "step": "define" },
      { "step": "reconfigure", "owner": "profile", "desktop": true }, { "step": "snapshot" }, { "step": "register" }
    ]
  },
  "agent": {
    "port": 8000,
    "path_style": "posix",                               // NEW: how paths and /execute quoting are written
    "ready": { "probe": "GET /", "marker": "{work_dir}/provision.done" },   // CHANGED: port alone does not mean provisioned
    "finish_dir": "/tmp",                                // NEW: replaces finish-run's C:\Windows\Temp
    "shutdown": "acpi"                                   // NEW: or "agent-command" (see 3.2)
  },
  "timeouts": { "agent_s": 600, "idle_s": 60, "shutdown_s": 180 },   // NEW: today bash constants (5400/900/60/300)
  "selftest": {
    "sample": { "source": "selftest/benign.c", "build": ["gcc", "-static", "-O1"], "name": "benign" },
    "signals": [
      { "id": "report.present",       "source": "report" },
      { "id": "network.dns_answer",   "source": "report" },
      { "id": "monitor.log_nonempty", "source": "storage", "path": "logs/strace.log" },
      { "id": "process.child",        "source": "report" }
    ],
    "facts": { "script": "selftest/facts.sh", "interpreter": ["/bin/sh"], "giveaway_scan": true },
    "extras": []
  },
  "packages": [                                          // CHANGED: entries carry the runtime they need
    { "name": "generic",     "label": "ELF binary" },
    { "name": "bash",        "label": "Shell script" },
    { "name": "python",      "label": "Python script" },
    { "name": "python_whl",  "label": "Python wheel" },
    { "name": "perl",        "label": "Perl script" },
    { "name": "deb",         "label": "Debian package" },
    { "name": "js",          "label": "Node script",  "requires": { "runtime": "node" } },
    { "name": "jar",         "label": "Java archive", "requires": { "runtime": "java" } },
    { "name": "doc",         "label": "Document",     "requires": { "runtime": "libreoffice" } },
    { "name": "pdf",         "label": "PDF",          "requires": { "runtime": "xpdf" } },
    { "name": "archive",     "label": "Archive",      "requires": { "runtime": "p7zip" } }
    // zip, wget, ps1, url omitted on purpose: broken at the pinned commit (section 1.5)
  ],
  "badges": [ { "option": "desktop", "value": "none", "label": "NO DESKTOP", "tone": "neutral" } ]
}
```

### 2.1 Step files (`guest/profiles/ubuntu/`)

| File | What it does |
|---|---|
| `profile.json` | The above, validated by the one schema. |
| `domain.xml.tpl` | Should shrink to the Linux-specific part; SMBIOS persona, hidden hypervisor, `migratable='on'` and the VNC line are OS-neutral and must be shared with Windows (change 3). Differences: `<clock offset='utc'>`, no `<tpm>`, `<smm>` only for Secure Boot, no second install CD in `run` mode. |
| `manifest.sha256` | The files the guest cannot fetch: the agent's pip wheels (Pillow, pyautogui and its pure-Python dependencies, an sdist-built `pyinotify` wheel), an optional pinned `.deb` bundle, and a reference to the apt snapshot date. Per-profile, because the repo-wide `guest/manifest.sha256` is Windows' (change 1). |
| `templates/user-data.tpl` | The autoinstall document: `identity` (hostname, username, **password as a SHA-512 crypt hash**), locale/keyboard/timezone, storage (single ext4 on the one disk), `packages`, `shutdown: poweroff`, `late-commands`. Values are written with `json.dumps` (JSON is YAML), not text substitution, so a hostile value cannot change the document (the Linux counterpart of the XML-escaping test of decision 3). |
| `steps/fetch_payload` | Downloads and verifies the manifest files; builds the apt mirror/proxy state the guest will use at build time (snapshot.ubuntu.com date pinned in the manifest); serves nothing to the guest until `provision`. |
| `steps/remaster_media` | Copies the ISO with `xorriso` replaying the boot records, changing only `/boot/grub/grub.cfg` to add `autoinstall` (so Subiquity does not stop at "Continue with autoinstall? yes/no") and builds the second ISO labelled `cidata` (`user-data`, `meta-data`). The signed shim and grub are untouched, so Secure Boot still passes. |
| `steps/install` | Boots the installer domain, waits for the domain to power itself off (`shutdown: poweroff`), no keystrokes. Can use the generic pause for a media that cannot be automated (change 10). |
| `steps/provision` | Defines the `run` domain (no CDs), boots the installed system, waits for the agent and `{work_dir}/provision.done`, fetches the provisioning log, and runs the pause logic if an option needs the user. First-boot work (done by a one-shot script from the seed, not by cloud-init modules left behind): install `strace`, `sudo`, `xterm`, the desktop and chosen runtimes from the build-time apt source; install the agent as a root systemd unit; static IP; X11 forced + autologin + `/root/.Xauthority` link when `desktop = gnome`; firewall, NTP, auto-updates, snapd off. |
| `steps/sanitize` | Removes what would say "this was built": cloud-init and its logs/instance data, `/var/log/installer`, the autoinstall user-data copy, apt proxy config and lists, pip caches, shell history, the seed device mount, `/etc/machine-id` (regenerated at first boot), SSH host keys (no `openssh-server` is installed at all), then `sync`. This is also the step the decision-16 gate checks. |
| `steps/reconfigure` | Clone: the guest is booted at the source's old address; `/store` a script and `/execute` it: new hostname + `/etc/hosts`, new static IP written into the network config, new `machine-id`, new SSH keys if any, remove `/var/lib/systemd/random-seed`, apply the changed options (decoys, locale, keyboard, timezone), `sync`, reboot once. IP change is `async` with a delay because the request that triggers it rides on the address being changed. |
| `payload/` | `agent.service.tpl` (neutral unit name and path), `firstboot.sh`, `x11.sh`, `decoys.sh`, and a copy of CAPE's `agent.py` taken from the image. All names come from the one neutral-names table of decision 16. |
| `selftest/facts.sh`, `benign.c` | `FACT key=value` lines (DMI strings via `/sys/class/dmi/id`, CPU flags, NIC and disk model, kernel `dmesg` hypervisor lines, hostname, accounts, services, cron, `Run`-like autostarts, top-level folders, listening ports) and a small static ELF that forks a child, writes a file and resolves a name. |

### 2.2 How the guest is made not to say "tartarus"/"cape" (decision 16 on Linux)

- Working folder, unit name, process name and file names are neutral and per-guest (the same table as
  Windows); `agent.py` is installed under that name, but its *content* still says `CAPE Agent`
  (allow-list, or the optional patch).
- The installer leaves the strings in many places: seed volume label (`cidata` is neutral),
  `/var/log/installer/autoinstall-user-data`, `/var/lib/cloud/`, `/var/log/cloud-init*.log`, the
  `late-commands` history, `apt` proxy config, `bash_history`. `sanitize` removes them and the facts
  script proves it.
- Hostname, account and password come from the identity rules. The account is `sudo`-capable only if
  the analyst needs a desktop session; the sample runs as root through the agent regardless.
- **The substring gate must become a token gate on Linux** (change 8): `landscape`, `escape`, `scape`
  contain `cape`, and Ubuntu ships `landscape-common` and many `escape` words in configs and in our
  own shell scripts.

### 2.3 What its "options" are, and why these

There is no Defender. What an analyst can sensibly choose: **desktop** (the one real trade-off: CAPE's
screenshots need GNOME, and so does the interactive view; a console server is small and fast but
screenshot-less), **runtimes** (decides which packages the Submit dialog offers), **locale / keyboard /
timezone** (Linux has these as install-time choices; an ISO is not single-language like a Windows
retail ISO), **decoys**. Sysmon-for-Linux and Tracee are deliberately not options: both are enabled by
**global** CAPE switches (`sysmon_linux`, `tracee_linux` in `auxiliary.conf`), so a per-guest option
could not honour them (change 6), and Tracee needs Docker inside the guest.

### 2.4 How its clone works

Same plan as decision 15, with these Linux specifics: copy the source's base `qcow2` with `qemu-img
convert` and the nvram if the *domain* has one; no swtpm because `tpm = false`; new UUID/MAC/SMBIOS/disk
serial from `generate_identity`; cold boot from a crash-consistent disk is a journal replay on ext4
(less scary than NTFS, but the source's `sync` must have run: `sanitize` ends with it, and the
snapshot step should run `sync` through the agent before the memory snapshot). In-guest: hostname,
`/etc/hosts` (so `sudo` does not hit INetSim DNS for its own name), static IP (match the interface
by name, not by MAC, because the MAC is new), `machine-id`, SSH host keys, `random-seed`. Filesystem
UUIDs stay identical between clones (accepted, like the Windows install date).

## 3. Field by field, and generic part by generic part

Legend: **as is** = expressible by decision 17 as written; **change** = needs an amendment
(numbers refer to section 5); **n/a** = does not apply to this OS but needs no change.

### 3.1 Profile schema fields

| Field (decision 17) | Linux | Reason |
|---|---|---|
| `id` | as is | `ubuntu`. Granularity question is change 9. |
| display name | as is | |
| `family` (`windows`, `linux`) | as is, but demote | Redundant with `cape.platform`; keep as a label only, never branch on it. |
| CAPE `platform` | as is | `linux` (`kvm.conf.default:27-29`). |
| CAPE `tags` | **change 5** | An OS-version tag is mandatory for Windows (`kvm.conf.default:38-41`) and optional for Linux; the arch is a field, not a tag. The registration renderer must derive tags from the profile plus the media (e.g. `win11`, `ubuntu2404`), so the profile has a base tag list and the media contributes the version tag. |
| `arch` | as is | `x64`/`x86` only (CAPE's vocabulary). Non-x86 guests are emulation, out of scope. |
| `firmware` (`uefi-secureboot-tpm` or `bios`) | **change 3** | One enum hides five independent choices (boot, Secure Boot, TPM, machine type, disk bus, NIC model, clock). A Linux guest wants UEFI + Secure Boot with no TPM; the image has only the `.ms` OVMF pair, so "UEFI without Secure Boot" is not available and "BIOS" means SeaBIOS (its banner is a known tell, `cape-integration.md` Findings). External snapshots work on a BIOS domain too (they are a libvirt feature of disks and memory; only *internal* snapshots are refused for pflash), so one snapshot mechanism survives. |
| default resources, min disk | as is, plus **change 3** | Add `scratch_gb`: the preflight's "+ 20 GB" is Windows ISO scratch; a cloud image needs ~4 GB. |
| media inspector | **change 2** | Contract "(media file in, `[{profile, variant, version, language, arch}]` out)" works for a Linux ISO (read `.disk/info` and `casper/`, no mount, no 7 GB extraction). It does not cover a disk image, nor media that carries "any language". See 3.3. |
| options (key, label, type, default, help, `requires_user_step`) | as is, plus small additions | Enough for `desktop`, `locale`, `keyboard`, `timezone`, `runtimes`, `decoys`. Needs a `multi` type, an `enum` with `values`, and a way to say an option is *CAPE-global* (change 6). `requires_user_step` has a Linux use only for manual installers (change 10). |
| name rules: username / computer-name patterns, reserved, giveaway list | **change 8** | Not general: two fixed slots named after Windows concepts, patterns that Windows needs a negative rule for ("not all digits"), a giveaway match that is substring-only. Replace by an `identity` object (account, machine, password) with `pattern`, `reserved`, `generator`, and a shared giveaway list with a match mode. |
| clone capabilities | as is | Fits (options + names + resources + inherited). Add `identity_changeable`. |
| pipeline (ordered step names, build and clone) | **change 2, 10** | Needs a pipeline per media kind, and step entries that carry metadata (`owner`, `desktop`, `timeout_s`, progress weight) instead of bare names. |
| agent (port and how to wait) | **change 4** | Add `path_style`, the marker path, `finish_dir`, `shutdown`. |
| self-test (sample file, signals, extras) | **change 7** | Signals need a generic vocabulary with a `source` (events, report, storage). `benign.c` + a compiler line replaces "mingw at image-build time". |
| packages | **change 5** | A static list is wrong; entries need `requires`. |
| step contract: `STEP`, `PROGRESS n`, `LOG` | as is | A step is any executable. |
| step contract: exit code "waiting for the user" | as is | Generic. Linux use is change 10. |
| step contract: idempotent | as is | Needs the sequencer to also say *which* step is resumed after a pause: the same one (decision 11), not "provision". |
| `domain.xml.tpl` in the profile | **change 3** | See the rule-3 point: the OS-neutral hardware persona would be copied. |
| installation templates, provisioning scripts | as is | They are profile files. But "**the payload ISO**" (CD with answer file + installers + agent) is Windows' delivery method; Linux needs a seed ISO and an apt source (change 1). |

### 3.2 Generic parts of the plan

| Generic part | Verdict | Reason |
|---|---|---|
| `registry/guest.json` (decision 5) | **change 7** | Keeps `os` and `options`. Remove `edition` (Windows noun; use a `media` object with `variant`, `version`, `language`, `arch`, `sha256`), add `capabilities` (installed runtimes, desktop) which `packages` and the Submit dialog read, and `work_dir`. |
| Address allocation | as is | Static IP from `.10`; Linux sets it in the installed system's network config. The "(`provision.ps1` already takes `-GuestIp`)" wording is Windows. |
| Single CAPE registration | as is, plus change 5 | `kvm.conf.d/guests.conf` with a section per guest; two platforms in one file is fine (`task.platform` filters, `machines.py:263-264`). The renderer takes `platform`, `arch`, `tags`, `snapshot` from the guest, not constants. |
| External snapshots with memory | as is | Works for any domain (see firmware row). Hard-coded `--diskspec sda,...` in `take_clean_snapshot` must be derived from the domain (change 3). Add a `sync` before the snapshot (crash-consistency of the copied base disk, change 4). |
| Health: VM defined | as is | |
| Health: snapshot | as is | |
| Health: agent | as is | `GET /status` exists on Linux (`agent.py:449`). The "wait" differs only in the marker path. |
| Health: CAPE registration | as is | `apiv2/machines/list` lists platform and tags. |
| Desktop through guacd/VNC | as is | QEMU VNC is OS-neutral. Availability by *step* needs change 10. For a running analysis it needs the desktop to exist (`desktop = none` shows a text console; `nohuman`'s xterm fails without X) so interactive = per-profile (change 4). |
| Self-test signals | **change 7** | Windows' set (process, file, registry, DNS, EICAR, no giveaways) is not a generic vocabulary; Linux has no registry, no EICAR verdict, and no event-level file/process signals until a Linux normaliser exists. |
| Submit dialog's package list | **change 5** | Profile list is not enough (runtimes, broken packages); also the guest/sample platform mismatch (1.4) must be shown before submit, not as a CAPE error after. |
| Name validation | **change 8** | See name rules row. Also password hashing is a renderer concern (autoinstall wants a crypt hash), invisible to the generic layer. |
| Giveaway scan | **change 8** | Substring on `cape` is unusable on a Linux filesystem; scan *locations* belong to the profile's facts script (processes, units, cron, `/etc`, `/home`, `/root`, `/var/lib`, `/var/log`, top-level dirs). |
| Exclusion rules (decision 7) | as is | They exist because `cuckoo.py` powers off a registered machine at start (M0b). OS-independent. |
| Control-service routes (decision 1) | as is | OS-independent; the one route that touches the guest agent, `finish`, needs change 4. |
| `finish-run` | **change 4** | `C:\Windows\Temp`, backslash, `.10:8000` hard-coded. |
| `build-guest.sh` generic steps | **change 1, 2, 3** | `download_into_cache` (manifest of files), `prepare_disk_and_firmware` (blank disk), `render_domain install|run` (two CDs, `OS_BOOT`), `take_clean_snapshot` (`sda`), `provisioning_done` (`C:\tartarus\provision.done`), `dismiss_press_any_key` (Windows boot prompt) are all Windows-shaped. |
| Job/pause (decision 11, 14) | as is, wording change | "step `provision`" and "after provision" must read "the step that exited with the pause code". |
| Adoption of `win` | n/a | Windows only; the adoption code is a profile concern or a one-off. |
| Self-test run via Tartarus, `self-test` tag | as is | Needs `web.conf [linux] enabled = yes` for an ELF sample, otherwise the backend gets `"Linux binaries analysis isn't enabled"`. |
| Clone: `copy` | as is, plus change 3 | Copy nvram **iff the domain has one**; create swtpm **iff it has `<tpm>`**. |
| Clone: `reconfigure` | as is | Profile step; the agent transport (`/store`, `/execute`, `/retrieve`) is generic, only the paths and quoting are profile (`agent.path_style`). |

### 3.3 The media inspector, for a Linux ISO and for a cloud image

- **Linux installer ISO.** ISO 9660 + El Torito, no UDF. Read-only in userspace (`7z` is in the image;
  `xorriso -indev -find` also works): `.disk/info` ("Ubuntu-Server 24.04.1 LTS ... amd64"), `casper/`,
  `/boot/grub/grub.cfg`, `dists/`. One entry out: `{profile: ubuntu, variant: "Server", version:
  "24.04.1", language: null, arch: x64}`. **Do not loop-mount** untrusted media in the privileged
  `cape` container for non-Windows media; the S0a plan to mount is a risk for an inspector that must
  accept anything dropped in `data/iso` (change 2). `language: null` must be allowed, and the
  `locale` then comes from an option.
- **Cloud image (qcow2/raw).** `qemu-img info --output=json` gives format and virtual size (use as
  `min_disk_gb`). Identifying the OS inside needs libguestfs (not in the image) or a mount (no);
  recognise it **by sha256 against a known-images list the profile ships** (from the vendor's
  `SHA256SUMS`), and treat unknown images as "not recognised", like an unrecognised ISO. `data/iso`
  needs to accept `.img`/`.qcow2`; the listing name is "media", as decision 17 already says.
- **No ISO at all** (a cloud image is already installed): the `installer` branch of the pipeline is
  skipped; `define` creates the disk by copying and growing the image (`qemu-img convert` +
  `resize`) instead of `qemu-img create`; the first boot runs cloud-init from a `cidata` seed ISO,
  which is the profile's `provision`. The wizard's step 1 is "choose media" either way.

## 4. What decision 17 got wrong or missed

**A. No model for software acquisition (the largest gap).** Windows' build is hermetic: Python
installer, Pillow wheel and `agent.py` are on a CD, pinned in `guest/manifest.sha256`. A Linux guest
needs `strace`, `sudo`, `xterm`, a desktop and runtimes, i.e. an apt closure, and `tt-guest` is
isolated with INetSim answering DNS. Options, all with costs: (a) a pinned offline `.deb` bundle (hash
in the manifest, closure resolution is fiddly); (b) an apt proxy/mirror served by the `cape` container
on `192.168.150.1` for the build only (the guest never sees the internet; pin by a dated snapshot
archive; the proxy config is removed in `sanitize`); (c) a temporary second NIC with internet (weakens
the "no weaker isolation" outcome; rejected). The seam needs: a per-profile manifest, and the idea
that `fetch_payload` is a *profile* step that may build state beyond flat files. Without (b) or (a)
there is no `strace` in the guest and no Linux profile.

**B. Pipeline is not media-agnostic.** `preflight -> define -> install -> provision -> snapshot ->
register` assumes an installer. A cloud image has no `install`; some manual distros need a pause in
`install`, not in `provision`. And `define` currently also creates the blank disk and renders
`install`/`run` modes with two CDs and a boot-order macro; a Linux installer needs the installer ISO,
the seed ISO, and (for the cloud image) neither installer nor blank disk.

**C. "Domain template per profile" duplicates the hardware persona.** `domain.xml.tpl` carries Dell
SMBIOS, `host-passthrough`, hidden KVM, `migratable='on'`, VNC. These are OS-neutral. The renderer is
`string.Template.safe_substitute` (`build-guest.sh:render_template`): no conditionals, so an optional
`<tpm>`, `<smm>`, `<nvram>` has to be passed as XML-fragment variables the way `INSTALL_CDROM_SOURCE`
already is. Rule 3 argues for a generic template built from fragments chosen by the profile's
`hardware` block, plus one shared persona. Also the disk target (`sda`), NIC model (`e1000e`) and
clock (`localtime` vs `utc`) are profile data; generic steps must read the disk target from the domain.

**D. Per-OS timeouts and waits are bash constants** (`INSTALL_TIMEOUT=5400`, `AGENT_TIMEOUT=900`,
`IDLE_SECONDS=60`, 300 s shutdown, a 20 s "press any key" nudge). They belong in the profile (and per
step), together with the way the guest is shut down: ACPI works for Windows; on a GNOME session the
power button may open a dialog instead of powering off, so a Linux profile may need
`agent-command` (`/execute poweroff`). Not verified.

**E. Where the "kind of CAPE package" lives.** In three places that disagree: the profile's `packages`
(decision 17), CAPE's analyzer folder (the real list, partly broken), and `web.conf [packages]` on the
host (maps a package to required machine tags, `machines.py:272-273`, e.g. `msix = win10,win11`). The
profile should list what is *offered*, with `requires` on installed runtimes recorded in `guest.json`
(`capabilities`), and a CI test could compare the list to the analyzer folder of the pinned commit.
The backend's `PackageName` regex accepts anything; the guest's list should be the validator
(`B5` in the plan already says "accepted `package` values from the chosen guest's profile").

**F. Interactive is Windows-shaped in the backend.** `INTERACTIVE_OPTIONS = "interactive=1,nohuman=yes"`
(`cape/client.py:25`) means "keep running until timeout, no mouse mover" on Windows. On Linux
`interactive` is ignored, `nohuman` wraps the sample in `xterm`, and the analysis ends when the sample
exits unless `enforce_timeout`. It must come from the profile (`agent.interactive_options`, and
`enforce_timeout` as a task field).

**G. `finish-run` and the control service interface.** Hard-coded folder and separator; the plan's
"take the guest's address with each request, validate it lies in `GUEST_SUBNET`" is weaker than the
control service looking the guest up by *name* and reading `ip`, `agent.port`, `agent.finish_dir`,
`agent.path_style` from `guest.json` and the profile.

**H. Desktop availability is keyed on step names.** B4: "available only during install, provision and
the pause". Those are Windows' step names. Make it a `desktop: true` attribute of the pipeline entry.

**I. Self-test vocabulary.** Signals like `registry` or `EICAR verdict` cannot be listed by a Linux
profile, and the plan's own "outside the seam" paragraph says a Linux run has no events yet. Define a
catalog of signal ids with a `source` (`events`, `report`, `storage`) and have the verdict function
(B3, pure) dispatch on it; the profile picks ids. Unknown ids fail schema validation.

**J. The substring giveaway gate** (decision 16 and G1's scan test) breaks on Linux (`landscape`,
`escape`). Use token boundaries (`\bcape\b`, path components), per profile.

**K. Profile granularity and sharing.** Ubuntu autoinstall and Debian preseed share provisioning,
reconfigure, facts and sanitize (apt, systemd, netplan/ifupdown aside). A directory per profile with no
sharing forces copies (rule 3) at the second Linux profile. Not a C2 blocker if the loader's step
lookup is a search path (profile dir, then its `extends`, then generic).

**L. What the plan got right and can stay:** one `guest.json`, one registration, external snapshots
with memory, health checks, the VNC proxy, the exclusion rules, address allocation, the pause as an
exit code, step idempotence, the CI "every step named exists" test, the `grep` gate. The seam *is*
mostly a data seam; the Windows leaks are in vocabulary and in the few bash helpers listed above.

**M. Linux-specific anti-VM tells a profile cannot or will not fix** (for the card and the docs; none
of these were checked in a guest): `TracerPid` and the strace parent chain; empty process
environment; `lspci` for QEMU's std VGA (`1234:1111`, `bochs` driver) and `1b36` PCIe root ports;
`/proc/bus/input/devices` and `lsusb` for the QEMU USB tablet; `dmesg` lines about the hypervisor and
paravirtual clocks (hidden by the domain, but `dmesg` also shows virtual ATA/CD-ROM strings); `uptime`
equal to the snapshot's; rdtsc timing; installer/cloud-init leftovers (fixed by `sanitize`); `sshd`
host keys (avoided by not installing it); filesystem UUIDs shared between clones.

## 5. Concrete changes to decision 17, by importance

"Before C2" = must be settled before the build engine, loader and step interface are written, because
C2 fixes those interfaces; "after" = can follow without rework.

| # | Change | Reason | When |
|---|---|---|---|
| 1 | Add a **payload/software-acquisition model**: a manifest per profile (`guest/profiles/<id>/manifest.sha256`), `fetch_payload` as a profile step that may build more than flat files (an apt snapshot mirror/proxy on `192.168.150.1` for build time only, removed in `sanitize`), and drop `download_into_cache` from the generic steps. | A Linux guest cannot be built hermetically from three files; without it there is no `strace` in the guest. | **Before C2** |
| 2 | Make **media a typed list** (`installer`, `disk_image`) and the **pipeline per media kind**; allow `install` to be absent; `define` creates the disk by `create` or `copy + resize` depending on media kind; the inspector for non-Windows media is **read-only userspace** (no loop mount) and may return `language: null`; unknown disk images are recognised by sha256 against a profile list. | A cloud image has no installer or blank disk; S0a's loop mount is unsafe for arbitrary media. | **Before C2** |
| 3 | Replace `firmware` by a **`hardware` block** (`machine`, `boot`, `secure_boot`, `tpm`, `disk_bus`, `nic_model`, `clock`, `persona`); build the domain from fragments selected by it, with **one shared persona** (SMBIOS, OUI, serial formats) instead of a template per profile; generic steps (snapshot `--diskspec`, `copy` of nvram and swtpm) read disk target, nvram and TPM **from the domain XML**, never from the profile or a constant. | Five unrelated choices behind one enum; rule 3 (Dell block copied); `sda` and nvram/TPM assumptions in `take_clean_snapshot` and the clone copy. | **Before C2** |
| 4 | Extend **`agent`** and the **control-service interface**: `path_style`, `ready.marker`, `finish_dir`, `shutdown` (`acpi`/`agent-command`), `interactive_options` (+ `enforce_timeout`), `pre_snapshot` (`sync`); `finish` takes the **guest name** and the control service resolves ip/port/dir from `guest.json` + profile (replacing "address per request"); `finish-run` loses `C:\Windows\Temp` and the backslash. Backend `INTERACTIVE_OPTIONS` comes from the guest's profile. | The finish trick applies to Linux (`analyzer.py:335-344`) but with `/tmp`; Linux interactive means `enforce_timeout`, not `interactive=1`. | **Before C2** (interface), backend part with B5 |
| 5 | **`packages` entries get `requires {runtime}`**, `guest.json` records `capabilities`, the CAPE `tags` are *profile base tags + media-derived version tag*, and a CI test compares the list with the analyzer folder of the pinned commit; mark `zip`, `wget`, `ps1` and `url` as not offered. Surface the **guest/sample platform mismatch** (CAPE refuses with `Wrong platform`) in the Submit dialog or as a readable 409. | CAPE's Linux packages are partly broken; runtimes decide what works; `File.get_platform()` calls every non-ELF/shell sample `windows`. | Schema before C2; UI with F18 |
| 6 | Let a profile declare **host-global CAPE settings it needs** (`web.conf [linux] enabled = yes`, `[strace] enabled = yes`, maybe `dynamic_platform_determination`), applied by the image/entrypoint at start from every installed profile (not per guest), and mark options that would require a global CAPE switch (`sysmon_linux`, `tracee_linux`, `QemuScreenshots`) as **not allowed as guest options**. | Linux submission is refused while `[linux] enabled = no`; `auxiliary.conf` switches are global, and `QemuScreenshots` requires both `screenshots_*` off (`auxiliary.conf.default:68`). | Before C2 (schema field), implementation C1/C2 |
| 7 | **Self-test signals from a catalog with a `source`** (`events`, `report`, `storage`); the selftest sample is `source + build command`; `guest.json` replaces `edition` with a `media` object and gains `capabilities` and `work_dir`; the verdict function dispatches on signal id. | Linux has no registry or EICAR verdict and no event-level signals yet; `benign.exe` is mingw-specific. | Schema before C2; verdict with B3 |
| 8 | Replace "username / computer-name patterns" by an **`identity` object** (`account`, `machine`, `password`) with `pattern`, `reserved`, `generator`, and a shared giveaway list with **`match: token`** (word boundaries, path components); the profile's facts script owns the scan locations. | Windows' two slots and its "not all digits" rule are not general; `cape` is inside `landscape` and `escape` on any Linux filesystem and in any shell script. | Before G1 and C2's validator |
| 9 | Make profile directories **resolve steps through a search path** (own dir, then `extends`, then generic); first Linux profile is `ubuntu`, a `debian` profile would `extends` a shared apt/systemd base. | Avoid copying provisioning between distros (rule 3). | After C2 (keep the lookup a function) |
| 10 | Step contract: the **pause may come from any step**, the pipeline entry carries `desktop: true`, `timeout_s` and an optional progress weight, and a `continue` **re-runs the step that paused**; B4's availability rule uses `desktop`, not names. | Linux has a real use for a pause in `install` (a distro with no unattended installer: the analyst installs by hand, the rest is automated); step names `install`/`provision` are Windows'. | Before C2 |
| 11 | `family` becomes a label; add `schema_version`; per-profile `timeouts` (agent, idle, shutdown) replace the bash constants. | Nothing may branch on `family`; the constants differ per OS. | With the schema |
| 12 | Document in the "adding an OS" checklist what CAPE does and does not support per platform (unofficial status, packages, strace text format, analysis ends with the sample) and make the **profile card show "unofficial"** for a profile whose CAPE platform has no official support. | CAPE's own wording (`linux.rst:5`); expectations. | Docs |

Changes 1 to 4, 6 (schema part), 7 (schema part), 8 and 10 are the ones that shape C2's interfaces
(loader, sequencer, step environment, `define`/`snapshot`/`copy` steps, control-service routes).
If only three can be afforded before C2, take 1, 2 and 3: they change what the generic build steps
*are*; the rest are fields and vocabulary.

## 6. Could not verify

Everything below is inferred from memory of the distro tooling or from reading CAPE, not observed.

- **Ubuntu autoinstall / cloud-init behaviour**: that `shutdown: poweroff` is honoured, that the
  password must be a crypt hash, the "Continue with autoinstall?" prompt when `autoinstall` is not on
  the kernel command line, the `cidata` NoCloud seed, `late-commands` running in the installer
  environment, 24.04 *desktop* supporting autoinstall. I tried to fetch Canonical's reference pages and
  they returned 404, so none of it is checked. Debian preseed (`preseed/url`, kernel arguments, direct
  kernel boot defeating Secure Boot) is likewise from memory.
- That a **remastered ISO** (only `grub.cfg` changed, boot records replayed with `xorriso`) still boots
  under the `.ms` OVMF Secure Boot, and that direct kernel boot does not.
- That the `.ms` OVMF vars boot Ubuntu's shim at all, and that SeaBIOS/UEFI differences do not matter
  for the Linux guest. Only the Windows guest and a BIOS Cirros probe have run here.
- **Whether CAPE's Linux analyzer works at this commit.** Read only: `strace` streaming, the finish
  folder, package selection. Not executed. The `zip`/`wget` `TypeError` and the `ps1` class-name
  mismatch are by inspection (the `bytes.index(str)` error was confirmed on the host Python; the
  rest was not run). The docs mention `systemtap-runtime`; the code uses `strace`.
- That the **finish trick ends a real Linux analysis** and in what time; that `TMP` is unset in a
  systemd-started agent (a `PrivateTmp=` unit would change which `/tmp` the analyzer sees).
- That the behaviours listed in 1.4 (platform refusal for Python/Perl/deb/jar samples, the
  effect of `dynamic_platform_determination = no`, `[linux] enabled = yes` being enough through
  `apiv2/tasks/create/file`) hold end to end. Read in `web_utils.py` and `objects.py` only.
- **GNOME-specific claims**: that `screenshots_linux` works on a GNOME 46 Wayland/X11 session as the
  code expects, that forcing X11 plus autologin plus a `/root/.Xauthority` link makes `nohuman`'s
  `xterm` appear on the VNC desktop, and that ACPI shutdown of a GNOME session works.
- **Timekeeping and "hidden hypervisor"** on Linux (`kvm hidden`, `hypervisor` CPUID bit disabled, no
  `kvm-clock`, `hpet` off): whether clocksource selection is stable and whether a memory snapshot
  revert plus `date -s` is clean.
- Build time, disk use and RAM figures for a Linux guest (not estimated beyond order of magnitude).
- Whether a 64-bit `x64` tag is needed on the machine: the code path that wanted it
  (`_machine_can_service_task`) has no callers at this commit; if a later CAPE starts calling it, Linux
  machines need `x64` in `tags`. (A related point for the existing Windows registration is outside
  this spike.)
- The tell list in 4.M and 1.9 beyond what the CAPE source itself shows (the `strace` command line and
  environment, the root-level analyzer folder).
- Anything about macOS (`darwin`) guests: CAPE has `platform = darwin` but no analyzer folder was read.
