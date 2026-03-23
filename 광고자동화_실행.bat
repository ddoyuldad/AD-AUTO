@echo off
chcp 65001 >nul
title 광고 자동화
echo.
echo  ============================================
echo    광고 자동화 설치 및 실행
echo  ============================================
echo.
cd /d "%~dp0"

:: Python 설치 확인
echo  [1/3] Python 확인 중...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ※ Python이 설치되어 있지 않습니다.
    echo.
    echo  아래 링크에서 Python을 설치해주세요:
    echo  https://www.python.org/downloads/
    echo.
    echo  설치 시 "Add Python to PATH" 체크 필수!
    echo.
    pause
    exit /b
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo  ※ %%i 확인 완료

:: 패키지 설치
echo.
echo  [2/3] 필요한 패키지 설치 중...
pip install -r requirements.txt -q >nul 2>&1
if %errorlevel% neq 0 (
    echo  ※ 패키지 설치 중 오류 발생. 수동 설치를 시도합니다...
    pip install requests APScheduler Jinja2 flask selenium webdriver-manager openpyxl -q
)
echo  ※ 패키지 설치 완료

:: config.json 존재 여부 확인
echo.
if not exist "config.json" (
    echo  ※ 첫 실행 감지 - 초기 설정 모드로 시작합니다.
    echo  ※ 브라우저에서 계정 정보를 입력해주세요.
) else (
    echo  ※ 설정 파일 확인 완료
)

:: 3초 후 브라우저 자동 오픈
echo.
echo  [3/3] 프로그램 시작 중...
echo.
echo  ============================================
echo    대시보드: http://localhost:5000
echo    종료하려면 이 창을 닫으세요.
echo  ============================================
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"
python main.py
pause
