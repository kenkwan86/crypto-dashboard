' Launches run_hourly.ps1 with no visible window. wscript.exe is a GUI-subsystem
' binary, so no console is ever created. Used by the "CryptoDashboardHourly" task.
Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\01. Coding\Crypto-Dashboard\tools\run_hourly.ps1"""
exitCode = shell.Run(cmd, 0, True)
WScript.Quit exitCode
