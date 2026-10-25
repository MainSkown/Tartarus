# Troubleshooting

Start with the logs and the health of the stack:

```bash
make logs            # follow every container's log (Ctrl+C stops following)
docker compose ps    # each container and its health
make smoke MODE=prod # checks a running stack
```

The header dots show the same health as the app sees it. See [the health dots](#the-health-dots).

## Preflight reports a FAIL

`make preflight` prints `[OK]`, `[WARN]` or `[FAIL]` per check. Fix every `[FAIL]`. A `[WARN]` does not stop the stack.

| Message | Fix |
|---|---|
| `Docker daemon unreachable` | Add your user to the `docker` group and log in again, or use rootless Docker. |
| `Docker Compose ... is older than 2.24.4` | Update the Docker Compose plugin. |
| `vm.max_map_count is ..., OpenSearch needs >= 262144` | `sudo sysctl -w vm.max_map_count=262144`. The setting is lost after a reboot unless you put it in `/etc/sysctl.d/`. |
| `/dev/kvm missing` (WARN) | The `cape` container needs KVM. The UI still runs without it, but no analysis can start. Check `ls -l /dev/kvm` and that virtualization is enabled in the firmware. |
| `NAME is not set in .env` or `is the placeholder` | Run `make init-env` on a new install. On an old `.env`, set a random value: `openssl rand -hex 32`. Do not change the database passwords of an existing install, because the databases keep the old ones. |
| `... it needs >= 32` | A token is too short. Use `openssl rand -hex 32`. |
| `.env is readable by group or others` (WARN) | `chmod 600 .env` |
| `RAM ... is below the 16 GB` or `free disk ... is below 200 GB` (WARN) | Less than the stack is sized for. Analyses may be slow or fail when a guest is large. |

## The guest does not run after a kernel update

**Symptom.** An analysis fails with `Unable to open /dev/net/tun, is tun module loaded?: No such device`.

**Cause.** The host was updated to a new kernel, but you are still running the old one, and its modules were removed. The `tun` module is missing.

**Fix.** Reboot into the new kernel. Check with `uname -r` and `ls /lib/modules`. Then check `lsmod | grep tun`.

If you cannot reboot now, `sudo modprobe tun` loads the module for the running kernel, if the module exists for it.

After the fix, if CAPE still does not list the guest, restart the CAPE service inside its container:

```bash
docker exec tartarus-cape supervisorctl restart cape
```

This stops any analysis that is running, so do it when none is running. Reboot the host before you start guests after every kernel update.

## A guest build step failed

The build page shows a red block with the failed step and its error. Read the `BUILD LOG` tail first. Then choose:

- **`[RESUME]`** runs the failed step again and keeps the steps that passed. Use it when the cause is gone, for example a download that failed on a network hiccup.
- **`[RESTART]`** starts again from `preflight` and throws away what was done. It takes the full build time. Use it when you want a clean start, or when resume does not help.

A step that fails during the build has no self-test, so `[RE-RUN SELF-TEST]` is not offered. Resume or restart instead.

Some things that look stuck are normal. The `install` step can show an idle desktop for minutes. The page warns `no news for N min` only after two minutes without any output.

`symbols` never fails a build. If the Microsoft symbol download fails, the guest is still built, and memory analyses of it have no findings.

## The Defender pause

**Symptom.** The build pauses with an amber `WAITING FOR YOU` block.

**Cause.** The scripted step could not find the Tamper Protection switch in Windows Security. This happens only when the lookup fails.

**Fix.** On the desktop below the block, open Windows Security, go to the threat protection settings, switch Tamper Protection off, and press `[CONTINUE]`. The step reads the switch again. If it is already off, the step goes on.

## 421 or 403 when you open the app

Tartarus accepts requests only from `localhost`, `127.0.0.1` and `[::1]`.

- **421 Misdirected Request**: you opened the app with another name, such as a LAN name or a hostname. The server does not know that name.
- **403 Forbidden**: a page from another site tried to write to the app or open its live connection. Close that page and try again.

Open **http://localhost:8080** instead. The port is `TARTARUS_PORT` in `.env`.

To use another name anyway, you must change two places and rebuild:

1. Add the name to `TARTARUS_ALLOWED_HOSTS` in `.env`, comma separated.
2. Add the name to the host map in `frontend/nginx.conf`. The frontend image copies that file when it is built.

Then run `make up`. The app is served over plain HTTP. Putting it on a network is not supported in v1. See [security](../security.md#hardening-checklist-for-a-lan-or-shared-install) before you do.

## The stack did not start after a reboot

This is expected. No container starts by itself after a reboot. Run:

```bash
make up
```

If it fails, run `make preflight` first.

## The health dots

Each dot is green, amber or red. Hover over it for the message. Click the Guest dot to see each guest.

| Dot | Green | Amber | Red |
|---|---|---|---|
| **CAPE** | CAPE answers its API. | Never shown: CAPE is green or red only. | CAPE cannot be reached, or the API token is refused. The tooltip says which. |
| **Guest** | Every guest is `READY`. | Some guests are not ready. The tooltip names them. | No guest is ready, no guest has been built, or the guest control service cannot be reached. |
| **Store** | Postgres and OpenSearch are both healthy. | OpenSearch reports a cluster status other than green or yellow. | Postgres or OpenSearch cannot be reached. The tooltip lists each one. |

A red **Guest** dot with `no guest has been built` means you need [a guest](building-a-guest.md).

If the header shows an amber bar with `Reconnecting…`, the live connection to the backend dropped. The page reconnects by itself. If it stays, check `make logs`.

## Other messages

| Message | Meaning and fix |
|---|---|
| `A guest is being built` (409) | A build, clone or self-test is running. No analysis can start until it ends. Wait, or cancel the build. |
| `No guest is ready` on Submit | Check the Guest dot and the **Guest VM** page. |
| The analysis stays queued | Another analysis runs on the guest you picked, or a build is running. The page says `Queued, position N`. |
| Red `REPORT FAILED` banner | The run finished but its report could not be read. Press `[RE-INGEST]` in the banner. |
| `A memory dump needs ... free` | CAPE storage has too little free space. Delete analyses or see [backup and disk](backup-and-disk.md#freeing-space). |
