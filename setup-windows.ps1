#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Sets up the Everpure ZTP File Server on Windows.
.DESCRIPTION
    Installs Flask, creates the files directory, opens port 8080 in Windows Firewall,
    and optionally registers a persistent Windows Service via NSSM.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AppPy     = Join-Path $ScriptDir "app.py"
$FilesDir  = Join-Path $ScriptDir "files"

Write-Host "=== Everpure ZTP File Server Setup (Windows) ===" -ForegroundColor Cyan

# ── 1. Verify Python 3 ─────────────────────────────────────────────────────────
$PythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3") {
            $PythonExe = $candidate
            Write-Host "[+] Found: $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $PythonExe) {
    Write-Host ""
    Write-Host "[!] Python 3 not found." -ForegroundColor Red
    Write-Host "    Download and install it from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "    Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    exit 1
}

# ── 2. Install Flask ───────────────────────────────────────────────────────────
Write-Host "[+] Installing Flask..."
& $PythonExe -m pip install --quiet flask
Write-Host "[+] Flask installed." -ForegroundColor Green

# ── 3. Create files directory ──────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $FilesDir | Out-Null
Write-Host "[+] Files directory: $FilesDir"

# ── 4. Open Windows Firewall ───────────────────────────────────────────────────
Write-Host "[+] Opening port 8080 in Windows Firewall..."
$existingRule = netsh advfirewall firewall show rule name="ZTP File Server" 2>&1
if ($existingRule -notmatch "No rules match") {
    netsh advfirewall firewall delete rule name="ZTP File Server" | Out-Null
}
netsh advfirewall firewall add rule `
    name="ZTP File Server" `
    dir=in `
    action=allow `
    protocol=TCP `
    localport=8080 | Out-Null
Write-Host "[+] Firewall rule added." -ForegroundColor Green

# ── 5. Windows Service via NSSM (optional) ─────────────────────────────────────
$NssmPath = Get-Command nssm -ErrorAction SilentlyContinue
if ($NssmPath) {
    Write-Host "[+] NSSM found — registering 'fileserver' Windows Service..."

    $PythonFull = (Get-Command $PythonExe).Source

    # Remove existing service if present
    $existing = nssm status fileserver 2>&1
    if ($existing -notmatch "The specified service does not exist") {
        nssm stop fileserver confirm 2>&1 | Out-Null
        nssm remove fileserver confirm 2>&1 | Out-Null
    }

    nssm install fileserver $PythonFull $AppPy
    nssm set fileserver AppDirectory $ScriptDir
    nssm set fileserver AppEnvironmentExtra "FILE_SERVER_ROOT=$FilesDir"
    nssm set fileserver Description "Everpure ZTP File Server"
    nssm start fileserver

    Write-Host ""
    Write-Host "=== Done ===" -ForegroundColor Cyan
    Write-Host "Service 'fileserver' is running." -ForegroundColor Green
    Write-Host ""
    Write-Host "Service management:"
    Write-Host "  nssm stop fileserver"
    Write-Host "  nssm start fileserver"
    Write-Host "  nssm restart fileserver"
} else {
    Write-Host ""
    Write-Host "=== Done ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[i] NSSM not found — the server was NOT registered as a Windows Service." -ForegroundColor Yellow
    Write-Host "    To run the server now, execute:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      cd `"$ScriptDir`""
    Write-Host "      `$env:FILE_SERVER_ROOT=`"$FilesDir`"; $PythonExe app.py"
    Write-Host ""
    Write-Host "    To run it as a persistent service, install NSSM (free) from:" -ForegroundColor Yellow
    Write-Host "      https://nssm.cc/download" -ForegroundColor Yellow
    Write-Host "    Then re-run this script."
}

# Resolve host IP for access URL
$HostIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "Access the file server at: http://${HostIp}:8080/" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: ZTP FlashArray Install and Initialize are fully supported on Windows." -ForegroundColor White
Write-Host "      The DHCP Server feature requires Linux and is not available on Windows." -ForegroundColor DarkGray
