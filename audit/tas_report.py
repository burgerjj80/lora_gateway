#!/usr/bin/env python3
"""
TAS Network Audit — report generator.

Parses the nmap XML produced by tas_audit.sh and emits a Markdown report:
an inventory of discovered hosts, per-host open services, and a prioritised
findings list built from a curated set of embedded-device failure modes.

The findings ruleset is heuristic. It flags things worth a human look
(cleartext protocols, weak TLS, exposed management, likely-default services)
— it does not confirm exploitability. Verify each finding manually.
"""
import argparse
import glob
import os
import xml.etree.ElementTree as ET
from collections import defaultdict

# severity ordering for sorting / display
SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}


def sev(level, title, host, port, detail, remediation):
    return {
        "sev": level, "title": title, "host": host, "port": port,
        "detail": detail, "remediation": remediation,
    }


# port -> (severity, title, detail, remediation) for cleartext / risky services
RISKY_PORTS = {
    21:   ("MEDIUM", "FTP exposed",
           "FTP transfers credentials and data in cleartext.",
           "Disable FTP; use SFTP/SCP. If required, restrict by firewall and disable anonymous access."),
    23:   ("HIGH", "Telnet exposed",
           "Telnet sends credentials in cleartext and is a top target on embedded devices.",
           "Disable Telnet entirely; use SSH. If the device only offers Telnet, isolate it on a management VLAN."),
    69:   ("MEDIUM", "TFTP exposed",
           "TFTP is unauthenticated and often used to pull/replace firmware.",
           "Disable TFTP unless actively provisioning; never leave it reachable from general LAN hosts."),
    111:  ("LOW", "rpcbind exposed",
           "rpcbind/portmapper can leak RPC service info and enable amplification.",
           "Firewall port 111 from untrusted segments if RPC is not needed."),
    161:  ("MEDIUM", "SNMP exposed",
           "SNMP with a default community string ('public'/'private') leaks device config.",
           "Change community strings, use SNMPv3 with auth+priv, or disable SNMP."),
    445:  ("MEDIUM", "SMB exposed",
           "SMB on an appliance is a common lateral-movement and exposure vector.",
           "Disable SMB if not required; patch and restrict to management hosts otherwise."),
    512:  ("HIGH", "rexec exposed", "Legacy r-service with weak/cleartext auth.",
           "Disable rexec/rlogin/rsh; use SSH."),
    513:  ("HIGH", "rlogin exposed", "Legacy r-service with weak/cleartext auth.",
           "Disable rexec/rlogin/rsh; use SSH."),
    514:  ("HIGH", "rsh exposed", "Legacy r-service with weak/cleartext auth.",
           "Disable rexec/rlogin/rsh; use SSH."),
    3389: ("MEDIUM", "RDP exposed",
           "RDP exposed on the LAN is a frequent ransomware entry point.",
           "Restrict RDP to jump hosts, enforce NLA + strong creds, or disable it."),
}


def txt(el, default=""):
    return el if isinstance(el, str) else (el.text if el is not None and el.text else default)


def parse_host(host_el):
    """Return a dict describing one <host> element from nmap XML."""
    addr, mac, vendor = None, None, None
    for a in host_el.findall("address"):
        if a.get("addrtype") == "ipv4":
            addr = a.get("addr")
        elif a.get("addrtype") == "mac":
            mac = a.get("addr")
            vendor = a.get("vendor")
    hostnames = [h.get("name") for h in host_el.findall("./hostnames/hostname") if h.get("name")]

    os_guess = None
    best = host_el.find("./os/osmatch")
    if best is not None:
        os_guess = f"{best.get('name')} ({best.get('accuracy')}%)"

    ports = []
    for p in host_el.findall("./ports/port"):
        state = p.find("state")
        if state is None or state.get("state") != "open":
            continue
        svc = p.find("service")
        scripts = {s.get("id"): s.get("output", "") for s in p.findall("script")}
        ports.append({
            "port": int(p.get("portid")),
            "proto": p.get("protocol"),
            "name": svc.get("name") if svc is not None else "",
            "product": (svc.get("product", "") + " " + svc.get("version", "")).strip() if svc is not None else "",
            "tunnel": svc.get("tunnel", "") if svc is not None else "",
            "scripts": scripts,
        })
    return {"ip": addr, "mac": mac, "vendor": vendor, "hostnames": hostnames,
            "os": os_guess, "ports": ports}


