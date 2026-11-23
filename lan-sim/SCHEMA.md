# lan-sim event log

One file per session, `logs/<session key>.jsonl` under the shared root (`/run/lan-sim`): one JSON
object per line, pure ASCII (non-ASCII text is `\uXXXX`-escaped), no newline inside a record. This is
the contract the backend's `lan-sim` normaliser reads (fake LAN plan, Step 7). The code that writes
it is `lan_sim/events.py` (the fields and their cleaning) and `lan_sim/session_log.py` (the caps).

The log has **no process id**: the daemon sees only a source address and port. The normaliser joins
`(src.port, dst.ip, dst.port)` with CAPE's flows and Sysmon EID 3 to find the process.

## Every string is untrusted

Everything a client sent (user, domain, secret, share, path, name, detail) has control characters,
format characters (bidi overrides, zero-width), line and paragraph separators and surrogates removed
before it is written (invalid UTF-8 becomes U+FFFD), and is cut to a cap with a final `U+2026` if it
was longer. Caps: `user`, `domain`, `share`, `name`, `operation` 256 characters; `path`, `detail`
1024; `secret` 4096. The text is not HTML-escaped: whoever renders it must escape it.

## Common fields

| Field | Type | Meaning |
|---|---|---|
| `time` | string | UTC, ISO 8601 with milliseconds and `Z`, from the daemon's clock |
| `type` | string | one of the seven types below |
| `host` | string | FQDN of the fake host (not on `session-end`) |
| `service` | string | service kind, e.g. `smb` (not on `session-end`) |
| `src` | `{ip, port}` | the guest's address and source port (only on the five connection events) |
| `dst` | `{ip, port}` | the fake host's address and the service port (same five) |

## Event types

### `login-attempt`

`user`, `domain`, `mechanism` (`ntlm`, `basic`, `password`, `publickey`, `sql`, `ldap-simple`),
`secret`, `success` (bool). `secret` is the NetNTLMv2 string in hashcat format, or the cleartext password
the client sent, or a key fingerprint, according to `mechanism`.

```json
{"time":"2026-11-23T12:00:00.000Z","type":"login-attempt","host":"fs01.corp.local","service":"smb","src":{"ip":"192.168.150.10","port":50123},"dst":{"ip":"192.168.150.201","port":445},"user":"Administrator","domain":"CORP","mechanism":"ntlm","secret":"Administrator::CORP:1122334455667788:0a1b2c3d4e5f60718293a4b5c6d7e8f9:0101000000000000","success":false}
```

### `share-access`

`share`, `path`, `operation` (free text from the service, e.g. `open`, `read`, `list`, `write`).

```json
{"time":"2026-11-23T12:00:00.000Z","type":"share-access","host":"fs01.corp.local","service":"smb","src":{"ip":"192.168.150.10","port":50123},"dst":{"ip":"192.168.150.201","port":445},"share":"ADMIN$","path":"\\evil.exe","operation":"write"}
```

### `file-write`

`share`, `path`, `size` (bytes the client sent to that file), `sha256` (of all of those bytes, in the
order they arrived), `truncated` (true if the stored copy is incomplete: the file or the session cap
was hit, so the daemon kept less than the client sent). The service keeps the stored copy in memory
only, for later reads by the same session; the log never carries file content.

```json
{"time":"2026-11-23T12:00:00.000Z","type":"file-write","host":"fs01.corp.local","service":"smb","src":{"ip":"192.168.150.10","port":50123},"dst":{"ip":"192.168.150.201","port":445},"share":"ADMIN$","path":"\\evil.exe","size":61440,"sha256":"abababababababababababababababababababababababababababababababab","truncated":false}
```

### `service-request`

`name` and `detail`: a protocol request worth recording with its argument. The framework also
writes it for its own refusals: `name` is `read-cap-exceeded`, `idle-timeout`, `connection-too-long`
(the connection lifetime cap) or `service-error` (a service raised; `detail` is the exception class
only, never its message). The SMB service's own names are in the table below.

```json
{"time":"2026-11-23T12:00:00.000Z","type":"service-request","host":"fs01.corp.local","service":"smb","src":{"ip":"192.168.150.10","port":50123},"dst":{"ip":"192.168.150.201","port":445},"name":"svcctl CreateService","detail":"evil, C:\\Windows\\evil.exe"}
```

### `connection`

Written once when a served connection ends: `bytes_in`, `bytes_out`, `duration_ms`.

```json
{"time":"2026-11-23T12:00:01.840Z","type":"connection","host":"fs01.corp.local","service":"smb","src":{"ip":"192.168.150.10","port":50123},"dst":{"ip":"192.168.150.201","port":445},"bytes_in":8123,"bytes_out":4410,"duration_ms":1840}
```

### `aggregate`

