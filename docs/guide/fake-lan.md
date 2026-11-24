# The fake local network

A guest sees only its gateway. Malware that scans the local network, or tries to spread to other
machines, finds nothing there, so the report shows no lateral movement. The fake local network gives
the sample a few machines to find: emulated Windows and Linux hosts with real-looking services on
addresses in the guest's own network. Each attempt on them is logged, and the report shows what the
sample tried.

Read [safety](safety.md) first. The fake hosts are not real, and nothing the sample sends reaches a
real machine, but the sample still runs live malware in a guest.

## When to use it

- The sample scans the network, copies itself to other machines, or uses stolen credentials to log
  in to them (SMB, RDP, WinRM, SSH, LDAP, SQL).
- You want the report to show lateral movement: the Network tab, the Summary, the Sigma alerts and
  the ATT&CK matrix.

Leave it off for a sample that does nothing on the network, or when you want the run to be exactly
the one you ran before. With it off, an analysis is the same as it always was.

## Turn it on

1. Open **Submit** and choose a sample, as in [your first analysis](first-analysis.md).
2. Switch on **SIMULATE LOCAL NETWORK**. It is off by default.
3. Choose one of the presets in **Local network presets**. The preset's hosts are listed under its
   name, so you can see what the sample will find before you run it.
4. Submit as usual.

The switch works with the routes `NONE`, `DROP` and `INETSIM`. With the **INTERNET** route it is
disabled, with the reason written beside it: a simulated local network and the real internet do not
mix, so pick another route to use the fake network. The API refuses the same combination.

If the presets cannot be read, the switch says so and submitting waits. If the fake network is not
ready when you submit, the submission is refused with the reason (see Troubleshooting).

## The presets

A preset is a set of fake hosts. Its file lists each host's name, role, services and accounts.
Addresses are the same in every guest: the preset's offset in the guest subnet, by default
`192.168.150.200` to `.247`.

| Preset | Domain | Hosts |
|---|---|---|
| **Small office** (`small-office`) | `corp.local` | `dc01` (domain controller: SMB, LDAP, RDP, WinRM), `fs01` (file server: SMB, RDP, WinRM), `ws01` and `ws02` (workstations: SMB, RDP), `sql01` (SQL server: SMB, MSSQL, RDP, WinRM), `printer01` (printer: SSH) |
| **Flat home LAN** (`flat-home`) | `home.lan` | `nas` (SMB, SSH), `desktop` (workstation: SMB, RDP), `laptop` (workstation: SMB), `printer` (SSH) |
| **Domain with servers** (`domain-servers`) | `lab.internal` | `dc01` and `dc02` (domain controllers: LDAP, SMB, WinRM, RDP), `app01` (SMB, RDP, WinRM), `sql01` (MSSQL, SMB, RDP), `file01` (SMB, RDP), `web01` (RDP, WinRM), `jump01` (RDP, SSH) |

The names above are the short ones; each host's full name is its name with the domain, for example
`fs01.corp.local`. The files are in `guest/lan-presets/`.

**Accounts.** Every SMB host has a few well-known accounts with weak, well-known passwords. Windows'
file-sharing client signs its traffic with a key made from the password, so a host that accepts any
password breaks the session; a Windows sample gets a working session only with one of these accounts.
The passwords are in the preset files, not in this guide. A sample that logs in with the right password gets a session on the fake host; a sample
with a wrong one is refused, and its password hash is logged.

Ports are the services' usual ones: 445 (SMB), 3389 (RDP), 5985 (WinRM), 22 (SSH), 389 (LDAP) and
1433 (MSSQL), unless a preset says otherwise.

## What the fake hosts do

- **Log every attempt.** Each connection, login attempt, share access, file write and service request
  is written to the analysis's log, with the time, the host, the service and the sample's addresses.
- **Answer just enough.** A host opens the port, accepts a login with its account, and lists its
  shares, so the sample goes on to the next step.
