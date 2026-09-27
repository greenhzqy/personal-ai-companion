' Run the watchdog with NO console window.
'
' A scheduled task that launches powershell.exe directly flashes a black
' window every single time it runs -- every 10 minutes, forever. wscript
' with Run(..., 0, ...) does not: the 0 means "hidden window".
'
' The script path is derived from this file's own location, so the folder
' can live anywhere. Nothing here is machine-specific.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set s = CreateObject("WScript.Shell")
s.Run "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & here & "\_watchdog.ps1""", 0, False