Written at the end of the session, one per (`host`, `service`) that had events beyond the caps below:
`count`, `first_time`, `last_time`, `by_type` (count per event type), `users` (up to 50 distinct, each cut
to 64 characters), `secrets` (up to 5 distinct, each cut to 1024). No `src` or `dst`.

```json
{"time":"2026-11-23T12:05:00.000Z","type":"aggregate","host":"fs01.corp.local","service":"smb","count":9800,"first_time":"2026-11-23T12:00:02.000Z","last_time":"2026-11-23T12:04:58.000Z","by_type":{"connection":4900,"login-attempt":4900},"users":["admin","root"],"secrets":["Password1"]}
```

### `session-end`

The last record of a session: `session` (the key), `log_truncated` (a hard cap was hit), and
`counters`: `connections` (served), `bytes_in`, `bytes_out`, `events_logged`, `events_by_type` (every
event, logged or not), `events_aggregated` (past the per-service cap), `events_rate_limited`,
`events_hard_capped`, `write_errors`, and `refused` (connections closed unserved, per reason:
`connections-per-source-service`, `connections-per-session`, `host-not-in-session`, `port-not-served`).
Connections from an address that is no session's guest belong to no session; the daemon counts them in
its own stdout log, not here.

```json
{"time":"2026-11-23T12:05:00.000Z","type":"session-end","session":"task-17","log_truncated":false,"counters":{"connections":9803,"bytes_in":8123,"bytes_out":4410,"events_logged":204,"events_by_type":{"login-attempt":4903,"connection":4900},"events_aggregated":9800,"events_rate_limited":0,"events_hard_capped":0,"write_errors":0,"refused":{"host-not-in-session":1}}}
```

## What the SMB service writes

Everything the normaliser may rely on from `service: "smb"`. Paths are share-relative with a leading
backslash (`\dir\file`; the share root is `\`). All strings are cleaned and capped as above.

| `type` | `name` / `operation` | When | Fields |
|---|---|---|---|
| `login-attempt` | `mechanism` `ntlm` | every NTLM AUTHENTICATE: at SMB session setup, and again at an RPC bind that authenticates (connect level) | `user` and `domain` as the client wrote them, `secret` the NetNTLMv2 line in hashcat mode 5600 (`user::domain:challenge:proof:blob`; a NetNTLMv1 client gives the 5500 line, an anonymous one an empty string), `success` true only for a host account with the right password |
| `share-access` | `tree-connect` | a tree connect to `IPC$`, `ADMIN$`, `C$` or a share the host lists | `share` the canonical name, `path` empty |
| `share-access` | `tree-connect-refused` | a tree connect to any other share | `share` the name asked, `path` empty |
| `share-access` | `create` | an open that created a file or directory | `share`, `path` |
| `share-access` | `open` | an open of something that existed (also used for overwrite and supersede) | `share`, `path` |
| `share-access` | `list` | the first directory listing on a handle | `share`, `path` of the directory |
| `share-access` | `read` | the first read on a file handle | `share`, `path` |
| `share-access` | `rename` | a rename accepted | `share`, `path` is `<old path> -> <new path>` |
| `share-access` | `delete` | a delete requested (applied when the handle closes) | `share`, `path` |
| `file-write` | | when a handle that was written to closes, or the connection ends with it open: one record per handle | `share`, `path`, `size`, `sha256`, `truncated` (see above) |
| `service-request` | `svcctl CreateService` | CreateServiceW accepted | `detail` is `<service name>, <binary path>`: the two joined by a comma and one space, the name at most 256 characters, the whole detail cut to 1024 characters with a final ellipsis |
| `service-request` | `svcctl StartService` | StartServiceW on a known service | `detail` as for CreateService, with the stored binary path (itself kept to 4096 characters) |
| `service-request` | `svcctl DeleteService` | DeleteService on a known service | `detail` as for CreateService |
| `service-request` | `svcctl bind` | an RPC bind that asks for authentication the service cannot give (packet integrity or privacy, which is what `sc.exe` sends) | `detail` is `authenticated bind refused: type <n>, level <n>`; the pipe name leads the name, so a refused bind on `srvsvc` is `srvsvc bind` |
| `service-request` | `malformed-smb` | the connection ended because of bytes that are not SMB, NTLM or DCERPC | `detail` is the parser's reason |

No service is ever started and no file ever reaches the host; `StartService` and the writes are
records of what the client asked for.

## What reaches the log, in order

Every event, whatever its type, is checked in this order (`limits.py` holds the numbers):

1. After 20 000 events or 8 MB in the file, nothing more is written (`log_truncated`).
2. After the first 200 events of a (host, service), the rest only update that pair's aggregate.
3. Above 200 events in one second, the rest only update the aggregate.

`aggregate` and `session-end` records are not subject to the caps: they are bounded by construction
(at most one aggregate per host and service, each a few KB at most). A session that failed to open
writes no log at all. A session opened again under the same key appends to the same file and ends it
with a second `session-end`.
