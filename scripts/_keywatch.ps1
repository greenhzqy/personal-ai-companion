# ============================================================
#  _keywatch.ps1  --  let the companion follow your typing
#
#  Polls GetAsyncKeyState, batches, POSTs VIRTUAL KEY CODES to the
#  local server. The wallpaper long-polls that endpoint, so a key
#  press reaches the screen in ~10-90ms.
#
#  PRIVACY -- these are design decisions, do NOT "optimise" them away:
#    * only virtual key codes leave this script; nothing is ever
#      translated into characters, so nobody can reconstruct what
#      you typed (no Shift/CapsLock state is reported either)
#    * nothing is written to disk here
#    * the server keeps only "last keys + a counter", in memory
#
#  WHY POLLING AND NOT A LOW-LEVEL HOOK:
#    A WH_KEYBOARD_LL hook injects into the Windows input chain,
#    slows down real input in games, and is exactly what antivirus
#    flags. Polling is fast enough and is a normal API call.
#
#  ASCII-only on purpose (PS 5.1 mis-reads BOM-less UTF-8).
# ============================================================
param(
  [string]$Url = "http://127.0.0.1:8765/keys",
  [int]$SampleMs = 24,      # how often we look at the keyboard
  [int]$BatchMs = 90,       # how often we ship what we saw
  [string]$PidFile = ""
)

$ErrorActionPreference = "SilentlyContinue"

# Announce ourselves with a PID file.
# The watchdog needs a reliable way to answer "is the watcher running?".
# Asking WMI/CIM is NOT reliable: with insufficient rights, or with WMI
# disabled, it returns NOTHING instead of throwing -- so a running watcher
# looks dead and the watchdog spawns another copy on every single run.
# A PID file next to this script cannot fail that way.
if (-not $PidFile) { $PidFile = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "_keywatch.pid" }
try { [System.IO.File]::WriteAllText($PidFile, [string]$PID) } catch { }

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class GreenKeys {
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vKey);
}
"@

# The keys we care about. Trim or extend to taste -- the wallpaper only
# needs to know WHICH key lit up, so a keyboard-shaped set is enough.
$VKS = New-Object System.Collections.Generic.List[int]
# letters A-Z, digits 0-9
65..90  | ForEach-Object { $VKS.Add($_) }
48..57  | ForEach-Object { $VKS.Add($_) }
# F1-F12
112..123 | ForEach-Object { $VKS.Add($_) }
# arrows, space, enter, tab, backspace, esc
@(37,38,39,40,32,13,9,8,27) | ForEach-Object { $VKS.Add($_) }
# punctuation row (OEM keys)
@(186,187,188,189,190,191,192,219,220,221,222) | ForEach-Object { $VKS.Add($_) }

$prev = @{}
foreach ($vk in $VKS) { $prev[$vk] = $false }

$pending = New-Object System.Collections.Generic.List[int]
$lastPost = [DateTime]::UtcNow
$lastSample = [DateTime]::UtcNow

while ($true) {
  $now = [DateTime]::UtcNow

  # --- sample ---
  if (($now - $lastSample).TotalMilliseconds -ge $SampleMs) {
    $lastSample = $now
    foreach ($vk in $VKS) {
      $down = ([GreenKeys]::GetAsyncKeyState($vk) -band 0x8000) -ne 0
      if ($down -and -not $prev[$vk]) { $pending.Add($vk) }   # edge, so no auto-repeat spam
      $prev[$vk] = $down
    }
  }

  # --- ship ---
  if ($pending.Count -gt 0 -and ($now - $lastPost).TotalMilliseconds -ge $BatchMs) {
    $batch = @($pending.GetRange(0, [Math]::Min($pending.Count, 32)))
    $pending.Clear()
    $lastPost = $now
    $body = @{ vks = $batch } | ConvertTo-Json -Compress
    try {
      Invoke-RestMethod -Uri $Url -Method Post -Body $body -ContentType "application/json" -TimeoutSec 3 | Out-Null
    } catch {
      # server not up yet -- drop the batch, never buffer to disk
    }
  }

  Start-Sleep -Milliseconds 8
}
