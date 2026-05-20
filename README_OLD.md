# Advanced Biometric Application

A production-ready Python application for ZKTeco biometric attendance device management.
Captures live attendance events, stores them in SQLite, and syncs to a remote server.

---

## Table of Contents
1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Application](#running-the-application)
5. [License Management](#license-management)
6. [Windows Service](#windows-service)
7. [Testing Device Connection](#testing-device-connection)
8. [Building an Executable](#building-an-executable)
9. [Directory Structure](#directory-structure)
10. [Troubleshooting](#troubleshooting)
11. [Bug Fixes Applied](#bug-fixes-applied)

---

## Requirements

| Component | Version |
|-----------|---------|
| Python    | 3.8 or higher |
| OS        | Windows 10/11 (recommended); Linux supported for dev/testing |
| Device    | ZKTeco biometric device on the local network |
| Network   | Device reachable on TCP port 4370 |

---

## Installation

### Step 1 — Install Python
Download from https://python.org and **tick "Add Python to PATH"** during setup.
Verify: open Command Prompt and run `python --version`

### Step 2 — Get the project
```
Unzip AdvancedBiometricApplication.zip  (or clone from GitHub)
```

### Step 3 — Run the installer
Double-click **`install.bat`** (or run in Command Prompt):
```bat
install.bat
```
This will:
- Create `data/`, `logs/`, `config/` directories
- Install Python dependencies (`requests`, `psutil`)
- Generate a 30-day trial license automatically

### Step 4 — Edit the configuration
Open **`config/default_config.json`** in Notepad or any text editor.

Minimum required changes:

```json
"devices": [
  {
    "ip": "192.168.1.201",          ← Change to your device IP
    "port": 4370,
    "serial_number": "ABC123456",   ← Change to your device serial number
    "name": "Main Entrance",
    "enabled": true,                ← Change false → true
    "timeout": 30,
    "sync_time": true
  }
],
"server": {
  "url": "https://your-site.com/", ← Your server URL (leave blank to disable sync)
  "api_key": "your_api_key",       ← Your server API key
  "sync_enabled": true
}
```

To find your device serial number: check the label on the back of the device,
or use the device's built-in menu → System Info.

### Step 5 — Health check
```bat
health_check.bat
```
All lines should show `[OK]`. Fix any `[FAIL]` items before continuing.

---

## Configuration

Full reference for `config/default_config.json`:

```json
{
  "database": {
    "path": "data/att.db",       // SQLite file location
    "auto_create": true          // Create DB tables on startup
  },
  "logging": {
    "level": "INFO",             // DEBUG | INFO | WARNING | ERROR
    "file": "logs/app.log",
    "max_size_mb": 10,
    "backup_count": 5            // Number of rotated log files to keep
  },
  "sync": {
    "interval_seconds": 300,     // How often to push records to server (seconds)
    "retry_attempts": 3,
    "retry_delay_seconds": 60,
    "batch_size": 100            // Max records per sync batch
  },
  "devices": [
    {
      "ip": "192.168.1.201",     // Device IP on local network
      "port": 4370,              // ZKTeco default port (do not change)
      "serial_number": "SN001",  // Device serial number (unique identifier)
      "name": "Front Door",      // Friendly name for logs
      "enabled": true,           // Set false to skip this device
      "timeout": 30,             // Connection timeout in seconds
      "sync_time": true          // Sync device clock to PC on connect
    }
  ],
  "server": {
    "url": "https://example.com/", // Leave empty "" to disable server sync
    "api_key": "abc123",           // Sent as Bearer token in Authorization header
    "sync_enabled": true,
    "verify_ssl": true,            // Set false only for self-signed certs in dev
    "timeout": 30
  }
}
```

**Multiple devices** — add more objects to the `devices` array:
```json
"devices": [
  { "ip": "192.168.1.201", "serial_number": "SN001", "enabled": true, ... },
  { "ip": "192.168.1.202", "serial_number": "SN002", "enabled": true, ... }
]
```

---

## Running the Application

### Foreground (recommended for first run)
```bat
scripts\run_app.bat
```
Or from Command Prompt in the project root:
```
python src\main.py
```

### With a specific config file
```
python src\main.py --config config\default_config.json
```

### Stop the application
Press `Ctrl+C` in the terminal window. The app disconnects devices cleanly.

---

## License Management

### Generate a license
```
python generate_license.py
```
You will be prompted for customer name, device count, and validity period.
The license key is saved to `config/license.json`.

### View current license
```
python generate_license.py info
```

### Activate a license key
Double-click **`activate_license.bat`** and enter the key when prompted.
Or from Command Prompt:
```
activate_license.bat
```

### Trial license
If no `config/license.json` exists, the application automatically generates
a **30-day trial license** on first startup. No action required.

---

## Windows Service

Running as a Windows service means the application starts automatically with Windows,
even before any user logs in.

### Install service (requires Administrator)
Right-click `scripts\install_service.bat` → **Run as administrator**

Or from an elevated Command Prompt:
```bat
scripts\install_service.bat
```

### Start / stop the service manually
```
sc start AdvancedBiometric
sc stop  AdvancedBiometric
sc query AdvancedBiometric
```
Or open **services.msc** and find "Advanced Biometric Application".

### Uninstall service (requires Administrator)
```bat
scripts\uninstall_service.bat
```

### Enable auto-start with Windows (alternative to service)
```
python src\main.py --enable-autostart
python src\main.py --disable-autostart
```

---

## Testing Device Connection

Before running the full application, verify the device is reachable:

```
python test_device.py 192.168.1.201
```

Or use an environment variable:
```
set DEVICE_IP=192.168.1.201
python test_device.py
```

Expected output on success:
```
ZKTeco Device Connection Test
Target : 192.168.1.201:4370  serial=TEST_DEVICE  timeout=10s
Connecting...
PASS  Connected successfully

Device info:
  serial_number        : ABC123456
  ip_address           : 192.168.1.201
  device_time          : 2026-05-20T10:30:00

Enrolled users : 45
Attendance logs: 1230
Disconnected cleanly.
```

Common failure reasons:
- Device is powered off or unreachable — check network cable / Wi-Fi
- Wrong IP — verify in device menu → Network Settings
- Firewall blocking port 4370 — add inbound rule for TCP 4370
- Device is busy — wait 30 seconds and retry

---

## Building an Executable (.exe)

To distribute without requiring Python on the target machine:

### Step 1 — Set encryption key (optional but recommended)
```bat
set APP_ENCRYPTION_KEY=YourSecureKeyAtLeast16Chars
```

### Step 2 — Build
```bat
python setup.py
```
The executable is created in `dist\Advanced Biometric Application.exe`.

### Step 3 — Verify
```
python integrity_verifier.py
```

### Step 4 — Distribute
Copy the entire `dist\` folder plus `config\` to the target machine.

---

## Directory Structure

```
AdvancedBiometricApplication/
├── src/
│   ├── main.py                    ← Application entry point
│   ├── biometric/
│   │   ├── zk_device.py           ← ZKTeco device wrapper
│   │   └── zk_lib/                ← ZK protocol implementation
│   │       ├── base.py            ← TCP/UDP communication
│   │       ├── const.py           ← Protocol constants
│   │       ├── attendance.py      ← Attendance record model
│   │       ├── user.py            ← User model
│   │       ├── finger.py          ← Fingerprint model
│   │       └── exception.py       ← Custom exceptions
│   ├── core/
│   │   ├── database.py            ← SQLite database manager
│   │   ├── device_manager.py      ← Multi-device orchestration
│   │   └── attendance_service.py  ← Sync service
│   └── utils/
│       ├── config_manager.py      ← JSON/INI config loader
│       ├── license_manager.py     ← License generation & validation
│       ├── logger.py              ← Rotating file logger
│       └── windows_utils.py       ← Registry, service, integrity tools
├── config/
│   ├── default_config.json        ← Main configuration (EDIT THIS)
│   ├── app_config.ini             ← INI alternative config
│   └── license.json               ← Generated on first run
├── data/
│   └── att.db                     ← SQLite database (auto-created)
├── logs/
│   └── app.log                    ← Application log (auto-created)
├── scripts/
│   ├── run_app.bat                ← Start the application
│   ├── install_service.bat        ← Install Windows service
│   └── uninstall_service.bat      ← Remove Windows service
├── install.bat                    ← One-click installer
├── health_check.bat               ← Pre-flight checks
├── activate_license.bat           ← License activation
├── generate_license.py            ← License key generator
├── test_device.py                 ← Device connectivity test
├── custom_runtime.py              ← Security runtime hook
├── setup.py                       ← PyInstaller build script
└── requirements.txt               ← Python dependencies
```

---

## Troubleshooting

### "No module named winreg"
You are running on Linux/macOS. `winreg` is Windows-only.
Windows service features will be unavailable but the core app works fine.

### "No devices configured"
In `config/default_config.json`, set `"enabled": true` for at least one device
and update `"ip"` and `"serial_number"` with your actual device values.

### "Site URL not configured — skipping sync"
Set `"url"` in the `"server"` section of the config. Leave it blank `""` if you
do not have a remote server — attendance is still recorded locally.

### "License expired"
Run `python generate_license.py` to generate a new license, or run
`activate_license.bat` to enter a commercial license key.

### Attendance not syncing to server
1. Check `logs/app.log` for HTTP error codes
2. Verify the server URL ends with `/`
3. Verify the API key is correct
4. Try disabling SSL verification temporarily: `"verify_ssl": false`
5. Ensure your server endpoint accepts POST to `/biometric`

### Application crashes immediately
1. Run `health_check.bat` — fix all `[FAIL]` items
2. Check `logs/app.log` for the traceback
3. Set `"level": "DEBUG"` in the logging config for verbose output

### Device connects but no live events appear
The device may not support live capture mode. Use the fallback poll mode:
the app calls `get_attendance()` to fetch stored records instead of streaming.
Check `logs/app.log` for "live capture error" messages.

### "Debugger detected" message
Set the environment variable `DEV_MODE=1` before running in development:
```
set DEV_MODE=1
python src\main.py
```

---

## Bug Fixes Applied (v2.0)

The following issues from the original repository were fixed in this release:

| File | Bug | Fix |
|------|-----|-----|
| `requirements.txt` | `pyzk` listed as required but project uses its own `zk_lib` | Removed; corrected to `requests`, `psutil`, `pywin32` |
| `src/biometric/zk_lib/const.py` | Missing `CMD_CONNECT`, `CMD_ACK_OK`, `EF_ATTLOG`, `CMD_REG_EVENT`, `FC_PC_USERS` — app crashed on import | All constants added |
| `src/biometric/zk_lib/base.py` | `ZK.connect()`, `get_users()`, `get_attendance()`, `live_capture()` methods incomplete/missing | Fully implemented ZK binary protocol |
| `src/biometric/zk_device.py` | Hard-coded `from src.biometric...` import broke when running from `src/` | Dual try/except import (absolute + relative) |
| `src/core/device_manager.py` | `from queue import Queue` missing `Empty`; queue overflow with no maxsize; reconnect loop missing sleep | Added `Empty`, `maxsize=10000`, reconnect sleep |
| `src/core/attendance_service.py` | Wrong column names (`UserID`, `PunchDateTime` vs `user_id`, `punch_time`); stop loop never exited | Fixed column names, incremental sleep in stop loop |
| `src/__init__.py` | Eagerly imported `windows_utils` causing `ModuleNotFoundError: winreg` on Linux | Removed eager import; lazy import in `main.py` |
| `src/utils/__init__.py` | Imported `WindowsStartupManager` at module level — crashes on Linux | Removed from `__init__`, import on-demand |
| `src/utils/windows_utils.py` | `import winreg` at top level crashes on non-Windows | Guarded with `try/except ImportError` |
| `custom_runtime.py` | Anti-debugger check killed process under coverage.py and test runners; `verify_binary_integrity()` always returned `True` | Added `DEV_MODE` env bypass; real hash check via `APP_EXPECTED_HASH` |
| `generate_license.py` | `ImportError` caught and swallowed — script returned exit code 0 on failure | Re-raises with `sys.exit(1)` |
| `test_device.py` | Double `sys.path.insert` caused import failure; hardcoded IP; no exit code | Single insert; `DEVICE_IP` env var + prompt; `sys.exit` |
| `scripts/config/license.json` | Expired date (2025-09-23) | Regenerated with 1-year validity |
| `config/default_config.json` | Placeholder values shipped as active config; `enabled: true` on example device | Devices disabled by default; blank server URL |
| `activate_license.bat` | Called non-existent `activate_license.py` | Rewritten to call `LicenseManager` directly |
| `install.bat` | Missing closing parenthesis caused syntax error; no auto license | Fixed syntax; auto trial license generation |
| `health_check.bat` | Checked nothing useful | Full checks: Python, deps, config, license, DB, directories |
