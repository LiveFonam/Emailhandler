# Launch script (double-clickable wrapper).
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "powershell.exe" & chr(34) & " -NoProfile -ExecutionPolicy Bypass -File """ & Replace(WScript.ScriptFullName, "launch.vbs", "launch.ps1") & """", 1, False
Set WshShell = Nothing