- **Keep files in memory.** A file the sample writes to a fake share is kept for the length of the run,
  up to 16 MiB per file and 64 MiB in all. What is beyond the cap is not kept, and the log says so. The
  file is never written to disk and never run.
- **Cap the flood.** A scan that makes thousands of attempts is logged up to a limit, then counted. The
  report says when the log was cut short.

## What the fake hosts never do

- **Never run what the sample sends.** A service that the sample asks to create or start is logged,
  and nothing starts.
- **Never give a shell.** A remote login, over WinRM or RDP, never offers a command line.
- **Never reach a real machine.** The guest cannot reach your network or another guest, with or without
  the fake network (see [safety](safety.md)).

## What appears in the report

- **Network tab.** A hosts list entry marked **FAKE LAN HOST** for each fake host the sample reached,
  and the flows to those hosts. The badge has a filter action, so you can keep only, or hide, the
  traffic to the fake network.
- **Summary, LATERAL MOVEMENT.** Per fake host: the services the sample touched, the number of attempts (a
  connection counts once, however many of CAPE's sources saw it; a login on a port counts for that login, not
  again for its connection), when the first and the last attempt happened, the credentials it tried and the files it wrote. The
  section shows only when the fake network was on. When the sample did nothing on it, the section says so.
- **Events.** Login attempts, share accesses, file writes and service requests appear in the **network**
  lane. Sweeps and fan-outs (one process reaching many hosts) and credential spraying (one user name tried
  on many hosts) appear as events of their own.
- **Sigma alerts and ATT&CK.** Eleven rules in `rules/sigma/tartarus/` tag these events with their
  techniques: connections to SMB, RDP, WinRM, SSH and MSSQL (T1021 and T1210), access to an admin share,
  an executable written to one (T1570), a service created over SMB (T1569.002), credential spraying
  (T1110.003), sweeps (T1046) and fan-outs. The techniques show in the ATT&CK matrix.
- **Exported report.** The HTML and PDF reports have a **Lateral movement** section, with the same
  information as the Summary.

The credentials and file names in these sections are what the sample sent, escaped on display, and none
of them is Tartarus's.

## Limits

- **No `wmiexec`.** It needs DCOM on port 135, which the fake hosts do not serve.
- **No `sc.exe` against a fake host.** It needs an authenticated, sealed RPC session, which the fake
  hosts refuse. The attempt is logged; the service is not created.
- **Single-label names do not resolve.** `\\FS01\C$` finds nothing by name; use `\\fs01.corp.local\C$`
  or the IP address. Guests have no DNS suffix, so the sample must use the full name.
- **NetBIOS and LLMNR are not answered.** A name that a sample asks for by broadcast gets no reply.
- **One MAC and one TTL.** Every fake host answers with the same network-card address, which is the
  bridge's, and replies with TTL 128. A sample that checks these can tell the hosts apart from real ones.
- **Final report only.** The fake network's events appear when the analysis finishes, not in the live
  feed while it runs.
- **Routes.** The fake network works with `NONE`, `DROP` and `INETSIM`. The `INTERNET` route is refused.

## Troubleshooting

**"The fake local network is not ready: ..."** when you submit. The reason is written after the colon.
The control service answers this at `GET /lan/health`, on the internal control network only; the
submission refusal carries the same reason. If the reason is that the fake-host container "runs in an old
network namespace", the `cape` container was recreated alone. Run `docker compose up -d` from the
repository folder, which recreates the fake-host container in the new namespace.

**"The fake local network could not start: ..."** on the analysis. The analysis did not run, and nothing
was submitted to CAPE, so you lose no run. Fix the reason it gives and submit again.

**"The local network presets could not be loaded"** in the submit dialog. The control service did not
answer. Check that the stack is running (`make up`), then reopen the dialog.

**The Network tab shows no fake hosts** on an analysis you expected to reach them. Check that the
switch was on when you submitted: the Summary's LATERAL MOVEMENT section names the preset only when the
fake network was on. An analysis run without a preset has no fake hosts.

For anything else, see [troubleshooting](troubleshooting.md).
