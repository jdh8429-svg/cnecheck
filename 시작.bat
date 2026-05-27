@echo off
chcp 65001 > nul

:: 기존 서버 종료
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo  ┌───────────────────────────────────────┐
echo  │   한글 유틸리티 서버 시작             │
echo  │   http://localhost:5000               │
echo  └───────────────────────────────────────┘
echo.
echo  서버가 시작되면 브라우저에서 아래 주소로 접속하세요:
echo  http://localhost:5000
echo.
echo  서버를 종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo.
cd /d "%~dp0"
python server.py
pause
