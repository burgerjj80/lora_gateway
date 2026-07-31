<#
.SYNOPSIS
  TAS Network Audit Toolkit — native Windows PowerShell edition.

.DESCRIPTION
  Repeatable discovery + port/service audit + Markdown report for the TAS
  project LAN (e.g. the Orpay 1000 and enhance controller on 192.168.19.0/24).

  Runs entirely on built-in Windows PowerShell — no admin, no WSL, no installs.
  Must be run from a machine that is ON the target network; the Claude Code
  cloud session cannot reach private LAN addresses.

  For deeper service/version + TLS analysis, use the Linux edition
  (tas_audit.sh) with nmap on a machine that has it.

.PARAMETER Subnet
  /24 base to sweep, e.g. "192.168.19". Sweeps .1-.254. Omit to skip discovery.

.PARAMETER Target
  One or more hosts to port-scan in depth. Defaults to every live host found.

.PARAMETER Ports
  TCP ports to probe. Defaults to a common embedded/appliance set.

.PARAMETER OutDir
  Report output directory. Defaults to .\reports next to this script.

.EXAMPLE
  .\tas_audit.ps1 -Subnet 192.168.19 -Target 192.168.19.64

.EXAMPLE
  .\tas_audit.ps1 -Subnet 192.168.19        # sweep + audit every live host
#>
[CmdletBinding()]
param(
  [string]   $Subnet,
  [string[]] $Target = @(),
  [int[]]    $Ports  = @(21,22,23,25,53,80,110,143,161,443,445,993,995,1700,1883,8080,8443,3389,9000),
  [string]   $OutDir
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutDir) { $OutDir = Join-Path $ScriptDir 'reports' }

# Ports that are findings just by being open on an appliance: sev + note + fix
$RiskyPorts = @{
  21   = @('MEDIUM','FTP (cleartext credentials/data)','Disable FTP; use SFTP. No anonymous access.')
  23   = @('HIGH','Telnet (cleartext credentials) — top embedded-device target','Disable Telnet; use SSH. Isolate on a management VLAN if unavoidable.')
  69   = @('MEDIUM','TFTP (unauthenticated firmware access)','Disable unless actively provisioning.')
  161  = @('MEDIUM','SNMP (default community leaks config)','Change community strings / use SNMPv3, or disable.')
  445  = @('MEDIUM','SMB exposed on an appliance','Disable if not needed; restrict to management hosts.')
  3389 = @('MEDIUM','RDP exposed on the LAN','Restrict to jump hosts, enforce NLA + strong creds.')
}

function Test-Port {
  param([string]$Ip,[int]$Port,[int]$TimeoutMs=800)
  $c = New-Object Net.Sockets.TcpClient
  try {
    $iar = $c.BeginConnect($Ip,$Port,$null,$null)
    if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs)) { $c.EndConnect($iar); return $true }
    return $false
  } catch { return $false } finally { $c.Close() }
}

function Invoke-PingSweep {
  param([string]$Base)
  Write-Host "[*] Sweeping $Base.0/24 ..." -ForegroundColor Cyan
  $pings = 1..254 | ForEach-Object {
    $ip = "$Base.$_"
    [pscustomobject]@{ IP = $ip; Task = (New-Object Net.NetworkInformation.Ping).SendPingAsync($ip,600) }
  }
  [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($pings.Task))
  $pings | Where-Object { $_.Task.Result.Status -eq 'Success' } | ForEach-Object { $_.IP }
}

function Get-ArpTable {
  $map = @{}
  (arp -a) 2>$null | ForEach-Object {
    if ($_ -match '^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})') {
      $map[$Matches[1]] = $Matches[2]
    }
  }
  $map
}

function Get-HttpBanner {
  param([string]$Ip,[int]$Port,[bool]$Tls)
  $scheme = if ($Tls) { 'https' } else { 'http' }
  try {
    $raw = cmd /c "curl.exe -ski --max-time 6 $scheme`://$Ip`:$Port/ 2>nul"
    $title = ($raw | Select-String -Pattern '<title>(.*?)</title>' -AllMatches).Matches |
             ForEach-Object { $_.Groups[1].Value } | Select-Object -First 1
    $server = ($raw | Select-String -Pattern '^Server:\s*(.*)$').Matches |
              ForEach-Object { $_.Groups[1].Value } | Select-Object -First 1
    [pscustomobject]@{ Title = $title; Server = $server }
  } catch { [pscustomobject]@{ Title = $null; Server = $null } }
}

# ---- run bookkeeping --------------------------------------------------------
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$runDir  = Join-Path $OutDir "run-$stamp"
$null    = New-Item -ItemType Directory -Force -Path $runDir
$report  = Join-Path $runDir 'report.md'

