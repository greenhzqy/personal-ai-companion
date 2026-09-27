# ============================================================
#  _watchdog.ps1  --  self-healing for an unattended machine
#
#  WHY: if the machine sits at a desk and is driven remotely,
#  anything that dies silently STAYS dead until somebody happens
#  to look. This runs every few minutes and repairs what is missing.
#
#  PORTABLE ON PURPOSE: nothing here is machine-specific.
#  Node is taken from PATH (with one fallback), the wallpaper
#  engine path is overridable by an env var, and everything is
#  relative to this script's own folder.
#
#  ASCII-only on purpose (PS 5.1 mis-reads BOM-less UTF-8).
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir
$log = Join-Path $dir "_watchdog.log"

$PORT = if ($env:COMPANION_PORT) { [int]$env:COMPANION_PORT } else { 8765 }

function Note($m) {
  Add-Content -Path $log -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + "  " + $m) -Encoding UTF8
}

# Is something listening on this port?
# Do NOT use Get-NetTCPConnection for this: with insufficient rights it
# returns NOTHING instead of throwing, so a healthy server looks dead and
# you start a second one. A raw TCP connect cannot fail that way.
function Test-Port([int]$p) {
  $c = $null
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $iar = $c.BeginConnect("127.0.0.1", $p, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(500)
    $connected = ($ok -and $c.Connected)
    $c.Close()
    return $connected
  } catch {
    if ($c) { try { $c.Close() } catch {} }
    return $false
  }
}

# --- 1) the local server ---
if (-not (Test-Port $PORT)) {
  $node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
  if (-not $node) { $node = "C:\Program Files\nodejs\node.exe" }
  if (Test-Path $node) {
    Start-Process -FilePath $node -ArgumentList "sense-server.js" -WorkingDirectory $dir -WindowStyle Hidden
    # Verify the start actually worked. Without this the log claims
    # "restarted" forever while the port stays dead (missing file, bad
    # syntax, port taken) -- a watchdog that lies is worse than none.
    $ok = $false
    for ($i = 0; $i -lt 10; $i++) {
      Start-Sleep -Milliseconds 300
      if (Test-Port $PORT) { $ok = $true; break }
    }
    if ($ok) { Note "server restarted" } else { Note "server start FAILED (port $PORT still closed)" }
  } else {
    Note "server DOWN and node.exe not found"
  }
}

# --- 2) the keyboard watcher ---
# Match on the COMMAND LINE, never on the process name.
# The wrong way -- tasklist /fi "IMAGENAME eq powershell.exe" | findstr powershell --
# is ALWAYS true (whatever launched it spawned powershell itself), so every
# logon adds one more copy. This project really did accumulate 3 that way.
#
# AND match on THIS folder's script, not just its filename: someone can easily
# have a second copy of this project (or of this very scaffold) running, and a
# loose match like "*_keywatch.ps1*" would then treat THEIR watcher as ours.
#
# DETECTION IS PID-FILE FIRST, and that is deliberate. Asking WMI/CIM is not
# reliable either: with insufficient rights, or with WMI disabled, Get-CimInstance
# returns NOTHING instead of throwing -- a running watcher then looks dead and
# the watchdog spawns a duplicate on EVERY run, silently and forever. (Measured:
# with CIM denied, two consecutive runs both logged "keywatch restarted".)
# A PID file cannot fail that way.
$kwScript = Join-Path $dir "_keywatch.ps1"
$pidFile  = Join-Path $dir "_keywatch.pid"

$running = $false
if (Test-Path $pidFile) {
  $kpid = 0
  [void][int]::TryParse((Get-Content $pidFile -Raw -ErrorAction SilentlyContinue), [ref]$kpid)
  if ($kpid -gt 0) {
    $proc = Get-Process -Id $kpid -ErrorAction SilentlyContinue
    # require it to be a powershell too, so a recycled PID cannot fool us
    if ($proc -and $proc.ProcessName -like "powershell*") { $running = $true }
  }
  if (-not $running) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }   # stale
}

if (-not $running) {
  Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
    "-NoProfile","-NonInteractive","-WindowStyle","Hidden","-ExecutionPolicy","Bypass",
    "-File", $kwScript)
  Note "keywatch restarted"
} else {
  # Best-effort cleanup of genuine duplicates of OUR OWN watcher, scoped to this
  # exact script path. If CIM is unavailable this silently does nothing -- which
  # is fine, because detection above never depended on it.
  $kw = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like ("*" + $kwScript + "*")) }
  if (@($kw).Count -gt 1) {
    $extra = @($kw) | Sort-Object CreationDate | Select-Object -Skip 1
    foreach ($p in $extra) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Note ("removed " + @($extra).Count + " duplicate keywatch")
  }
}

# --- 3) the wallpaper host (optional) ---
# Without the host there is nothing on screen. Set HOST_EXE if yours
# lives somewhere unusual; otherwise we look in the usual places.
$hostName = if ($env:COMPANION_HOST_NAME) { $env:COMPANION_HOST_NAME } else { "Lively" }
if (-not (Get-Process -Name $hostName -ErrorAction SilentlyContinue)) {
  $cand = @($env:HOST_EXE,
            (Join-Path $env:LOCALAPPDATA "Programs\Lively Wallpaper\Lively.exe"),
            (Join-Path ${env:ProgramFiles} "Lively Wallpaper\Lively.exe")) |
          Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if ($cand) { Start-Process -FilePath $cand; Note "host restarted" }
  else { Note "host not running and no executable found" }
}

# --- 4) keep the log from growing forever ---
if (Test-Path $log) {
  $c = @(Get-Content $log)
  if ($c.Count -gt 400) { $c | Select-Object -Last 200 | Set-Content $log -Encoding UTF8 }
}
