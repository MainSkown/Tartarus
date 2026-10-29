# Zip spike notes (Step 0 of zip-submission-plan.md)

Setup: stack up with `make up`. Sample = `guest/profiles/windows/selftest/benign.c` built with the mingw container
(`scripts/lib/benign-sample.sh`), sha256 `4b322b00346035d752e2cced1d6936d151c7edc341004c3aaa36ac4025aeec37`.
Zips built with 7z in the cape image (`-mem=ZipCrypto` / `-mem=AES256`, password `infected`). Submitted straight to
CAPE (`POST /apiv2/tasks/create/file/` from the backend container, with its `CAPE_API_TOKEN`): machine `win`, route
`inetsim`, timeout 180, package `zip`. Sysmon and the CAPE report were read from the analysis directory of each
task; these direct CAPE tasks are not ingested by Tartarus, so OpenSearch was not queried.

## Done
- Case 1 (ZipCrypto, 1 member, `password=infected`): task 21, reported, sample ran.
- Case 2 (AES-256, 1 member, `password=infected`): task 22, reported, nothing ran (7z.exe missing).
- Case 3 (AES-256, 3 members, `password=infected,file=payload.exe`): task 23, reported, nothing ran (same as case 2).
- Case 4 (AES-256, `password=wrong`): task 24, reported, nothing ran (same as case 2: the password is never tried).
- Case 4b, added (ZipCrypto, `password=wrong`): task 25, reported, nothing ran (7z.exe missing).
- Case 3b, added (ZipCrypto, 3 members, `password=infected,file=payload.exe`): task 26, reported, `payload.exe` ran.
  Cases 4b and 3b exist because AES fails before the password is checked and before `file=` is used.
- Cleanup: tasks 21 to 26 deleted through `GET /apiv2/tasks/delete/<id>/` (each then answers "Task not found in database"),
  the five zips CAPE kept in `storage/binaries` removed, `/tmp/zs` removed in `cape` and `backend`, the zips and the sample
  removed from the scratchpad, `make down` run (volumes kept, `win` shut off). No Tartarus analysis was created.

## Running
- nothing

## Next
- nothing for the spike; the planner decides Step 1 and 2.

## Findings

### Outcome per case

| Case | Task | CAPE status | Ran? | Final error |
|---|---|---|---|---|
| 1 ZipCrypto, 1 member | 21 | reported | yes, `benign.exe` pid 9580 | none |
| 2 AES-256, 1 member | 22 | reported | no | `Unable to find any 7z.exe executable` |
| 3 AES-256, 3 members, `file=payload.exe` | 23 | reported | no, no member ran | same |
| 4 AES-256, `password=wrong` | 24 | reported | no | same, password never tried |
| 4b ZipCrypto, `password=wrong` (extra) | 25 | reported | no | same |
| 3b ZipCrypto, 3 members, `file=payload.exe` (extra) | 26 | reported | yes, only `payload.exe` (pid 332) | none |

In every failing case the CAPE task is `reported`, the task `errors` list and the report's `debug.errors` are empty
(`GET tasks/view/<id>/` and `report.json`), `malscore` is low (0.3) and `behavior.processes` is empty. The host
`cuckoo.log` shows `WARNING: Task #22: Analysis caught an exception` (text: `You probably submitted the job with wrong
package`) and then `Completed analysis successfully.`

