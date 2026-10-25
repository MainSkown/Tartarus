# T3.0 notes (guest-to-guest isolation)

Done (all checks green, no stack or guest started):
- `<port isolated='yes'/>` in `guest/domain/domain.xml.tpl` and both golden renders; `test_render_domain.py` asserts it.
- `cape/guest_engine/isolation.py`: `isolate_interfaces` (text edit, idempotent) and `isolate_guest` (persistent domain
  plus every snapshot's own `<domain>` copy, because a memory-snapshot revert starts from that copy).
- `Engine._isolate_existing_guests` runs in `_start` after adoption: skips guests without a libvirt domain and running
  guests (picked up at the next service start), logs and goes on when libvirt refuses. Tests in `cape/tests/test_isolation.py`.
- `scripts/verify-isolation.sh GUEST_A GUEST_B` (+ `scripts/lib/isolation-probe.ps1`, `make verify-isolation GUESTS="a b"`),
  stub test `scripts/tests/test_verify_isolation.sh`.

Running: nothing.
Next (real stack, another agent): try the migration on a throwaway clone first (does `snapshot-create --redefine --current`
accept the edited snapshot XML, does a revert re-apply the flag), then the four guests, then the script on two guests (exit 0),
then `bridge link set dev vnetN isolated off` (exit 1). Commands are in the header of the script.