# ---- Phase 1: discovery -----------------------------------------------------
$live = @()
if ($Subnet) {
  $live = @(Invoke-PingSweep -Base $Subnet)
  Write-Host "[+] $($live.Count) live host(s)." -ForegroundColor Green
}
$arp = Get-ArpTable
$auditHosts = if ($Target.Count -gt 0) { $Target } else { $live }
if (-not $auditHosts -or $auditHosts.Count -eq 0) {
  Write-Warning "No hosts to audit. Pass -Target or a -Subnet that has live hosts."
}

# ---- Phase 2: port audit + findings ----------------------------------------
$hostResults = @()
$findings    = @()
foreach ($h in $auditHosts) {
  Write-Host "[*] Auditing $h ..." -ForegroundColor Cyan
  $open = @()
  foreach ($p in $Ports) { if (Test-Port -Ip $h -Port $p) { $open += $p } }

  $banner = $null
  if ($open -contains 80)  { $banner = Get-HttpBanner -Ip $h -Port 80  -Tls $false }
  elseif ($open -contains 8080) { $banner = Get-HttpBanner -Ip $h -Port 8080 -Tls $false }

  foreach ($p in $open) {
    if ($RiskyPorts.ContainsKey($p)) {
      $r = $RiskyPorts[$p]
      $findings += [pscustomobject]@{ Sev=$r[0]; Host=$h; Port=$p; Detail=$r[1]; Fix=$r[2] }
    }
  }
  if (($open -contains 80) -and ($banner -and ($banner.Title -match 'login|admin|router|gateway|controller|config|setup'))) {
    $findings += [pscustomobject]@{ Sev='MEDIUM'; Host=$h; Port=80;
      Detail="HTTP admin interface over cleartext (title: $($banner.Title))";
      Fix='Serve admin UI over HTTPS only; enforce auth; redirect HTTP->HTTPS.' }
  }
  if ($open -contains 22) {
    $findings += [pscustomobject]@{ Sev='INFO'; Host=$h; Port=22; Detail='SSH reachable';
      Fix='Key-based auth, no root login, current OpenSSH.' }
  }

  $hostResults += [pscustomobject]@{ Host=$h; Mac=$arp[$h]; Open=$open; Banner=$banner }
  Write-Host "    open: $((($open|Sort-Object) -join ', '))" -ForegroundColor Gray
}

# ---- Phase 3: report --------------------------------------------------------
$sevRank = @{ HIGH=0; MEDIUM=1; LOW=2; INFO=3 }
$findings = $findings | Sort-Object @{E={$sevRank[$_.Sev]}}, Host, Port
$counts   = $findings | Group-Object Sev -AsHashTable -AsString

$md = New-Object System.Collections.Generic.List[string]
$md.Add("# TAS Network Audit Report (Windows edition)")
$md.Add("")
$md.Add("- **Run:** ``$stamp``")
$md.Add("- **Subnet:** ``$(if($Subnet){"$Subnet.0/24"}else{'—'})``")
$md.Add("- **Live hosts:** $($live.Count)")
$md.Add("- **Findings:** $(@($findings|?{$_.Sev -eq 'HIGH'}).Count) high · $(@($findings|?{$_.Sev -eq 'MEDIUM'}).Count) medium · $(@($findings|?{$_.Sev -eq 'INFO'}).Count) info")
$md.Add("")
$md.Add("> Heuristic report from native port probing. For service/version + TLS depth, run the nmap edition (tas_audit.sh). Verify each finding manually.")
$md.Add("")
$md.Add("## Host inventory")
$md.Add("")
$md.Add("| Host | MAC | Open ports | Web title |")
$md.Add("|------|-----|-----------|-----------|")
foreach ($hr in $hostResults) {
  $ports = ($hr.Open | Sort-Object) -join ', '
  $title = if ($hr.Banner) { $hr.Banner.Title } else { '' }
  $md.Add("| $($hr.Host) | $(if($hr.Mac){$hr.Mac}else{'—'}) | $(if($ports){$ports}else{'—'}) | $(if($title){$title}else{'—'}) |")
}
$md.Add("")
$md.Add("## Findings (most severe first)")
$md.Add("")
if ($findings.Count -eq 0) { $md.Add("_No heuristic findings from port probing. Review the inventory manually._") }
foreach ($f in $findings) {
  $md.Add("### [$($f.Sev)] $($f.Host):$($f.Port)")
  $md.Add("")
  $md.Add("- **Detail:** $($f.Detail)")
  $md.Add("- **Remediation:** $($f.Fix)")
  $md.Add("")
}
Set-Content -Path $report -Value ($md -join "`r`n") -Encoding UTF8

Write-Host ""
Write-Host "[+] Report: $report" -ForegroundColor Green
Write-Host "[+] Commit it:  git add `"$runDir`"; git commit -m `"TAS audit $stamp`"" -ForegroundColor Green
