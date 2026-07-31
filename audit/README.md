# TAS Network Audit Toolkit

Repeatable discovery + service/config audit + Markdown report for the TAS
project LAN — e.g. auditing the **Orpay 1000** (`192.168.19.64`) and the
**enhance controller** on `192.168.19.0/24`.

## Why this exists (and where it must run)

A Claude Code **cloud/web** session runs in an isolated container with no route
to private LAN addresses (`192.168.x.x`, `10.x`, etc.) — the proxy blocks them
by policy. It physically cannot scan a device on your local network.

So this toolkit is designed to run from a **standing audit host that is on the
target network** (a Linux box / WSL2 / the gateway Pi). Run Claude Code there
and it can drive these scripts directly; or run them yourself and commit the
results back to the repo.

## Two editions — pick what your audit host runs

| Edition | File | Needs | Depth |
|---------|------|-------|-------|
| **Linux / WSL** | `tas_audit.sh` + `tas_report.py` | `nmap` (+ python3) | Full: service/version, OS, UDP, TLS + NSE scripts |
| **Windows PowerShell** | `tas_audit.ps1` | nothing — built-in only | Discovery + TCP port audit + web banner + heuristic findings |

Use the Linux edition where you can (much deeper). Use the PowerShell edition
on a locked-down Windows box where you can't install nmap/WSL — it needs no
admin and no installs.

### Linux / WSL edition

```bash
sudo apt update && sudo apt install -y nmap
# python3 is used for the analysed report; without it you get raw nmap output.
```

Run as **root/sudo** for the full audit (SYN scan, UDP, OS detection).
Unprivileged runs fall back to a TCP connect scan and skip UDP/OS.

### Windows PowerShell edition

No installation. From the `audit` folder on a machine on the target LAN:

```powershell
.\tas_audit.ps1 -Subnet 192.168.19 -Target 192.168.19.64
.\tas_audit.ps1 -Subnet 192.168.19          # sweep + audit every live host
```

If PowerShell blocks the script, allow it for the current session only:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Output goes to `audit/reports/run-<timestamp>/report.md`, same as the Linux edition.

## Usage

```bash
# Sweep the whole /24, then deep-audit every live host it finds:
sudo ./tas_audit.sh 192.168.19.0/24

# Sweep to inventory the subnet, but deep-audit only the Orpay:
sudo ./tas_audit.sh 192.168.19.0/24 --target 192.168.19.64

# Audit a single known host, no sweep:
sudo ./tas_audit.sh 192.168.19.64

# Faster (top-1000 ports), skip UDP:
sudo ./tas_audit.sh 192.168.19.0/24 --fast --no-udp
```

### Options

| Option | Meaning |
|--------|---------|
| `--target IP` | Restrict deep audit to this host (repeatable). Default: all live hosts. |
| `--fast` | Top-1000 ports instead of a full `-p-` scan. |
| `--no-udp` | Skip the UDP top-ports scan. |
| `--aggressive` | Add intrusive NSE (default-cred + SNMP brute). Authorized use only. |
| `-o DIR` | Report output directory (default `audit/reports`). |

## Output

Each run creates `audit/reports/run-<timestamp>/` containing:

- `report.md` — analysed report: host inventory, prioritised findings
  (HIGH → INFO), and per-host service detail.
- `raw/` — raw nmap output (`.nmap` / `.gnmap` / `.xml`) for every phase, so
  results are reproducible and auditable.

Commit a run to keep it in the TAS project history:

```bash
git add audit/reports/run-<timestamp> && git commit -m "TAS audit <timestamp>"
```

## What the audit checks

- **Discovery:** live hosts on the subnet + MAC vendor (identifies devices).
- **Services:** full/again top-port TCP + UDP scan with version detection.
- **TLS:** protocol/cipher strength, self-signed certs.
- **Embedded-device failure modes:** telnet/FTP/TFTP/r-services, SNMP with
  default community, exposed SMB/RDP, cleartext HTTP admin panels, likely
  default credentials, and the LoRa packet-forwarder port (UDP 1700).

## Scope & authorization

Only run this against hosts you own or are explicitly authorized to test.
The findings are **heuristic** — they point you at things worth checking, not
confirmed vulnerabilities. Verify each one before acting.
