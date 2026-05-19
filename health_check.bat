@echo off
chcp 65001 >nul
title Advanced Biometric Application - Health Check
echo ===============================================
echo    Advanced Biometric Application Health Check
echo ===============================================
echo.

cd /d "%~dp0"

python -c "
import sys, os
sys.path.insert(0, '.')

errors = []
warnings = []

# 1. Python version
if sys.version_info < (3, 8):
    errors.append(f'Python 3.8+ required (found {sys.version})')
else:
    print(f'[OK]   Python {sys.version.split()[0]}')

# 2. Dependencies
for pkg in ['requests', 'sqlite3']:
    try:
        __import__(pkg)
        print(f'[OK]   {pkg}')
    except ImportError:
        errors.append(f'Missing dependency: {pkg}')

# 3. Config file
import json
from pathlib import Path
cfg_path = Path('config/default_config.json')
if not cfg_path.exists():
    errors.append('config/default_config.json not found')
else:
    try:
        cfg = json.loads(cfg_path.read_text())
        print('[OK]   config/default_config.json found')
        # Warn about placeholders
        url = cfg.get('server', {}).get('url', '')
        if 'example.com' in url or url == '':
            warnings.append('Server URL not configured (sync disabled)')
        devs = cfg.get('devices', [])
        enabled = [d for d in devs if d.get('enabled', False)]
        if not enabled:
            warnings.append('No devices enabled in config')
        else:
            print(f'[OK]   {len(enabled)} device(s) enabled')
    except Exception as e:
        errors.append(f'Config parse error: {e}')

# 4. Directories
for d in ['data', 'logs', 'config']:
    Path(d).mkdir(parents=True, exist_ok=True)
    print(f'[OK]   {d}/ directory exists')

# 5. License
lic_path = Path('config/license.json')
if not lic_path.exists():
    warnings.append('No license.json found - app will auto-generate trial on first run')
else:
    try:
        lic = json.loads(lic_path.read_text())
        from datetime import datetime
        exp = datetime.fromisoformat(lic.get('expiry_date','2000-01-01'))
        if datetime.now() > exp:
            errors.append(f'License expired on {exp.date()}')
        else:
            remaining = (exp - datetime.now()).days
            print(f'[OK]   License valid ({remaining} days remaining)')
    except Exception as e:
        warnings.append(f'License check error: {e}')

# 6. Database
try:
    import sqlite3
    from pathlib import Path
    db_path = cfg.get('database',{}).get('path','data/att.db') if 'cfg' in dir() else 'data/att.db'
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.close()
    print(f'[OK]   Database accessible: {db_path}')
except Exception as e:
    errors.append(f'Database error: {e}')

# Summary
print()
for w in warnings:
    print(f'[WARN] {w}')
for e in errors:
    print(f'[FAIL] {e}')

if errors:
    print()
    print('Health check FAILED. Fix the errors above before starting.')
    sys.exit(1)
else:
    print()
    print('Health check PASSED. Application is ready to start.')
    sys.exit(0)
"

if %errorlevel% equ 0 (
    echo.
    echo Run scripts\run_app.bat to start the application.
) else (
    echo.
    echo Please fix the issues above. See README.md for help.
)
echo.
pause
