@echo off
chcp 65001 >nul
title Advanced Biometric Application

cd /d "%~dp0\.."

echo ===============================================
echo    Advanced Biometric Application
echo ===============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Run install.bat first.
    pause & exit /b 1
)

if not exist data   mkdir data
if not exist logs   mkdir logs
if not exist config mkdir config

if not exist config\license.json (
    echo [INFO] No license found - a 30-day trial will be auto-generated.
    timeout /t 2 /nobreak >nul
)

echo Starting application... Press Ctrl+C to stop.
echo.
python src\main.py %*

if %errorlevel% equ 0 (
    echo. & echo Application stopped normally.
) else (
    echo. & echo Application stopped with error code %errorlevel%.
    echo Check logs\app.log for details.
)
echo.
pause
