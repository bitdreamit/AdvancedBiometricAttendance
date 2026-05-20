@echo off
chcp 65001 >nul
title Advanced Biometric — Device Auto-Discovery

cd /d "%~dp0\.."

echo ============================================================
echo    Advanced Biometric — Device Auto-Discovery
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Run install.bat first.
    pause & exit /b 1
)

echo  This will scan your local network for ZKTeco devices.
echo  It takes about 5-15 seconds.
echo.

set /p SAVE=Save found devices to config automatically? [Y/N]: 

if /i "%SAVE%"=="Y" (
    echo.
    echo Scanning and saving to config...
    echo.
    python auto_detect_devices.py --save
) else (
    echo.
    echo Scanning (read-only)...
    echo.
    python auto_detect_devices.py
)

echo.
if %errorlevel% equ 0 (
    echo Done! Run health_check.bat to verify, then scripts\run_app.bat to start.
) else (
    echo No devices found. Check that your device is powered on and connected.
)
echo.
pause
