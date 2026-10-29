# Detonation from a password-protected zip

## Summary
Malware samples are shared as password-protected zips. Today Tartarus accepts a single file and has no way to pass an archive password, so the analyst would have to unpack the sample on their own machine first. This feature lets the analyst drop the zip into the submit dialog, give the password, pick the entry file, and have the archive unpacked **inside the guest VM**. The sample is never unpacked on the analyst's computer or in the backend.

**Status:** the dialog, the member list, the submission checks, the unpacking in the guest, a pinned 7-Zip for AES zips, and the archive and entry SHA256s in the analysis header and the exported report are built, and proved on a real guest by `E2E_ONLY=zip scripts/e2e.sh` (checks z1 to z8). See the [plan](zip-submission-plan.md).

## Goals
- Submit a password-protected zip without unpacking it on the analyst's machine or on the Tartarus host.
- Choose which archive member is detonated when the zip holds several files.
- Record both the zip's identity and the detonated file's identity in the report.

## Non-goals
- Unpacking on the host or in a separate unpack container (decided: guest-side only).
- Formats other than zip (7z, rar, tar, gz), and zips nested inside zips.
- URL submission (still a v1 non-goal).
- Trying a list of common passwords automatically.
- Submitting several members of one archive as separate analyses.

## Changes

### UI / frontend
- [x] `SubmitDialog.vue`: when the dropped file is a zip (name ends in `.zip` or starts with the `PK` signature), show an "Archive password" field prefilled with `infected`.
- [x] After a zip is dropped, call the member-list endpoint and show the member names (and sizes) as a pick list titled "File to run". One member: preselected. Several: the user must choose one, no default.
- [x] While the list loads, show a loading state; on error (not a valid zip, too many members, zip bomb limits) show the message from the API under the drop zone and block submit.
- [x] When a zip is dropped, set the package to `zip` and lock the package picker, with a hint saying why.
- [x] Analysis detail header and report: show the archive name, the entry file name, and both SHA256s (see Behavior details). The entry's SHA256 is "not recorded" when the entry started no process of its own (a DLL, script or batch file runs through another program) or the guest's Sysmon log is missing.
- [x] All new strings go through the message-key mechanism (see `docs/contributing/adding-a-message-key.md`).

### Backend / API
- [x] New endpoint `POST /api/analyses/archive-members`: takes the zip (multipart `file`) and the password (form field `password`), reads only the central directory, and returns `[{name, size, encrypted, unsafe, unsupported}]` plus `password_ok`. It never decrypts or extracts anything.
- [x] Member-list limits: at most 1000 members, and a total declared uncompressed size cap (value in Open questions); member names containing `..`, absolute paths or NUL are reported but marked `unsafe: true` and cannot be chosen; names with a comma or edge whitespace are marked `unsupported` and cannot be chosen either.
- [x] `AnalysisOptions` (`backend/app/schemas/analysis_requests.py`): add `archive_password: str | None` (max 256 chars) and `archive_entry: str | None`. Both are valid only together with a zip upload; `extra="forbid"` stays.
- [x] Submission validates that `archive_entry` is one of the zip's members and is not unsafe; otherwise 422 with a precise message.
- [x] `AnalysisRunner._upload` / task fields: for a zip analysis send package `zip` and build the CAPE `options` string with `password=` and `file=` (option names to be verified against the installed CAPE, see Open questions).
- [x] The multipart filename sent to CAPE is the upload's own name. No `.zip` suffix is forced: the `zip` package opens the file by content, and a real-guest run of the same AES zip named `e2e-archive.bin` ran the chosen entry (`E2E_ONLY=zip scripts/e2e.sh`, check z8).
- [x] The password is never logged and never returned by the API.

### Data / configuration
- [x] `Analysis` stores the archive name (in `filename`) and the entry name (in `options`), with no new columns; the zip's SHA256 stays the `Sample` identity.
- [x] Entry file hashes are recorded from the guest's side after the analysis, and added to the report. CAPE's report does not carry the entry's hash when `file=` is set, so the source is Sysmon's process-creation event (`process.hash.sha256`): the final ingest takes the hash of the earliest process started from `%TEMP%\<entry>` and stores it at `summary.sample.entry_sha256`.

### Other
- [x] Docs: remove "URL and archive submission" archive part from the non-goals in `docs/features/tartarus-v1.md`, `docs/overview.md`, `SECURITY.md`; add a section to `docs/guide/first-analysis.md` and `docs/guide/safety.md` (the sample is unpacked in the guest only).
- [x] `CHANGELOG.md` entry.

## Behavior details
- The password defaults to `infected`, the industry convention and the password Tartarus already uses for its own downloads.
- The stored sample is still the zip, kept in the existing AES store as today, so `Sample` has one row per zip SHA256.
- The member list is read by the backend from the central directory only. Reading it parses untrusted metadata on the host, so the parser must be strict about limits and must not decrypt or extract member data.
- The password is sent to CAPE as a task option, so it is stored in CAPE's task record. It is also kept in the Tartarus database, because the runner uploads from the queue, and the API never returns it. That is accepted: the password is shared with the sample publicly and is not a secret.
- If the user picks no entry because the archive holds several files, the submit button stays disabled.

