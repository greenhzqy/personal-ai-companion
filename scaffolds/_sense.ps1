# ============================================================
#  _sense.ps1  --  read "am I at the computer, and what am I doing"
#
#  Emits ONE json object describing the current user state:
#     { idleSec, proc, title, activity }
#
#  WHY THIS FILE IS ASCII-ONLY:
#     Windows PowerShell 5.1 reads a BOM-less UTF-8 script as ANSI/GBK,
#     which corrupts any non-ASCII text and can even break parsing.
#     Keeping this script ASCII avoids that whole class of bug.
#
#  WHY IT WRITES TO A FILE INSTEAD OF STDOUT:
#     Some environments (sandboxes, restricted hosts) forbid a child
#     process from using piped stdio -- node's spawn/execFile then fails
#     with EPERM. Writing the result to a file the caller names, and
#     spawning with stdio ignored, works everywhere.
#
#  USAGE:
#     powershell -NoProfile -ExecutionPolicy Bypass -File _sense.ps1 -Out <path>
# ============================================================
param(
  [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = "SilentlyContinue"

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class GreenSense {
    [StructLayout(LayoutKind.Sequential)]
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }

    [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);

    public static uint LastInputTick() {
        LASTINPUTINFO li = new LASTINPUTINFO();
        li.cbSize = (uint)Marshal.SizeOf(li);
        GetLastInputInfo(ref li);
        return li.dwTime;
    }
}
"@

# --- idle seconds ---
# TickCount is a 32-bit wrapping counter; do the subtraction modulo 2^32
# so the result stays correct across the wrap.
$now = [uint32](([Environment]::TickCount) -band 0xFFFFFFFF)
$last = [GreenSense]::LastInputTick()
$diff = [uint32](($now - $last) -band 0xFFFFFFFF)
$idleSec = [Math]::Round($diff / 1000.0, 1)

# --- foreground process + window title ---
$proc = ""
$title = ""
try {
  $hwnd = [GreenSense]::GetForegroundWindow()
  if ($hwnd -ne [IntPtr]::Zero) {
    $len = [GreenSense]::GetWindowTextLength($hwnd)
    if ($len -gt 0) {
      $sb = New-Object System.Text.StringBuilder ($len + 1)
      [void][GreenSense]::GetWindowText($hwnd, $sb, $sb.Capacity)
      $title = $sb.ToString()
    }
    $pid_ = 0
    [void][GreenSense]::GetWindowThreadProcessId($hwnd, [ref]$pid_)
    if ($pid_ -gt 0) { $proc = (Get-Process -Id $pid_).ProcessName }
  }
} catch { }

# --- classify what he is doing ---
# Extend these lists with whatever YOU actually use. Lowercase matching.
$map = @{
  "code"     = @("code","devenv","idea64","pycharm64","webstorm64","sublime_text","notepad++","cursor","zed")
  "terminal" = @("windowsterminal","powershell","pwsh","cmd","conhost","wt","alacritty","wezterm")
  "browse"   = @("chrome","msedge","firefox","brave","opera","quark","360se","sogouexplorer")
  "chat"     = @("wechat","qq","telegram","discord","slack","dingtalk","feishu","lark")
  "game"     = @("steam","steamwebhelper","genshinimpact","yuanshen","leagueclient")
  "video"    = @("potplayer","vlc","mpc-hc64","bilibili","youku")
  "doc"      = @("winword","excel","powerpnt","wps","et","wpp","typora","obsidian","notion")
}
$activity = "other"
$p = $proc.ToLower()
foreach ($k in $map.Keys) {
  if ($map[$k] -contains $p) { $activity = $k; break }
}

$obj = [ordered]@{
  ok       = $true
  idleSec  = $idleSec
  proc     = $proc
  title    = $title
  activity = $activity
  at       = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
}

# charset matters: callers that read this as Latin-1 will mangle CJK titles
$json = $obj | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($Out, $json, (New-Object System.Text.UTF8Encoding($false)))
