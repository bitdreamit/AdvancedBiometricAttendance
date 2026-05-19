@echo off
chcp 65001 >nul
title Advanced Biometric Application - Install Service

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Must be run as Administrator. Right-click → Run as administrator.
    pause & exit /b 1
)

cd /d "%~dp0\.."

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Run install.bat first.
    pause & exit /b 1
)

echo Installing Windows service...
python src\main.py --install-service

if %errorlevel% equ 0 (
    echo [OK]   Service installed. Starting...
    sc start AdvancedBiometric
    if %errorlevel% equ 0 (
        echo [OK]   Service started successfully.
    ) else (
        echo [WARN] Service installed but did not start automatically.
        echo        Try: sc start AdvancedBiometric
    )
) else (
    echo [FAIL] Service installation failed. Check logs\app.log
)
echo.
pause
