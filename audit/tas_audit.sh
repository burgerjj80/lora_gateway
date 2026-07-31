#!/usr/bin/env bash
#
# TAS Network Audit Toolkit
# ------------------------------------------------------------------------------
# Discovery + service/config audit + Markdown report for the TAS project LAN
# (e.g. the Orpay 1000 and the enhance controller on 192.168.19.0/24).
#
# Run this from a machine that is ON the target network. It cannot be run from
# the Claude Code cloud session, which has no route to private LAN addresses.
#
# Usage:
#   ./tas_audit.sh <subnet-or-host> [--target IP ...] [options]
#
# Examples:
#   ./tas_audit.sh 192.168.19.0/24                 # sweep + audit every live host
#   ./tas_audit.sh 192.168.19.0/24 --target 192.168.19.64   # sweep, deep-audit one
#   ./tas_audit.sh 192.168.19.64                   # audit a single host, no sweep
#
# Options:
#   --target IP     Restrict deep audit to this host (repeatable). Default: all
#                   live hosts found during discovery.
#   --fast          Top-1000 ports instead of a full -p- scan.
#   --no-udp        Skip the UDP top-ports scan.
#   --aggressive    Add intrusive NSE scripts (default-cred + banner brute).
#                   Only use with explicit authorization.
#   -o, --outdir D  Report output directory (default: audit/reports).
#   -h, --help      Show this help.
#
# Requires: nmap. Optional: python3 (richer report; falls back to raw nmap output).
# Run as root/sudo for SYN + UDP + OS detection; otherwise falls back to a
# TCP connect scan and skips UDP/OS.
# ------------------------------------------------------------------------------
set -euo pipefail

VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- defaults ---------------------------------------------------------------
SCOPE=""
TARGETS=()
FAST=0
DO_UDP=1
AGGRESSIVE=0
OUTDIR="${SCRIPT_DIR}/reports"

# ---- helpers ----------------------------------------------------------------
log()  { printf '\033[1;34m[*]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[+]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# ---- argument parsing -------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)     TARGETS+=("$2"); shift 2 ;;
    --fast)       FAST=1; shift ;;
    --no-udp)     DO_UDP=0; shift ;;
    --aggressive) AGGRESSIVE=1; shift ;;
    -o|--outdir)  OUTDIR="$2"; shift 2 ;;
    -h|--help)    usage 0 ;;
    -*)           die "Unknown option: $1 (see --help)" ;;
    *)            [[ -z "$SCOPE" ]] && SCOPE="$1" || TARGETS+=("$1"); shift ;;
  esac
done

[[ -z "$SCOPE" ]] && { warn "No subnet or host given."; usage 1; }
command -v nmap >/dev/null 2>&1 || die "nmap not found. Install it: sudo apt install -y nmap"

# ---- privilege / scan-type selection ----------------------------------------
if [[ "$(id -u)" -eq 0 ]]; then
  TCP_SCAN="-sS"
  PRIV=1
else
  TCP_SCAN="-sT"
  PRIV=0
  warn "Not running as root: using TCP connect scan (-sT), skipping UDP and OS detection."
  warn "For a complete audit, re-run with sudo."
  DO_UDP=0
fi

# ---- run bookkeeping --------------------------------------------------------
# Timestamp comes from the OS clock on the audit rig (not available in the cloud session).
STAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUTDIR}/run-${STAMP}"
RAW_DIR="${RUN_DIR}/raw"
mkdir -p "$RAW_DIR"
REPORT="${RUN_DIR}/report.md"

log "TAS Network Audit v${VERSION}"
log "Scope: ${SCOPE}   Raw output: ${RAW_DIR}"

# ---- NSE script selection ---------------------------------------------------
NSE="default,ssl-enum-ciphers,ssl-cert,http-title,http-headers,http-server-header,snmp-info,ftp-anon,banner"
if [[ "$AGGRESSIVE" -eq 1 ]]; then
  warn "Aggressive mode: adding intrusive default-credential checks."
  NSE="${NSE},http-default-accounts,snmp-brute"
fi

# ---- port spec --------------------------------------------------------------
if [[ "$FAST" -eq 1 ]]; then PORTS="--top-ports 1000"; else PORTS="-p-"; fi

# ---- Phase 1: discovery -----------------------------------------------------
LIVE_HOSTS=()
if [[ "$SCOPE" == */* ]]; then
  log "Phase 1: host discovery sweep of ${SCOPE} ..."
  nmap -sn -oA "${RAW_DIR}/discovery" "$SCOPE" >/dev/null
  # Extract live host IPs from the grepable output.
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && LIVE_HOSTS+=("$ip")
  done < <(grep -E "Status: Up" "${RAW_DIR}/discovery.gnmap" 2>/dev/null | awk '{print $2}')
  ok "Discovered ${#LIVE_HOSTS[@]} live host(s)."
else
  log "Phase 1: single host mode (${SCOPE}) — skipping sweep."
  LIVE_HOSTS=("$SCOPE")
fi

# Decide which hosts get the deep audit.
if [[ "${#TARGETS[@]}" -gt 0 ]]; then
  AUDIT_HOSTS=("${TARGETS[@]}")
else
  AUDIT_HOSTS=("${LIVE_HOSTS[@]}")
fi
[[ "${#AUDIT_HOSTS[@]}" -eq 0 ]] && { warn "No live hosts to audit."; AUDIT_HOSTS=(); }

# ---- Phase 2: deep audit per host ------------------------------------------
for host in "${AUDIT_HOSTS[@]}"; do
  safe="${host//\//_}"
  log "Phase 2: auditing ${host} (TCP ${PORTS//--/ }) ..."
  nmap ${TCP_SCAN} ${PORTS} -sV -O --script "${NSE}" \
       --version-intensity 5 -oA "${RAW_DIR}/host-${safe}-tcp" "$host" >/dev/null 2>&1 \
       || warn "TCP audit of ${host} returned a non-zero status (partial results kept)."
  if [[ "$DO_UDP" -eq 1 ]]; then
    log "  UDP top-ports scan of ${host} (checks 1700/LoRa, 161/SNMP, 53, 123, ...) ..."
    nmap -sU --top-ports 50 --script "snmp-info,banner" \
         -oA "${RAW_DIR}/host-${safe}-udp" "$host" >/dev/null 2>&1 \
         || warn "UDP audit of ${host} returned a non-zero status."
  fi
  ok "  Done: ${host}"
done

# ---- Phase 3: report --------------------------------------------------------
log "Phase 3: building report ..."
if command -v python3 >/dev/null 2>&1 && [[ -f "${SCRIPT_DIR}/tas_report.py" ]]; then
  python3 "${SCRIPT_DIR}/tas_report.py" \
      --raw "$RAW_DIR" --scope "$SCOPE" --stamp "$STAMP" \
      --priv "$PRIV" --out "$REPORT"
  ok "Report written: ${REPORT}"
else
  warn "python3 or tas_report.py missing — writing a raw-output report instead."
  {
    echo "# TAS Network Audit — ${STAMP}"
    echo
    echo "Scope: \`${SCOPE}\`  (raw nmap output; install python3 for the analysed report)"
    echo
    for f in "${RAW_DIR}"/*.nmap; do
      [[ -e "$f" ]] || continue
      echo "## $(basename "$f")"; echo '```'; cat "$f"; echo '```'; echo
    done
  } > "$REPORT"
  ok "Raw report written: ${REPORT}"
fi

echo
ok "Audit complete. Review and commit:"
echo "    git add \"${RUN_DIR}\" && git commit -m \"TAS audit ${STAMP}\""
