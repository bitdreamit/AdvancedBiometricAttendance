@echo off
chcp 65001 >nul
title Advanced Biometric — Batch Attendance Pull

cd /d "%~dp0\.."

echo ============================================================
echo    Advanced Biometric — Batch Attendance Pull
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Run install.bat first.
    pause & exit /b 1
)

echo  Choose pull mode:
echo.
echo  [1] Pull all records (one time)
echo  [2] Pull last 24 hours only
echo  [3] Pull and sync to server
echo  [4] Pull and clear device log
echo  [5] Pull in loop every 5 minutes
echo  [6] Exit
echo.
set /p CHOICE=Enter choice [1-6]: 

if "%CHOICE%"=="1" (
    python batch_pull_attendance.py
)
if "%CHOICE%"=="2" (
    python batch_pull_attendance.py --hours 24
)
if "%CHOICE%"=="3" (
    python batch_pull_attendance.py --sync
)
if "%CHOICE%"=="4" (
    echo.
    echo WARNING: This will erase attendance records from the device!
    set /p CONFIRM=Are you sure? [Y/N]: 
    if /i "%CONFIRM%"=="Y" (
        python batch_pull_attendance.py --clear
    ) else (
        echo Cancelled.
    )
)
if "%CHOICE%"=="5" (
    echo Running in loop mode. Press Ctrl+C to stop.
    python batch_pull_attendance.py --loop 300
)
if "%CHOICE%"=="6" (
    exit /b 0
)

echo.
pause
