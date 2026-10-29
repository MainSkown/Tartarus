# Safety

Tartarus runs live malware on your machine. Read this page before your first run.

## What a sample can reach

Each analysis runs in a guest VM. The guest sits on a private network inside the `cape` container, and its only way out is the route you choose for the analysis.

| Route | What the sample can reach | What it cannot reach |
|---|---|---|
| `NONE` | Nothing outside. Only the gateway services the run needs, such as the port that sends monitor data to CAPE. | The internet, your network, other guests, Tartarus services. |
| `DROP` | Same as `NONE`: no outside traffic. | Same as `NONE`. |
| `INETSIM` (default) | A fake internet. INetSim on the gateway answers DNS and common network services, so the sample sees replies. | The real internet, your network, other guests, Tartarus services. |
| `INTERNET` | The real internet, through this machine's public IP. | Your local and private networks, Docker networks, other guests, Tartarus services. |

On every route, the rules that the security review checked hold:

- a guest reaches only its gateway, not your LAN, not the host's private networks and not the Tartarus containers (OpenSearch, PostgreSQL, the backend and the guest control service);
- a guest cannot reach another guest;
- a guest cannot use an address it made up to get around these rules.

`make verify-isolation GUESTS="lab1 lab5"` checks these rules from inside two real guests. See [the security notes](../security.md#layers) for what was proven.

Every packet is recorded in the PCAP, whichever route you use.

## The internet route

`INTERNET` lets the sample talk to real servers. Malware often contacts its command server, downloads a second stage or sends data out. You then:

- show this machine's public IP address to those servers;
- let the sample reach real sites, which may be hostile or log the visit.

Use a separate network or a VPN for the machine before you run live malware on this route. Tartarus does not offer a VPN route yet, so you must set it up at the network level.

Keep the default route, `INETSIM`, unless you have a reason to pick another. The default is set in **Settings**.

## What a guest is not

- **It is not invisible.** A sample can detect a virtual machine, and some do. The wizard removes obvious giveaways, and the **Make it look used** option adds realism. Sandbox evasion is outside the threat model of this project. See [the threat model](../security.md#threat-model).
- **It is not a place to keep your data.** Each analysis starts from a clean snapshot, so a previous sample does not carry over, but the guest still runs real Windows code.
- **Clipboard is not shared.** There is no clipboard sync between the host and the guest.

## Password-protected zips

When you submit a zip, the guest unpacks it when the run starts, with the tools inside the guest. Your machine does not unpack the sample, and neither does the Tartarus backend. The backend only reads the zip's list of files and checks the password against the zip's header. It decrypts and extracts nothing.

The archive password is not a secret. Malware zips are shared with a password that everyone knows, and `infected` is the usual one. Tartarus keeps the password with the analysis and in CAPE's record of the task. The guest's 7-Zip command line shows it too, so it can appear in the events and the report. The API does not return it in an analysis's options.

## Accepted risks

The security review fixed what it could. These risks remain by design. The full table is in [the security doc](../security.md#accepted-risks).

- **The `cape` container runs privileged.** It needs the host's KVM device and some capabilities to run VMs. If a sample escaped the guest and then gained root inside `cape`, it would have more access than a normal container.
- **There is no login.** The app listens on `127.0.0.1`, over plain HTTP. Any user on this machine can open it.
- **The Guest VM page shows the guest's password** so you can log into the guest desktop.
- **The `INTERNET` route reaches the internet.** That is its purpose.

## Practical advice

1. Use a dedicated machine or a VM for Tartarus where you can. Keep it away from data you care about.
2. Use the `INETSIM` route unless the sample needs the real internet.
3. Use a VPN or a separate network before you run live malware on `INTERNET`.
4. Leave the app on `127.0.0.1`. Do not publish port 8080 on other interfaces. Remember the [421 and 403 notes](troubleshooting.md#421-or-403-when-you-open-the-app).
5. Keep `.env` at mode 600. It holds the secrets.
6. After a host kernel update, reboot before you start guests. See [troubleshooting](troubleshooting.md#the-guest-does-not-run-after-a-kernel-update).
7. Downloads of artifacts are zip archives with the password `infected`, so a browser never runs a sample by accident. Do not extract them on a machine you care about.
