Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = appDir
sh.Run """" & appDir & "\.venv\Scripts\pythonw.exe"" """ & appDir & "\main.py""", 0, False
