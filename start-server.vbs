Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\User\Desktop\naver-ads-bot"
WshShell.Run """C:\Users\User\AppData\Local\Programs\Python\Python313\pythonw.exe"" -B main.py", 0, False
