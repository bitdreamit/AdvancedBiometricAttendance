@echo off
chcp 65001 >nul
title Advanced Biometric Application - License Activation
echo ===============================================
echo    License Activation
echo ===============================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Run install.bat first.
    pause & exit /b 1
)

python -c "
import sys
sys.path.insert(0, '.')
from src.utils.license_manager import LicenseManager

print('Enter your 32-character license key.')
print('(Run: python generate_license.py  to create one)')
print()

key = input('License Key: ').strip()
if not key:
    print('No key entered. Exiting.')
    sys.exit(0)

m = LicenseManager()
ok, msg = m.activate_license(key)

if ok:
    print()
    print('[OK]  ' + msg)
    info = m.get_license_info()
    print()
    print('License details:')
    for k, v in info.items():
        if k != 'license_key':
            print(f'  {k.replace(\"_\",\" \").title():20}: {v}')
else:
    print()
    print('[FAIL] ' + msg)
    sys.exit(1)
"

echo.
pause
