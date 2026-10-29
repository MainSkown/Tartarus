# Plan: detonation from a password-protected zip

Implementation plan for [zip-submission.md](zip-submission.md). It was written from reading the spec, the
submit path and CAPE's own `zip` package in the `tartarus-cape` image. **Nothing has been run yet**: every
finding below is from reading code, and Step 0 checks them on a real guest.

## Findings that change the spec

| # | Finding | Effect |
|---|---|---|
| 1 | CAPE's option names are confirmed: `password` and `file` (`analyzer/windows/lib/common/constants.py`). The package's default password is already `infected`. | Open question "CAPE option names" is closed. |
| 2 | **Every AES zip fails today** (confirmed by the Step 0 spike, CAPE tasks 22-24). Python `zipfile` cannot read AES and the guest has no 7-Zip (the manifest fetches Python, Pillow and Sysmon). *Mechanism corrected by the spike:* `NotImplementedError` is a `RuntimeError`, so `extract_zip` catches it and `Zip.start()` already falls back to 7-Zip; the crash is `Unable to find any 7z.exe executable`. CAPE still ends the task as `reported`, with no `errors` recorded and nothing run. | Most shared sample zips are AES, so a guest-side change is needed (Step 1): a `7z.exe` the lookup can find. No analyzer logic needs to change. |
| 3 | CAPE splits the option string on `,` and strips whitespace from values (`lib/cuckoo/common/config.py: parse_options`). A password or entry name with a comma, or with leading or trailing spaces, cannot be passed. | Reject these in the API. The member list marks such members `unsupported`, the same way as `unsafe`. |
| 4 | `AnalysisRead.options` is returned verbatim by the API. A password stored in `AnalysisOptions` would be returned on every GET. | The spec's "never returned by API" needs an explicit strip in the read schema. The password stays in the DB, because the runner uploads later from the queue. |
| 5 | With `file=` set, `zip.py` skips `upload_extracted_files`: the entry file is absent from `report.json`, `files/` and `files.json` (spike, task 26). Without `file=` it is listed under `dropped`, but with every interesting member and no sign of which one ran. Sysmon event 1 carries `Hashes: SHA256=...` with image path `%TEMP%\<member>` in both modes, but `backend/app/ingest/sysmon_mapping.py` (`_process_created`) drops the hash. | The entry SHA256 is not a report field anywhere. Sourcing it needs a decision (see Decisions, item 4). |
| 6 | `backend/app/samples/store.py` needs no change: the store wraps the user's zip in its own one-member AES zip, so `_decrypt` still sees one member. | Remove it from the spec's "Relevant code". |
| 7 | The archive name and the entry name fit in `analysis.filename` and `analysis.options`. | No DB migration. |
| 8 | **No usable wrong-password signal after submission** (spike, tasks 24-25). The only distinguishing line is a DEBUG `Password ... was unsuccessful` in the guest's `analysis.log`, and only for ZipCrypto. `Zip.start()` re-raises only when `"Bad password for file"` is in `repr(e)`, which `extract_zip` has already rewritten, so the 7-Zip fallback runs and the final error is the missing `7z.exe`. The task is `reported`, `errors` empty. | Check the password before the run: in the dialog (member list, Step 2) and again at submission (Step 4). |
| 9 | CAPE keeps the uploaded zip in `storage/binaries/<sha256>` after `tasks/delete`. | A cleanup that wants no trace on the CAPE side must remove that file itself. |

## Steps

Each step follows the [rules](../contributing/the-rules.md): test first, self-documenting code, no
duplication. Model tiers follow rule 5 (never Opus; pass `model` explicitly).

### Step 0: spike on a real guest

**Status: done.** Evidence in [../history/zip-spike-notes.md](../history/zip-spike-notes.md); the findings
above already include its results.

**Tier:** extreme (Sonnet, with a notes file listing done, running and next; I re-run its checks and read
its diff).

Detonate the benign self-test sample from four zips:

1. ZipCrypto, one member.
2. AES, one member.
3. AES, three members, with `file=` naming one.
4. AES, wrong password.

Each case ends in a check that can fail. Record:

- the exact error text that reaches the Tartarus analysis on a wrong password;
- where the entry file's SHA256 appears: Sysmon process-create hashes (already ingested), the CAPE report,
  or nowhere (then the patch of Step 1 must upload it).

Write the findings to `docs/history/`. Delete the throwaway guest and analyses afterwards.

### Step 1: AES in the guest

