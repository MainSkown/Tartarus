# F1: clean-host install test (2026-10-26)

Run on the development machine, not a second host: every Tartarus container, image, network and volume was removed
(`make down`, the seven `tartarus_*` volumes, the `tartarus-*` images), then a fresh `git clone` of HEAD (`bc78427`) in
another folder, following only the README. The host prerequisites (kernel modules, `vm.max_map_count`, Docker, KVM)
were already in place here, so this test does not prove them; `make preflight` is the check for those.

| Step | Result |
|---|---|
| `make init-env` | `.env` written, mode 600, four 64-character secrets |
| `make preflight` | every check `[ OK ]` (`uv` and `node` are warnings only on a host that does not run the tests) |
| `make up` | 4 min 14 s from nothing, all five containers healthy, both guest firewall tables loaded |
| Empty stack | `GET /api/guests` is `[]`, the guest health dot says "no guest has been built", `GET /api/version` is 1.0.0 |
| ISO in `data/iso` | `GET /api/guests/media` lists `Win11_25H2_Polish_x64_v2.iso` with its 10 editions |
| Guest build through `POST /api/guests/build` (Pro, defaults: Defender on, Sysmon on) | `ready` in about 17 minutes, self-test "all checks passed" |
| First analysis (`inetsim`) | done in under two minutes, 679 events, score 6.0 |
| Views and report | processes, network, detections, IOCs and artifacts answered 200; the PDF report job finished and the file holds the sample |

## Gaps found

- The README and the install guide said the first `make up` takes "a few minutes", then "20 minutes or more". Measured: about 4 minutes.
  Both now say about 5 minutes.

## Not covered

- A second machine: kernel-module and sysctl prerequisites, a different Docker version, no pre-existing KVM setup.
- The wizard in a browser: the build was started through the same API the wizard calls (`make e2e` drives the wizard in a browser).
