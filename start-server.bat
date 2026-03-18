@echo off
chcp 65001 >nul 2>&1
title 네이버 광고 자동화 서버

cd /d "C:\Users\User\Desktop\naver-ads-bot"
echo [%date% %time%] 서버 시작 중... >> logs\server.log 2>&1

:loop
echo [%date% %time%] 서버 실행
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" -B main.py >> logs\server.log 2>&1
echo [%date% %time%] 서버가 종료되었습니다. 10초 후 재시작... >> logs\server.log 2>&1
timeout /t 10 /nobreak >nul
goto loop
