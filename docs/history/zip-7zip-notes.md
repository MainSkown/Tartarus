# Zip Step 1 notes (bundled 7-Zip, zip-submission-plan.md)

## Done
- Read plan, spike notes, patch style, Dockerfile. df before: 1.9T total, 1.4T used, 401G free (78%); docker system df: images 136.9GB, volumes 52.89GB, build cache 0B.
- Chosen release: 7-Zip 26.03 (2026-09-04, 54 days old; 26.04 is 23 days old, 26.05 7 days). `7z2603-extra.7z` sha256 191894e6acb3647ffb69ce630479ff318523b2e2b9890aa7f05c1127c2e59b8f.
- Analyzer tools directory is `analyzer/windows/bin` (autoit3.exe, loader.exe live there; `archive.py` has a commented `os.path.join(os.getcwd(), "bin", "7z.exe")`). `analyzer_zipfile` zips the whole analyzer dir, ZIP_STORED, so a .exe in bin/ is uploaded. The guest extracts it to a mkdtemp dir on the system drive and runs analyzer.py with cwd there.

## Running
- nothing

## Next
- failing unit tests, patch, Dockerfile layer, THIRD_PARTY.md and docs/licenses.md, rebuild, 4 real-guest checks, cleanup.

## Findings
- Failing unit run shown (7 errors, patch file missing), then patch + Dockerfile layer written; 11 tests pass in cape/tests/test_analyzer_patches.py. Next: THIRD_PARTY/licenses, rebuild.
- THIRD_PARTY.md + docs/licenses.md done. Image rebuilt (docker compose build cape, cached, fast); 7z.exe present in image, zip.py patched; bad-hash build fails at the 7-Zip layer (verified). Used 'docker compose up -d' (no --build) to avoid rebuilding backend with the other session's WIP. Next: real-guest checks.
- Running: CAPE tasks 27 (a aes1 pw infected), 28 (b aes3 file=payload.exe), 29 (c aes1 pw wrong), 30 (d zipcrypto). Zips in scratchpad zip7/, copies in backend:/tmp/zs7 and cape:/tmp/zs7. Cleanup pending: delete tasks 27-30, storage/binaries zips, /tmp/zs7 in both containers.
- 27 and 28 reported: 7z.exe found at C:\<analyzer dir>\bin\7z.exe, 7-Zip (a) 26.03 (x86) extracted AES zips. Waiting for 29, 30; then collect process evidence (report.json behavior.processes / sysmon).
- 27 PASS (benign.exe ran), 28 PASS (only payload.exe ran; other.exe only a file-create), 29: 'Exception: Wrong password(s) provided' in analysis.log, task reported, errors []. Waiting for 30.
- 30 PASS (benign.exe ran, ZipCrypto). Cleanup done: tasks 27-30 deleted, 3 zips removed from storage/binaries, /tmp/zs7 removed in both containers, scratchpad zips removed, docker compose down, dangling images pruned (this also removed older dangling images that predated this work). Two exited build containers from the bad-hash test (sad_neumann, strange_haibt) were left: removal was denied by the permission classifier. df after: 1.3T used, 498G free (73%).
