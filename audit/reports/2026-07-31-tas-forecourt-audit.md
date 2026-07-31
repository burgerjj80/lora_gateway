# TAS Network Audit — 192.168.19.0/24

- **Date:** 2026-07-31
- **Scanned from:** operator workstation (`192.168.19.130`), on the target LAN
- **Method:** native Windows PowerShell (async ping sweep, TCP connect probing,
  HTTP title grab, TLS handshake inspection). No credentialed access.
- **Scope:** discovery of `192.168.19.0/24` + service probe of live hosts, with
  focus on the Orpay 1000 payment terminals.

> Findings are heuristic — derived from external port/service probing, not
> authenticated inspection or exploitation. Verify each item on the device
> before acting.

## Environment

The TLS certificate served by the payment terminals identifies the operator as
**GVR (Gilbarco Veeder-Root)**, and the terminal vendor OUI (`00-21-0e`,
Orpak) confirms it: this is a **fuel-forecourt network**. The `.64/.65/.66`
units are **Orpak outdoor payment terminals ("Orpay 1000")** and constitute a
**Cardholder Data Environment (CDE)**. Payment terminals, industrial
controllers, network infrastructure, and office peripherals currently share a
single flat `/24`.

## Host inventory

| IP | MAC | Vendor (OUI) | Open TCP ports | Identity / role |
|----|-----|--------------|----------------|-----------------|
| 192.168.19.1 | 34-fa-40-0d-b8-0a | Ubiquiti | 443 | Gateway / router (HTTPS admin) |
| 192.168.19.5 | e0-23-ff-9e-0b-02 | — | none of scanned | Unidentified |
| 192.168.19.6 | 00-90-e8-a5-a8-c2 | Moxa | 22, 23, 80, 443, 502 | Industrial serial-to-Ethernet gateway (Modbus) |
| 192.168.19.40 | 30-b8-51-43-7d-09 | — | 102 | S7 / ISO-TSAP device (likely controller) |
| 192.168.19.41 | 30-b8-51-43-7d-23 | — | 102 | S7 / ISO-TSAP device |
| 192.168.19.42 | 30-b8-51-43-7c-d5 | — | 102 | S7 / ISO-TSAP device |
| 192.168.19.43 | 30-b8-51-43-7d-07 | — | 102 | S7 / ISO-TSAP device |
| 192.168.19.50 | 34-fa-40-19-d1-77 | Ubiquiti | 22, 23, 80, 443 | Switch / AP |
| 192.168.19.63 | 00-30-18-04-4e-0d | — | 22 | Unidentified (SSH only) |
| 192.168.19.64 | 00-21-0e-03-73-9d | Orpak | 443 | **Orpay 1000 payment terminal** |
| 192.168.19.65 | 00-21-0e-03-73-b8 | Orpak | 443 | **Orpay 1000 payment terminal** |
| 192.168.19.66 | 00-21-0e-03-73-9c | Orpak | 443 | **Orpay 1000 payment terminal** |
| 192.168.19.100 | 58-c1-7a-50-c4-01 | — | 22, 80, 443 | Unidentified controller (web+SSH) |
| 192.168.19.101 | 58-c1-7a-50-c4-ed | — | 22, 80, 443 | Unidentified controller (web+SSH) |
| 192.168.19.102 | 58-c1-7a-50-bd-5f | — | 22, 80, 443 | Unidentified controller (web+SSH) |
| 192.168.19.130 | (this host) | — | — | Operator workstation (dual-homed, see below) |
| 192.168.19.240 | bc-0f-f3-ca-e1-a8 | — | none of scanned | Unidentified |
| 192.168.19.245 | 98-e7-f4-05-0a-db | HP | 80, 443, 8080, 9100 | HP LaserJet Pro M501dn (printer) |

Vendor names are inferred from MAC OUI prefixes and should be treated as
best-effort until confirmed on-device.

## Orpay 1000 payment terminals (.64 / .65 / .66)

- **Exposure:** only **TCP 443** open on all three — no Telnet, SSH, HTTP,
  SNMP, SMB, or RDP. This is a tight, well-reduced attack surface.
