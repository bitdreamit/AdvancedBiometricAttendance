@echo off
chcp 65001 >nul
title Advanced Biometric Application - Installer
echo ===============================================
echo    Advanced Biometric Application Installer
echo ===============================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python is not installed or not in PATH.
    echo        Download from https://python.org  (tick "Add Python to PATH")
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK]   Python %PY_VER% found

:: Create directory structure
echo.
echo Creating directories...
if not exist data   mkdir data
if not exist logs   mkdir logs
if not exist config mkdir config
echo [OK]   Directories created

:: Install Python dependencies
echo.
echo Installing Python dependencies...
pip install requests>=2.28.0 psutil>=5.9.0 --quiet
if errorlevel 1 (
    echo [FAIL] pip install failed. Check internet connection.
    pause & exit /b 1
)
echo [OK]   Dependencies installed

:: Copy default config if not present
if not exist config\default_config.json (
    echo [OK]   Using default_config.json from project root
) else (
    echo [OK]   config\default_config.json already exists
)

:: Generate trial license if none exists
if not exist config\license.json (
    echo.
    echo Generating 30-day trial license...
    python generate_license.py --auto-trial >nul 2>&1
    python -c "
import sys
sys.path.insert(0,'.')
from src.utils.license_manager import LicenseManager
m=LicenseManager()
k=m.generate_license('Trial User',1,30)
print('[OK]   Trial license generated: '+k[:8]+'...')
"
)

echo.
echo ===============================================
echo    Installation Complete
echo ===============================================
echo.
echo Next steps:
echo  1. Edit config\default_config.json
echo       - Set your device IP and serial number
echo       - Set your server URL and API key (optional)
echo       - Set "enabled": true for each device
echo  2. Run health_check.bat to verify everything
echo  3. Run scripts\run_app.bat to start
echo.
pause
