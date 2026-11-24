# Adding a fake local network preset

A preset is a set of fake hosts that a sample can find on the fake local network
([feature](../features/fake-lan.md), [guide](../guide/fake-lan.md)). A preset is data, not code: one JSON
file, validated each time the control service reads the presets, and the analyst can pick it in the submit dialog
without any change to the app.

Read [the rules](the-rules.md) first. A preset is test-first like any other change: write the file, run
the test, and only then think about the hosts.

## The file

Put the file in `guest/lan-presets/<id>.json`. The `id` is the file name without `.json`. A file whose
name starts with a dot is ignored.

```json
{
  "id": "small-office",
  "name": "Small office",
  "description": "A domain controller, a file server and a workstation on one corp.local network.",
  "domain": "corp.local",
  "hosts": [
    {
      "fqdn": "dc01.corp.local",
      "host_offset": 200,
      "role": "domain-controller",
      "os_banner": "Windows Server 2019 Standard 10.0.17763",
      "accounts": [{"user": "Administrator", "password": "Password1"}],
      "services": [
        {"kind": "smb", "port": 445},
        {"kind": "ldap", "port": 389},
        {"kind": "rdp", "port": 3389}
      ]
    },
    {
      "fqdn": "printer01.corp.local",
      "host_offset": 201,
      "role": "printer",
      "os_banner": "Embedded Linux 4.19",
      "services": [
        {"kind": "ssh", "port": 22, "options": {"banner": "SSH-2.0-OpenSSH_8.0"}}
      ]
    }
  ]
}
```

The shipped presets are the examples: `guest/lan-presets/small-office.json`, `flat-home.json` and
`domain-servers.json`.

### Fields

| Field | Required | Rule |
|---|---|---|
| `id` | yes | Lower case, starts with a letter, 2 to 32 characters of letters, digits and hyphens; must equal the file name |
| `name`, `description` | yes | Non-empty text |
| `domain` | yes | A DNS name under the same rules as an FQDN (below). Every host's FQDN ends in `.<domain>` |
| `hosts` | yes | A non-empty list |
| `hosts[].fqdn` | yes | At least two labels; lower case; only `a-z`, `0-9` and hyphens in each label, none starting or ending with a hyphen; no underscore. The underscore and single-label rules exist because INetSim's `dns_static` refuses them and would then stop every INetSim service |
| `hosts[].host_offset` | yes | An integer from **200 to 247**, the fake LAN block. The address is the offset in the guest subnet (`GUEST_SUBNET`, which must be a `/24`) |
| `hosts[].role` | yes | Lower case, the same pattern as `id`. Shown in the GUI |
| `hosts[].os_banner` | yes | Non-empty text. The MSSQL service answers its version query with it |
| `hosts[].accounts` | no | A list of `{user, password}`. Each `user` is listed once per host. A host that serves `smb` needs at least one |
| `hosts[].services` | yes | A non-empty list of `{kind, port, options}` |
| `services[].kind` | yes | One of `smb`, `rdp`, `winrm`, `ssh`, `ldap`, `mssql` |
| `services[].port` | yes | 1 to 65535; one service per port on a host |
| `services[].options` | no | `smb`: `shares`, a list of share names (`A-Za-z0-9`, space, `_`, `.`, `$` and `-`; up to 80 characters). `ADMIN$`, `C$` and `IPC$` are implied and must not be listed. `ssh`: `banner`, printable ASCII up to 200 characters |

No other key is accepted: an unknown field name fails the load. The loader is
`cape/guest_engine/lan_presets.py`; read it when a rule here and the error you get disagree.

### Across presets

Every FQDN and every address must be unique across **all** presets, not only within one file. Two
presets may not share a block offset, and the loader says which file and which host clash. The blocks
are disjoint so that one shared daemon can answer by address, and so that two analyses on two guests
cannot clash (plan, Decision 2). Pick offsets no other preset uses, and check the existing files first.

### Accounts

An account in a preset is a well-known weak one, such as `Administrator` with `Password1`. It is there
because Windows' file-sharing client signs its traffic with a key made from the password, so a host that
accepts any password cannot be used by it (plan, S5). Never put a real password in a preset. A preset is
committed to the repository and is copied into the `cape` image.

## Where the preset goes into the app

- `guest/lan-presets/` is copied into the `cape` image (`COPY` in `cape/Dockerfile`). The control service
  reads it from `GUEST_LAN_PRESETS_DIR`, which defaults to `/usr/local/lib/tartarus/lan-presets`.
  A new or edited preset reaches the stack when you rebuild the `cape` image (`make up` does).
- `GET /api/lan-presets` lists a preset once the control service loads it. The submit dialog reads that
  list, so the new preset appears there with no frontend change.
- The control service gives the chosen preset's hosts to the fake-host daemon (`lan-sim`) with each
  session. The `dns_static` entries for every preset's names come from the same files through
  `cape/bin/lan_dns.py`.

## How to test it

The validator and the shipped presets are tested in `cape/tests/test_lan_presets.py`:

```bash
cd cape && uv run --no-project --with pytest pytest tests/test_lan_presets.py
```

`uv run --no-project --with pytest` is the same way `make test-cape` runs the `cape` tests. The shipped
presets are checked by the same test, so a preset you add is checked as soon as it is in
`guest/lan-presets/`. Add a test for each rule your preset relies on, written before the preset. The
existing tests cover a duplicate FQDN across presets, an offset outside the block, an unknown service kind
and an SMB host without an account, each with a precise message. The DNS lines are tested in
`cape/tests/test_lan_dns.py`.

To see the preset run, start the stack, open the submit dialog, switch on **SIMULATE LOCAL NETWORK** and
choose it. Then check the Network tab and the Summary, as the [guide](../guide/fake-lan.md) describes.

## Checklist

- [ ] The file is `guest/lan-presets/<id>.json`, and `id` equals the file name.
- [ ] Every host's `host_offset` is between 200 and 247, and no other preset uses it.
- [ ] Every FQDN is unique, has at least two labels, is lower case, has no underscore and ends with the preset's `domain`.
- [ ] Every host that serves `smb` has at least one account, and every account is a well-known weak one.
- [ ] Every `kind` is one of the six known kinds, and no port is used twice on one host.
- [ ] No field is unknown to the loader.
- [ ] `cd cape && uv run --no-project --with pytest pytest tests/test_lan_presets.py` passes, and a test covers each rule the preset relies on.
- [ ] The `cape` image is rebuilt, and the preset shows in `GET /api/lan-presets`.
- [ ] The preset is listed in [the guide](../guide/fake-lan.md) and, if it adds a kind of host the spec does not describe, in [the feature spec](../features/fake-lan.md).