### Evidence: AES (cases 2, 3, 4), from `analysis.log` (`report.json` `debug.log`)

    [lib.common.zip_utils] DEBUG: Archive is encrypted, using default password value: infected
    [root] ERROR: You probably submitted the job with wrong package
    File "C:\Python311\Lib\zipfile.py", line 719, in _check_compression
        raise NotImplementedError("That compression method is not supported")
    NotImplementedError: That compression method is not supported
    During handling of the above exception, another exception occurred:   (second identical NotImplementedError, the "try twice")
    File "...\lib\common\zip_utils.py", line 212, in extract_zip
        raise CuckooPackageError("Unable to extract Zip file: %s", str(e)) from e
    lib.common.exceptions.CuckooPackageError: ('Unable to extract Zip file: %s', 'That compression method is not supported')
    During handling of the above exception, another exception occurred:
    File "...\modules\packages\zip.py", line 82, in start
        seven_zip_path = self.get_path_app_in_path("7z.exe")
    lib.common.exceptions.CuckooPackageError: Unable to find any 7z.exe executable
    lib.common.exceptions.CuckooError: The package "modules.packages.zip" start function raised an error: Unable to find any 7z.exe executable

Guest Python is `C:\Python311` (`Python path: C:\Python311`, tracebacks under `C:\Python311\Lib\zipfile.py`).

### Evidence: wrong password (cases 4 and 4b)

- Case 4 (AES, `password=wrong`) is byte-for-byte the case 2 failure: Python `zipfile` fails on the compression method
  before it ever looks at the password. There is no "wrong password" text anywhere in it.
- Case 4b (ZipCrypto, `password=wrong`) does reach the password check:

      [lib.common.zip_utils] DEBUG: Password 'b'wrong'' was unsuccessful in extracting the archive.
      [root] ERROR: You probably submitted the job with wrong package
      lib.common.exceptions.CuckooPackageError: ('Unable to extract password-protected Zip file with the password(s): %s', "[b'wrong']")
      During handling of the above exception, another exception occurred:
      lib.common.exceptions.CuckooPackageError: Unable to find any 7z.exe executable
      lib.common.exceptions.CuckooError: The package "modules.packages.zip" start function raised an error: Unable to find any 7z.exe executable

  `Zip.start()` re-raises only when `"Bad password for file" in repr(e)`. `extract_zip` swallows Python's "Bad password for
  file" into `password_fail` and raises a different `CuckooPackageError` (its text is "Unable to extract password-protected
  Zip file"), so the check never matches, the 7-Zip fallback runs, and the final error is again the missing `7z.exe`.
- Where it surfaces: only in the guest's `analysis.log` (also embedded as `report.json` `debug.log`, and the file
  `storage/analyses/<id>/analysis.log`), as free text in a traceback. The CAPE task status is `reported`, `errors` is empty,
  and `cuckoo.log` carries only the generic `You probably submitted the job with wrong package`.
- Plainly: a Tartarus analysis cannot read a distinct "wrong password" signal from CAPE today. The final error of a wrong
  password and of an AES archive (and of a missing 7z) are the same string. The only distinguishing line is the DEBUG
  `Password '...' was unsuccessful` in `analysis.log`, and only for ZipCrypto. With a working 7-Zip the final error would be
  `Exception("Wrong password(s) provided")`, which is not run here. So the plan's finding 8 holds: check the password when
  the dialog reads the member list (Step 2), and treat "no process ran, task reported" as the failure signal, with the
  `analysis.log` text as the message.

### Entry file sha256

For the cases that ran (1 with no `file=`, 3b with `file=payload.exe`); the entry hash is `4b322b00...eec37` in both.

| Place | Case 1 (no `file=`) | Case 3b (`file=` set) |
|---|---|---|
| `report.json` `target` | no, it is the zip (`a7b8690c...`, `3142ce7c...`) | no, the zip |
| `report.json` `dropped` | yes: `dropped[0]` name `benign.exe`, sha256, path `files/<sha>` | no: only `tartarus-benign.txt` |
| `report.json` `CAPE.payloads` | empty | empty |
| `report.json` `behavior.processes[*]` | no hash field (name and `module_path` only) | same |
| `report.json` `procdump` | sha256 of the dumped memory image `0b80d25b...`, not of the file | `477340ac...`, not the file |
| analysis dir `files/` and `files.json` | yes: `files/<sha>`, `metadata: "benign.exe"`, from `upload_extracted_files` | no: only `tartarus-benign.txt` |
| Sysmon (`sysmon/sysmon.xml`) EID 1 `Hashes` | yes, `SHA256=4B322B00...` | yes, `SHA256=4B322B00...`, image `...\Temp\payload.exe`, parent `explorer.exe` |
| `analysis.log` | `Uploading file ...benign.exe to files/<sha>` | no hash, only the path and pid |

