@echo off
rem ============================================================
rem  autostart.bat  --  silent start of everything
rem
rem  ASCII ONLY, on purpose. A .bat containing non-ASCII text is read
rem  by cmd as GBK; if the file was saved as UTF-8 the paths turn into
rem  garbage and autostart silently registers a path that does not
rem  exist -- with NO error message.
rem
rem  NOTE: this only runs at LOGON (HKCU\...\Run). A machine that
rem  reboots and stops at the login screen never runs it -- that is
rem  exactly what _watchdog.ps1 (a scheduled task) is for.
rem ============================================================
cd /d "%~dp0"

rem --- 1) local server on 127.0.0.1:8765 ---
netstat -aon | findstr ":8765" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
  start "" /min powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "node sense-server.js"
  timeout /t 2 /nobreak >nul
)

rem --- 2) the keyboard watcher is owned by the watchdog, not by us ---
rem  Starting it here with a process-name check is the classic bug:
rem     tasklist /fi "IMAGENAME eq powershell.exe" | findstr powershell
rem  is ALWAYS true, so every logon adds one more copy. Let the
rem  watchdog do it -- it matches on the command line and kills extras.
start "" /min wscript.exe "%~dp0_watchdog.vbs"

exit /b 0
