@echo off
chcp 65001 >nul
title Advanced Biometric Application - Uninstall Service

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Must be run as Administrator.
    pause & exit /b 1
)

cd /d "%~dp0\.."

echo Stopping service...
sc stop AdvancedBiometric >nul 2>&1
timeout /t 3 /nobreak >nul

echo Uninstalling service...
python src\main.py --uninstall-service

if %errorlevel% neq 0 (
    echo Trying fallback removal...
    sc delete AdvancedBiometric
)

echo Done.
pause
