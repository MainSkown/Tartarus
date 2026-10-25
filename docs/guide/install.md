# Install

Tartarus runs as a Docker Compose stack on one Linux machine. You supply the Windows installation media yourself. Tartarus never bundles or downloads Windows.

Windows hosts are not supported in v1. See [the overview](../overview.md#after-v1-not-designed-yet).

## What you need

| Item | Needed | Notes |
|---|---|---|
| Linux host with KVM | yes | `/dev/kvm` must exist and the CPU must have `vmx` or `svm`. |
| Docker with Compose | 2.24.4 or newer | Check with `docker compose version`. |
| RAM | 16 GB minimum, 32 GB recommended | OpenSearch takes 1.5 GB of heap. A guest takes 4 GB while it runs. |
| Free disk | 200 GB minimum | About 5 GB for a Windows ISO and about 22 GB per guest. See [backup and disk](backup-and-disk.md). |
| Windows ISO | yes | Windows 11 and Windows 10 22H2 were tested. |

Check KVM:

```bash
ls -l /dev/kvm
grep -Ec 'vmx|svm' /proc/cpuinfo
```

The second command must print a number above 0.

Your user must be able to run Docker. If `make preflight` says the daemon is unreachable, add your user to the `docker` group, log in again, or use rootless Docker.

## Steps

1. Get the code.

   ```bash
   git clone https://github.com/MainSkown/Tartarus.git
   cd Tartarus
   ```

2. Raise the map count that OpenSearch needs. This setting does not survive a reboot.

   ```bash
   sudo sysctl -w vm.max_map_count=262144
   ```

   To keep it, put `vm.max_map_count = 262144` in a file under `/etc/sysctl.d/`.

3. Create the secrets.

   ```bash
   make init-env
   ```

   This writes `.env` from `.env.example`, with random values for the four secrets, and sets its mode to 600. It never overwrites an existing `.env`. Keep a copy of `.env` somewhere safe: the databases were created with the passwords in it.

4. Check the host.

   ```bash
   make preflight
   ```

   Each line is `OK`, `WARN` or `FAIL`. Fix every `FAIL`. A `WARN` does not stop the stack, but it tells you what is short. [Troubleshooting](troubleshooting.md#preflight-reports-a-fail) lists the common ones.

5. Start the stack.

   ```bash
   make up
   ```

   The first run builds the images. The CAPE image takes a few minutes.

6. Open http://localhost:8080 in a browser.

   On a new install the Dashboard shows `> guest VM not ready` with a `[BUILD GUEST]` button. Continue with [building a guest](building-a-guest.md).

7. Stop the stack when you are done.

   ```bash
   make down
   ```

   This stops the containers and keeps all your data.

## Good to know

- **The stack does not start after a reboot.** Every container has restart policy `no`. Run `make up` again after you log in.
- **Only this machine can open the app.** The page listens on `127.0.0.1` only. To change the port, set `TARTARUS_PORT` in `.env` and run `make up` again.
- **Logs and status.** `make logs` follows the logs. `docker compose ps` shows the health of each container.
- **Where the data is.** Analyses, guests and databases live in named Docker volumes, not in a `data/` folder. Your Windows ISO goes in `data/iso/` inside the repository. See [backup and disk](backup-and-disk.md) for the list of volumes and what to keep.