**Status: done, uncommitted.** 7-Zip 26.03 (`7z2603-extra.7z`, sha256 pinned in `cape/Dockerfile`) is
installed as `analyzer/windows/bin/7z.exe`; `cape/patches/zip-bundled-7zip.py` adds its path. Real-guest
checks passed: AES one member (task 27), AES three members with `file=` (28, only the chosen member ran),
AES wrong password (29, `Wrong password(s) provided` in `analysis.log` only; the task is still `reported`),
ZipCrypto regression (30). CAPE's first `7z x -p` attempt with an empty password always logs `ERROR: Wrong
password`, also on success, so that line alone is not a failure signal. Notes:
[../history/zip-7zip-notes.md](../history/zip-7zip-notes.md).

**Tier:** Sonnet. Runs in parallel with Step 2.

- Ship a pinned standalone 7-Zip console build inside the analyzer directory, **named `7z.exe`**:
  CAPE's lookup (`get_path_app_in_path`) matches the substring `7z.exe` in each path of `Zip.PATHS`, so a
  file called `7za.exe` would not be found. The Dockerfile downloads it, checks its sha256 and unpacks it
  with the image's own `7z`.
- Add `cape/patches/zip-bundled-7zip.py`, in the style of the existing patches (anchor must match exactly
  once, otherwise the image build fails). It adds the bundled path to `Zip.PATHS` in `zip.py`. The
  fallback logic itself is untouched (the spike showed it already runs).
- The analyzer is uploaded for every task, so this needs **no guest rebuild** and leaves existing
  snapshots untouched, as the other analyzer patches do.
- Test first: extend `cape/tests/test_analyzer_patches.py` ("applies once", "fails if the anchor moved").
- Update `THIRD_PARTY.md` for 7-Zip (LGPL), with the pinned hash.
- Real-guest check on an image built from the Dockerfile: the AES one-member zip runs, the three-member
  zip with `file=` runs the chosen member, and a wrong password shows 7-Zip's `Wrong password(s)
  provided` in `analysis.log`.

### Step 2: archive reader module

**Status: done, uncommitted** (`backend/app/samples/archive.py`, 69 tests). `password_ok` is `None` both
when nothing is encrypted and when every encrypted member is unsafe.

**Tier:** Sonnet, because it parses untrusted input on the host. Runs in parallel with Step 1.

New `backend/app/samples/archive.py` with `read_members(path, password) -> listing`:

- The central-directory size is checked from the end-of-central-directory record **before** it is parsed.
- At most 1000 members; a cap on the total declared uncompressed size (proposed: 2 GiB).
- Members are flagged `unsafe` (`..`, absolute path, drive letter, NUL, backslash escape) or `unsupported`
  (comma, leading or trailing whitespace). Neither can be chosen.
- Password check: `pyzipper` verifies the AES password verifier or the ZipCrypto check byte, so the result
  carries `password_ok`. This reads the member's encryption header (about 20 bytes) and decrypts or
  extracts nothing. The spec's "never touches member data" should be reworded to "never decrypts or
  extracts".
- Unit tests only, with generated zips. The standard library cannot write ZipCrypto, so commit a tiny
  binary fixture for it.

### Step 3: endpoint `POST /analyses/archive-members`

**Status: done, uncommitted** (operation id `analyses_archive_members`; the capped upload copy is now one
shared function, `copy_capped` in `samples/store.py`). The frontend client is regenerated with Step 5.
`backend/app/imports/upload.py` still has its own near-identical chunk loop, which could move onto
`copy_capped` later.

**Tier:** Haiku, on top of the Step 2 module.

- Streams the upload to a temp file (not the sample store), reads it, deletes it.
- Takes the zip as multipart `file` and the password as a form field. Returns `[{name, size, encrypted,
  unsafe, unsupported}]` plus `password_ok`; 422 with the reason otherwise.
- Register it in the upload-route loop in `backend/app/api/analyses.py` with `sample_limit`.
- Regenerate the OpenAPI client.

### Step 4: submission

**Tier:** Sonnet.

- `AnalysisOptions`: add `archive_password` and `archive_entry`. They must come together, have a length
  cap, and follow the comma and whitespace rules of finding 3. They force `package="zip"`, and the stored
  file must start with `PK`.
- `AnalysisSubmitter`: check that the entry is a safe, supported member inside the existing try block, which
  already discards the stored sample on failure.
- One `_archive_options()` builder merges `password=` and `file=` with `interactive.options` in
  `AnalysisRunner._upload`.
- Submission re-checks the password with `read_archive` and answers 422 when `password_ok` is `False`
  (finding 8: CAPE gives no usable signal afterwards). `None` (nothing encrypted) passes.
- `AnalysisRead`: drop `archive_password` from `options`.
- Tests: the 422 cases, a wrong password, and a check that the password appears in no log line and no API
  response.

### Step 5: frontend

**Tier:** Sonnet. The composable can start once the Step 3 client is generated.

- `useArchiveMembers` composable, tested with vitest: loading, error, one member preselected, several
  members with none preselected.
- Put the archive fields in a new `SubmitArchiveFields.vue` instead of growing the 748-line
  `SubmitDialog.vue`: the password input (prefilled `infected`) and the "File to run" list.
- Lock the package picker to `zip`, with a hint saying why.
- Block submit while loading, on error, or while no entry is chosen.
- All strings through message keys ([how](../contributing/adding-a-message-key.md)).

### Step 6: report and analysis header

**Status: done, uncommitted.** Decision 4 was settled as option A. Sysmon event 1 carries
`process.hash.sha256` (one field catalog entry, `backend/app/search/fields.py`, and a row in
`docs/specs/data-model.md`). The final ingest computes `summary.sample.entry_sha256` (`ReportIngester`,
`backend/app/analyses/entry_hash.py`): the hash of the earliest process whose image is
`...\Temp\<entry>`. It is null for entries that run through another program, and when the Sysmon export is
missing. The analysis header and the exported report show the archive and the file run with both hashes;
the header was reviewed and approved as an Artifact.

**Tier:** split in three: backend ingest (Sonnet), header (Sonnet, with screenshots), report (Haiku).

Show the archive name, the entry name and both SHA256s.

### Step 7: visual review

Done by me, per rule 4.

Screenshots of the submit dialog: loading, one member, three members with none chosen, wrong password, not
a zip, an unsafe member greyed out, long member names, narrow window. I check them myself first, then
publish one Artifact for the dialog and a separate one for the analysis header. Comments are addressed on the
same Artifact URL.

### Step 7 and Step 8: status

**Step 7 done:** the submit dialog and the analysis header were each published as an Artifact and approved.

**Step 8 done, uncommitted:** `scripts/lib/e2e-zip.sh` (run with `E2E_ONLY=zip scripts/e2e.sh`) passes on a
real guest: z1 member list and password check, z2 submission with no password in any response, z3 only the
chosen entry ran, z4 and z5 refusals that leave nothing behind, z6 no password in the backend log, z7 the
entry's SHA256 equals the file inside the zip and the HTML report shows both hashes, z8 the same zip under a
`.bin` name runs. Docs and `CHANGELOG.md` are updated.

### Step 8: proof and docs

**Tier:** Haiku.

- A real-guest end-to-end proof next to the existing ones: an AES zip with three files, running the chosen
  one.
- Docs listed in the spec, and `CHANGELOG.md`.

## Order

0 → (1 ∥ 2) → (3, 4) → 5 → 6 → 7 → 8

## Decisions needed

1. **AES fix.** Recommended: bundle `7za.exe` in the analyzer through a patch. The alternative, installing
   7-Zip in the guest build, means rebuilding every guest and still needs the same patch.
2. **Uploading the zip twice** (member list, then submit). Recommended: accept it for v1. The password check
   needs the member data, so sending only the file's tail would save nothing.
3. **Caps:** 1000 members and 2 GiB declared total, as proposed above.
4. **Where the entry file's SHA256 comes from** (new, from the spike). Recommended: map Sysmon event 1's
   `Hashes` to `process.hash.sha256` in `sysmon_mapping.py` and take the hash of the first process whose
   image is `%TEMP%\<entry>`. It uses data the guest already records, but it changes ingestion for every
   analysis and needs a data-model spec check. The alternative is a second analyzer patch that uploads the
   entry file as `files/<sha>`, which would list the sample among the dropped files.

## Spec edits this plan implies

- "Relevant code": remove `backend/app/samples/store.py`.
- Backend: the member list also returns `password_ok`; members can be `unsupported`.
- Behavior details: "never decrypts or extracts" in place of "never touches member data".
- Data: no new columns; the archive and entry names live in `filename` and `options`.
- Open questions: close "CAPE option names"; keep "AES zips", "Wrong-password detection" and "Entry hashes"
  until Step 0.