- **TLS:** protocol **TLS 1.2**, cipher **AES-128**, no deprecated
  protocol/cipher support observed. Web root returns a "Home" page.
- **Certificate:** `CN=*.GVR_Local.net, OU=Embedded, O=GVR`, valid
  2020-07-01 → 2030-06-29.

### Terminal findings

| ID | Sev | Finding | Detail | Remediation |
|----|-----|---------|--------|-------------|
| T-1 | LOW | Self-signed certificate | Terminals present a self-signed cert; clients cannot cryptographically verify the endpoint (MITM risk on the segment). | Issue certs from an internal CA and distribute trust, or accept as residual risk with compensating network controls. |
| T-2 | LOW | Shared wildcard key across units | All three terminals serve the same `*.GVR_Local.net` certificate, implying shared key material. Compromise of one unit's key allows impersonation of all. | Confirm with the vendor whether per-unit keys are supported; treat any single-unit compromise as affecting all three. |

Overall the payment terminals are the **best-hardened devices on the network**.

## Network-wide findings (most severe first)

| ID | Sev | Host(s) | Finding | Remediation |
|----|-----|---------|---------|-------------|
| N-1 | HIGH | .6, .50 | **Telnet (23) exposed** — cleartext admin credentials on an industrial gateway and a network switch. | Disable Telnet; use SSH. If a device is Telnet-only, isolate it on a management VLAN with strict ACLs. |
| N-2 | HIGH | .6 | **Modbus (502) exposed** — Modbus has no authentication; any LAN host can read/write controller registers. | Restrict 502 to the specific control host(s) via firewall/ACL; segment OT away from general LAN and the CDE. |
| N-3 | MEDIUM | .40–.43 | **S7 / ISO-TSAP (102) exposed** on four controllers — legacy S7 has weak/no auth; LAN access can equal control-plane access. | Firewall port 102 to authorized engineering hosts only; segment these controllers; apply vendor auth/hardening if available. |
| N-4 | MEDIUM | all | **Flat network / no segmentation** — payment terminals (CDE) share one `/24` with PLCs, industrial gateways, a printer, and office gear. | Segment the CDE from OT and office networks per PCI-DSS; enforce inter-VLAN firewalling; limit the payment segment to payment devices. |
| N-5 | MEDIUM | .130 | **Dual-homed operator workstation** — bridges `192.168.23.0/24` and `192.168.19.0/24`, potentially straddling the CDE boundary. | Remove the bridge; if cross-segment access is required, route it through a firewall/jump host with logging. A workstation should not span the payment segment and another zone. |
| N-6 | MEDIUM | .100–.102 | **Cleartext HTTP (80) management** alongside HTTPS on three controllers. | Serve management over HTTPS only; redirect 80→443; verify auth is enforced. |
| N-7 | LOW | .245 | **Printer on the payment segment** with web (80/443/8080) and raw print (9100) exposed. Printers are common pivot/exfil points. | Move the printer off the payment segment; set an admin password; update firmware; disable unused services. |
| N-8 | INFO | .1, .50 | Network infrastructure (Ubiquiti) exposes HTTPS/SSH admin. | Ensure strong unique admin credentials, current firmware, and management restricted to an admin VLAN. |

## Unidentified hosts to resolve

`.5`, `.63`, `.100–.102`, `.240` were not positively identified. In particular
`.100–.102` (three web+SSH controllers) or the Moxa `.6` are the leading
candidates for the **"enhance controller"** referenced for this project.
A follow-up banner/service probe is needed to name them (see next audit step).

## Recommended priorities

1. **Kill Telnet** on `.6` and `.50` (N-1).
2. **Firewall the industrial control ports** — Modbus/502 and S7/102 (N-2, N-3).
3. **Segment the CDE** away from OT/office and remove the workstation bridge
   (N-4, N-5) — the highest-leverage structural fix and a PCI-DSS requirement.
4. Move the printer off the payment segment (N-7).
5. Identify the remaining hosts and fold them into this inventory.

---
_Heuristic audit generated with the `audit/` toolkit and manual analysis of the
scan output. Not a substitute for an authenticated, on-device review._