def analyse(host):
    """Apply the heuristic ruleset to one parsed host -> list of findings."""
    out = []
    ip = host["ip"]
    for p in host["ports"]:
        port, name, scripts = p["port"], p["name"], p["scripts"]

        # 1. risky / cleartext ports by number
        if port in RISKY_PORTS:
            s, title, detail, rem = RISKY_PORTS[port]
            extra = ""
            if port == 21 and "ftp-anon" in scripts:
                s, extra = "HIGH", " Anonymous FTP login is ALLOWED."
            if port == 161 and "snmp-info" in scripts:
                extra = " SNMP responded to a query — check the community string."
            out.append(sev(s, title, ip, port, detail + extra, rem))

        # 2. cleartext HTTP admin surface
        if name in ("http", "http-proxy") and p["tunnel"] != "ssl":
            title_txt = scripts.get("http-title", "")
            looks_admin = any(k in title_txt.lower() for k in
                              ("login", "admin", "router", "gateway", "controller", "config", "setup"))
            out.append(sev(
                "MEDIUM" if looks_admin else "LOW",
                "HTTP management interface (no TLS)" if looks_admin else "Cleartext HTTP service",
                ip, port,
                f"Web service over plain HTTP. {('Title: ' + title_txt.strip()) if title_txt else ''}".strip(),
                "Serve the admin UI over HTTPS only; redirect HTTP->HTTPS; ensure auth is enforced."))

        # 3. default-account NSE hit
        if "http-default-accounts" in scripts and "credentials" in scripts["http-default-accounts"].lower():
            out.append(sev("HIGH", "Default credentials likely", ip, port,
                           "http-default-accounts matched a known default login.",
                           "Change all default passwords immediately; disable stock accounts."))

        # 4. weak TLS
        enum = scripts.get("ssl-enum-ciphers", "")
        if enum:
            weak = []
            for proto in ("SSLv2", "SSLv3", "TLSv1.0", "TLSv1.1"):
                if proto in enum:
                    weak.append(proto)
            if "least strength: C" in enum or "least strength: D" in enum or "least strength: E" in enum or "least strength: F" in enum:
                weak.append("weak cipher grade")
            if weak:
                out.append(sev("MEDIUM", "Weak TLS configuration", ip, port,
                               "Deprecated protocol/cipher support: " + ", ".join(weak) + ".",
                               "Disable SSLv2/v3 and TLS 1.0/1.1; offer TLS 1.2+ with strong ciphers only."))
        cert = scripts.get("ssl-cert", "")
        if "self-signed" in cert.lower() or "self signed" in cert.lower():
            out.append(sev("LOW", "Self-signed TLS certificate", ip, port,
                           "Device presents a self-signed certificate.",
                           "Install a certificate from an internal CA and pin/trust it on clients."))

        # 5. SSH version note (informational — flag ancient OpenSSH)
        if name == "ssh":
            out.append(sev("INFO", "SSH service", ip, port,
                           f"SSH reachable. {p['product']}".strip(),
                           "Ensure key-based auth, no root login, and a current OpenSSH build."))

        # 6. LoRa packet-forwarder UDP (context for the TAS project)
        if port == 1700 and p["proto"] == "udp":
            out.append(sev("INFO", "LoRa packet-forwarder port (UDP 1700)", ip, port,
                           "Semtech UDP packet-forwarder endpoint is reachable.",
                           "Confirm this is expected for this host and restrict to the network server."))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="directory of nmap -oA output")
    ap.add_argument("--scope", required=True)
    ap.add_argument("--stamp", required=True)
    ap.add_argument("--priv", default="0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    hosts = {}
    for xmlf in sorted(glob.glob(os.path.join(args.raw, "*.xml"))):
        try:
            root = ET.parse(xmlf).getroot()
        except ET.ParseError:
            continue
        for h_el in root.findall("host"):
            h = parse_host(h_el)
            if not h["ip"]:
                continue
            # merge TCP + UDP scans of the same host
            if h["ip"] in hosts:
                hosts[h["ip"]]["ports"].extend(h["ports"])
                for k in ("mac", "vendor", "os"):
                    hosts[h["ip"]][k] = hosts[h["ip"]][k] or h[k]
            else:
                hosts[h["ip"]] = h

    findings = []
    for h in hosts.values():
        findings.extend(analyse(h))
    findings.sort(key=lambda f: (SEV_ORDER.get(f["sev"], 9), f["host"], f["port"]))

    counts = defaultdict(int)
    for f in findings:
        counts[f["sev"]] += 1

    L = []
    L.append(f"# TAS Network Audit Report")
    L.append("")
    L.append(f"- **Run:** `{args.stamp}`")
    L.append(f"- **Scope:** `{args.scope}`")
    L.append(f"- **Privilege:** {'root (SYN/UDP/OS scan)' if args.priv == '1' else 'unprivileged (TCP connect only)'}")
    L.append(f"- **Live hosts:** {len(hosts)}")
    L.append(f"- **Findings:** "
             f"{counts['HIGH']} high · {counts['MEDIUM']} medium · {counts['LOW']} low · {counts['INFO']} info")
    L.append("")
    L.append("> Heuristic report — verify each finding manually before acting. "
             "Generated by `audit/tas_audit.sh`.")
    L.append("")

    # ---- host inventory
    L.append("## Host inventory")
    L.append("")
    L.append("| IP | MAC | Vendor | Hostname | OS guess | Open ports |")
    L.append("|----|-----|--------|----------|----------|------------|")
    for ip in sorted(hosts, key=lambda x: tuple(int(o) for o in x.split("."))):
        h = hosts[ip]
        openp = ", ".join(f"{p['port']}/{p['proto']}" for p in sorted(h["ports"], key=lambda x: x["port"])) or "—"
        L.append(f"| {ip} | {h['mac'] or '—'} | {h['vendor'] or '—'} | "
                 f"{', '.join(h['hostnames']) or '—'} | {h['os'] or '—'} | {openp} |")
    L.append("")

    # ---- findings
    L.append("## Findings (most severe first)")
    L.append("")
    if not findings:
        L.append("_No heuristic findings. Still review the service detail below manually._")
    for f in findings:
        L.append(f"### [{f['sev']}] {f['title']} — {f['host']}:{f['port']}")
        L.append("")
        L.append(f"- **Detail:** {f['detail']}")
        L.append(f"- **Remediation:** {f['remediation']}")
        L.append("")

    # ---- per-host service detail
    L.append("## Service detail")
    L.append("")
    for ip in sorted(hosts, key=lambda x: tuple(int(o) for o in x.split("."))):
        h = hosts[ip]
        L.append(f"### {ip}")
        if not h["ports"]:
            L.append("_No open ports detected._")
            L.append("")
            continue
        L.append("")
        L.append("| Port | Proto | Service | Product / Version |")
        L.append("|------|-------|---------|-------------------|")
        for p in sorted(h["ports"], key=lambda x: x["port"]):
            L.append(f"| {p['port']} | {p['proto']} | {p['name'] or '—'} | {p['product'] or '—'} |")
        L.append("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