- Case 3 proper (AES, `file=` set) could not show it: nothing ran. Case 3b is the stand-in and confirms the plan's
  finding 5: with `file=` set, `upload_extracted_files` is skipped, so the entry file is neither in `files/` nor in
  `report.json`.
- Sysmon EID 1 is the one place that carries the entry hash in both modes, as `Hashes: SHA256=<UPPERCASE>` (lowercase it
  to compare). Caveat from code, not from OpenSearch: `backend/app/ingest/sysmon_mapping.py` `_process_created` returns no
  `hash` section (only file events use `_sha256`), so the EID 1 `Hashes` field does not reach the index today. Using Sysmon
  means adding a `process.hash.sha256` mapping to that function; it also means correlating by the process image path or
  name (`...\Temp\<entry>`), since the guest path is `%TEMP%\<member name>`.
- Without `file=`, the hash is also in `dropped`, but with several interesting members CAPE runs all of them
  (`get_interesting_files`) and uploads every extracted file, so `dropped` lists them all and does not say which one ran.
- Nowhere in the report is the entry hash a first-class field.

### Prediction check (finding 2: AES crashes the package)

- Outcome CONFIRMED: an AES zip crashes the package in the real guest, nothing runs, and CAPE still reports the task as
  `reported` with no error recorded.
- Mechanism REFUTED in one detail: `NotImplementedError` does not escape. It is a subclass of `RuntimeError`, so
  `extract_zip`'s `except RuntimeError` catches it, retries once ("try twice"), and raises `CuckooPackageError("Unable to
  extract Zip file ...")`. That is a `CuckooPackageError`, so `Zip.start()` does fall back to 7-Zip. The crash is that
  fallback: `get_path_app_in_path("7z.exe")` raises `CuckooPackageError: Unable to find any 7z.exe executable`, which
  `Zip.start()` does not catch and the analyzer wraps in `CuckooError`. The guest has no 7-Zip (`PATHS` lists
  `ProgramFiles\7-Zip\7z.exe` and nothing else for 7z; the lookup failed).
- Consequence for Step 1: the plan's patch "fall back to 7-Zip on `NotImplementedError` too" is NOT needed, the fallback
  already triggers. What is missing is a 7-Zip the lookup can find. `get_path_app_in_path` (abstracts.py, read in the image)
  returns the first entry of `enum_paths()` (the package's `PATHS`, wildcards expanded) that is a file and whose path contains
  the substring `7z.exe` (case-insensitive). So a bundled `7za.exe` would NOT match (`7za.exe` does not contain `7z.exe`):
  ship it as `7z.exe`, and add its path to `Zip.PATHS` (the stock list only has `ProgramFiles\7-Zip\7z.exe`). Whether the
  lookup is reached for the standalone 7za command-line build (it handles zip, AES included) was not run.

### Other facts worth keeping

- CAPE option names confirmed on the wire: the task's options string came back as `password=infected,file=payload.exe,vnc_port=5900`
  (CAPE appends `vnc_port`).
- The CAPE API takes `package=zip` as a plain form field; `machine=win`, `route=inetsim`, `timeout=180` were accepted.
- ZipCrypto, no `file=`: the archive's single member is auto-run (`Missing file option, auto executing: ['benign.exe']`).
- Every case also ran Python's own "Archive is encrypted, using default password value: infected" line, even with
  `password=wrong`: that line only reports a default for an empty password and is not evidence of the password used.
- CAPE keeps the uploaded zip in `storage/binaries/<sha256>` after `tasks/delete`; a Tartarus cleanup that wants no trace
  of a sample on the CAPE side has to remove that file itself.