## Edge cases
- Not a zip, or a corrupt central directory → member-list endpoint returns 422, dialog shows the reason, submit blocked.
- Zip with no encrypted members → password field is shown but marked optional, and ignored.
- Wrong password → refused before queuing: the dialog says the password does not open the archive, and the API answers `422` at `options.archive_password`. CAPE gives no usable signal after submission (see Open questions), so the check happens first.
- AES-encrypted zips (what MalwareBazaar-style archives use) versus ZipCrypto → must work, see Open questions.
- Zip over 512 MiB → the existing 413 limit applies.
- A member named `../x` or with an absolute path → shown as unsafe, not selectable.
- Entry file is itself a zip, 7z or similar → detonated as the inner file's type; no further unpacking.

## Acceptance criteria
- When I drop a password-protected zip with one executable in it, the dialog shows the password `infected` and the one member, preselected, and the analysis runs the executable without any file being unpacked on my machine or in the backend.
- When the zip holds three files, the dialog forces me to choose one, and the analysis runs the one I chose.
- When I type a wrong password, the dialog says the password does not open the archive, and no analysis is queued.
- The report shows the zip's SHA256 and the executable's SHA256. Pending: the report header is not built, and the entry's SHA256 is not recorded yet.
- A zip with a `../evil` member cannot be submitted with that member selected.
- No archive password appears in a backend log line or in the `options` of an analysis the API returns. It does appear in the guest's 7-Zip command line, so in the indexed events and in CAPE's report, which the Behavior details already accept as non-secret.

## Decisions
- Unpack in the guest via CAPE's `zip` package: it keeps the sample off the host entirely and is the smallest change.
- Password field prefilled with `infected`, no automatic guessing: guessing makes a wrong password indistinguishable from a corrupt archive.
- User picks the entry file in the dialog: real samples ship with side-loaded DLLs or configs.
- The member list is read in the backend (names only), not in the browser.
- The entry file's SHA256 is recorded too, besides the zip's.

## Open questions
- **AES zips.** Python's `zipfile` (which CAPE's zip package likely uses in the guest) cannot read AES-encrypted zips; most shared sample archives are AES. Must be tested on a real guest first. If unsupported, the fix is a guest-side change in the Tartarus analyzer (extract with `pyzipper` or 7-Zip in the guest), which is still guest-side and fits the decision.
  **Answered by the spike:** Python's `zipfile` fails on AES, and the guest had no 7-Zip, so every AES zip failed. The fix is a pinned 7-Zip console build in the analyzer's `bin` (`cape/patches/zip-bundled-7zip.py`). AES zips with one member, and with three members and `file=`, ran on a real guest, and a wrong AES password was reported by 7-Zip. ZipCrypto still works. See [the 7-Zip notes](../history/zip-7zip-notes.md).
- **CAPE option names.** `password`, `file` (and `arguments`) for the zip package are from memory; the CAPE source is not in the repo and is installed in the image at `/opt/CAPEv2`. Verify there.
  **Answered:** `password` and `file` are the names CAPE's analyzer reads (`lib/common/constants.py`), and the task's options string carried `password=...,file=...` on the wire. CAPE splits options on commas and strips whitespace, which is why the API refuses those in the password and the entry name.
- **Wrong-password detection.** Does CAPE report a distinct error? If not, can the member-list step verify the password cheaply (AES password-verification value / ZipCrypto check byte) without extracting?
  Spike: no distinct error after submission, only a line in the guest's `analysis.log` for ZipCrypto (see [the spike notes](../history/zip-spike-notes.md)). The member-list step does check the password, and submission checks it again.
- **Upload twice.** The member list and the submit both send the zip (up to 512 MiB). Accept that, or have the dialog send only the file's tail (end-of-central-directory plus central directory) to the list endpoint?
- **Caps.** Values for max declared uncompressed size and max member count.
- **Entry hashes.** Closed. No field of CAPE's report carries the inner file's hash when `file=` is set (spike, task 26). Sysmon's process-creation event does, for an entry that is an executable; the other entry types have no hash (see the checklist above).

## Relevant code
- `frontend/src/components/SubmitDialog.vue`, `frontend/src/services/submit-dialog.ts`, `frontend/src/services/routes.ts`
- `backend/app/api/analyses.py` (`create`, `parse_options`), `backend/app/api/upload_limit.py`
- `backend/app/schemas/analysis_requests.py` (`AnalysisOptions`)
- `backend/app/analyses/submission.py` (`AnalysisSubmitter.submit_with_warnings`), `backend/app/analyses/runner.py` (`_upload`, around lines 365-384)
- `backend/app/cape/client.py` (`create_file_task`)
- `guest/profiles/windows/profile.json` (`zip` listed in packages, around line 323)
- `docs/features/tartarus-v1.md:38`, `docs/overview.md:87`, `SECURITY.md`, `docs/history/finish-line.md:49`
