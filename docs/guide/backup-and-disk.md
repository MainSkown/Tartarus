# Backup and disk

Tartarus keeps almost everything in Docker volumes, not in a folder you can copy. This page lists the volumes, what each one holds, and how to free space.

## Where the data is

| Volume | Holds | Keep it? |
|---|---|---|
| `tartarus_pg-data` | The Tartarus database: analyses, tags, notes, settings and jobs. Also CAPE's task database. | Yes |
| `tartarus_os-data` | The event index of each analysis (OpenSearch). | Yes. Re-ingest rebuilds it from CAPE's files; see [the data flow](../architecture.md#data-flow). |
| `tartarus_cape-storage` | CAPE's files for each analysis: logs, reports, screenshots, PCAPs and memory dumps. | Yes. This is the largest volume. |
| `tartarus_sample-store` | Your samples, stored zipped. | Yes |
| `tartarus_guest-images` | The guests: disks, snapshots, NVRAM and the guest registry. | Yes. Each guest takes about 22 GB. A rebuild takes about 16 minutes plus your time. |
| `tartarus_imports` | Uploaded PCAPs and memory images. | Yes |
| `tartarus_exports` | Generated exports and reports. | Optional |

Outside the volumes:

- `.env` holds the secrets. Keep a copy. The databases were created with its passwords.
- `data/iso/` holds your Windows ISO. Tartarus only reads it.
- `rules/sigma/custom/` holds your own Sigma rules.

You can list the volumes with `docker volume ls --filter name=tartarus_`.

## Backing up

The project does not ship a backup command. A simple approach is to stop the stack and copy each volume with a throwaway container. This is plain Docker, and Tartarus does not test it.

```bash
make down
mkdir -p backup
docker run --rm -v tartarus_pg-data:/data -v "$PWD/backup":/backup alpine \
  tar czf /backup/tartarus_pg-data.tar.gz -C /data .
```

Repeat the `docker run` line for each volume, changing the volume and file names. Then start the stack again with `make up`.

## How much disk each thing uses

| Item | Size | Notes |
|---|---|---|
| Windows ISO | about 5 GB | Stays in `data/iso/`. |
| Each guest | about 22 GB | About 17 to 18 GB of disk and 3 GB of memory image for Windows 11. Up to five guests. |
| Memory dump | about the guest's RAM, for example 4 GB for a 4 GB guest | Only with **FULL MEMORY DUMP** on. Deleted after the findings unless you keep it. |
| An ordinary analysis | not given in the specs | Measure it yourself with `docker system df -v` before and after a run. |
| Docker images | about 3 GB for the `cape` image | These are images, not analysis data. |

The preflight check wants at least 200 GB free. `make preflight` prints the free space.

## The disk thresholds in Settings

**Settings** has two numbers, `DISK WARN (GB)` and `DISK BLOCK (GB)`. The defaults are 50 and 20, and the warning must be larger than the block.

Today they only control the memory dump check. Before a dump is accepted, Tartarus looks at the free space on the CAPE storage:

- below the larger of CAPE's own floor (about 48.8 GB) and the block value plus the guest's RAM, the dump is refused;
- below the warning value plus the guest's RAM, the dump is accepted with a warning.

The header does not show a disk gauge yet, and the Submit button is not disabled by disk space yet. Check free space with `df -h` and `docker system df -v`.

## Freeing space

- **Delete an analysis.** Use `[DELETE]` in its header, or the row menu on the Dashboard. The dialog shows how much it frees. This removes its CAPE task and files, its event index, its imports and its memory dump. The sample is removed only when no other analysis uses it. A running analysis cannot be deleted.
- **Delete a guest.** Use `[DELETE]` on its card on the **Guest VM** page. This frees about 22 GB. Analyses that used the guest keep their data.
- **Dumps you kept.** A kept memory dump stays until its analysis is deleted.
- **Old Docker images.** After rebuilds, Docker keeps old images. `docker image prune` removes the unused ones. This is a Docker command, not a Tartarus one.

## What `make down` does and does not delete

`make down` stops the containers and removes the containers and networks. It does not delete:

- analyses, samples, reports or the database;
- guests, their disks or their snapshots;
- `.env`, `data/iso/` or your rules.

`docker compose down -v` also deletes the volumes. That removes every analysis, sample and guest. Use it only when you want to start from nothing.
