@echo off
chcp 65001 >nul
echo.
echo  ============================================
echo    배포용 ZIP 파일 생성
echo  ============================================
echo.
cd /d "%~dp0"

set "DIST_NAME=광고자동화"
set "DIST_DIR=%TEMP%\%DIST_NAME%"

:: 기존 임시 폴더 삭제
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%"
mkdir "%DIST_DIR%\core"
mkdir "%DIST_DIR%\templates"
mkdir "%DIST_DIR%\downloads"
mkdir "%DIST_DIR%\logs"

:: 핵심 파일 복사
echo  파일 복사 중...
copy /y main.py "%DIST_DIR%\" >nul
copy /y web_app.py "%DIST_DIR%\" >nul
copy /y requirements.txt "%DIST_DIR%\" >nul
copy /y config.template.json "%DIST_DIR%\" >nul
copy /y 광고자동화_실행.bat "%DIST_DIR%\" >nul
copy /y 광고자동화_시작.vbs "%DIST_DIR%\" >nul

:: core 폴더 (Python 파일만)
for %%f in (core\*.py) do copy /y "%%f" "%DIST_DIR%\core\" >nul

:: templates 폴더
for %%f in (templates\*.html) do copy /y "%%f" "%DIST_DIR%\templates\" >nul

:: config.json은 복사하지 않음 (개인 정보 보호)
:: .env, __pycache__, logs, downloads 내용도 복사하지 않음

:: ZIP 생성
echo  ZIP 파일 생성 중...
set "ZIP_PATH=%~dp0%DIST_NAME%.zip"
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ZIP_PATH%' -Force"

:: 임시 폴더 삭제
rmdir /s /q "%DIST_DIR%"

echo.
if exist "%ZIP_PATH%" (
    echo  ============================================
    echo    완료! 아래 파일을 전달하세요:
    echo    %ZIP_PATH%
    echo  ============================================
) else (
    echo  ※ ZIP 생성 실패
)
echo.
pause
