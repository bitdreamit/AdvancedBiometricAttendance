# Advanced Biometric Application
### ZKTeco Biometric Attendance System — Complete Installation & Operations Guide

> **Version:** 2.0 &nbsp;|&nbsp; **Python:** 3.8+ &nbsp;|&nbsp; **Platform:** Windows 10/11 (primary), Linux (dev/testing)

---

## Table of Contents

| # | Section |
|---|---------|
| 1 | [What This Application Does](#1-what-this-application-does) |
| 2 | [Before You Begin — Prerequisites Checklist](#2-before-you-begin--prerequisites-checklist) |
| 3 | [Getting the Project Files](#3-getting-the-project-files) |
| 4 | [Complete Installation — Step by Step](#4-complete-installation--step-by-step) |
| 5 | [Configuration Guide](#5-configuration-guide) |
| 6 | [License Setup](#6-license-setup) |
| 7 | [Test Your Device Connection](#7-test-your-device-connection) |
| 8 | [Running the Application](#8-running-the-application) |
| 9 | [Windows Service Setup (Auto-Start)](#9-windows-service-setup-auto-start) |
| 10 | [All Scripts Reference](#10-all-scripts-reference) |
| 11 | [Verify Everything Is Working](#11-verify-everything-is-working) |
| 12 | [Building a Standalone Executable (.exe)](#12-building-a-standalone-executable-exe) |
| 13 | [Daily Operations](#13-daily-operations) |
| 14 | [Troubleshooting — A to Z](#14-troubleshooting--a-to-z) |
| 15 | [Project Structure Explained](#15-project-structure-explained) |
| 16 | [How the Application Works Internally](#16-how-the-application-works-internally) |
| 17 | [Bug Fixes Applied in v2.0](#17-bug-fixes-applied-in-v20) |

---

## 1. What This Application Does

This application connects to one or more **ZKTeco biometric fingerprint/face attendance devices** on your local network, captures attendance punch events in real time, stores them in a local **SQLite database**, and syncs them to your **web server** on a schedule.

```
[ZKTeco Device] ──TCP 4370──► [This App] ──► [SQLite DB] ──HTTP──► [Your Server]
     ↑                              ↑
fingerprint scan             runs on Windows PC
```

**Key features:**
- Live attendance capture (instant, not batch)
- Supports multiple ZKTeco devices simultaneously
- Works offline — stores locally when server is unreachable, syncs when back online
- Automatic time sync between PC and device
- Runs as a Windows Service (starts without login)
- 30-day auto-trial license included

---

## 2. Before You Begin — Prerequisites Checklist

Work through this checklist **before** installing. Every item is required.

### 2.1 Hardware & Network

| Check | Requirement | How to Verify |
|-------|-------------|---------------|
| ☐ | ZKTeco device is powered on | Green/blue LED on device |
| ☐ | Device is connected to same network as PC | Ping the device IP from PC |
| ☐ | Device IP address is known | Device menu → System → Network |
| ☐ | Device serial number is known | Label on back of device OR device menu → System Info |
| ☐ | TCP port **4370** is not blocked by firewall | See Section 2.3 |

### 2.2 Software

| Check | Requirement | Download |
|-------|-------------|----------|
| ☐ | Windows 10 or Windows 11 | — |
| ☐ | Python **3.8 or higher** installed | https://python.org |
| ☐ | Python added to PATH | Tick the checkbox during Python install |
| ☐ | pip works | Run `pip --version` in Command Prompt |

### 2.3 Finding Your Device Information

**Find the device IP address:**
1. On the ZKTeco device, press **Menu**
2. Go to **System** → **Network**
3. Note the IP Address (e.g. `192.168.1.201`)

**Find the device serial number:**
1. On the ZKTeco device, press **Menu**
2. Go to **System** → **Device Info**  (or check label on back)
3. Note the Serial Number (e.g. `ABC123456789`)

**Check if port 4370 is reachable from your PC:**
```cmd
telnet 192.168.1.201 4370
```
If you see a blank screen, the port is open. If you get "connection refused" or timeout, there is a firewall or network problem.

> **No telnet?** Run this in Command Prompt:
> `python -c "import socket; s=socket.socket(); s.settimeout(5); print('OPEN' if s.connect_ex(('192.168.1.201',4370))==0 else 'BLOCKED'); s.close()"`

### 2.4 Verify Python Installation

Open **Command Prompt** (`Win + R` → type `cmd` → Enter) and run:

```cmd
python --version
```

Expected output: `Python 3.8.x` or higher.

```cmd
pip --version
```

Expected output: `pip 23.x.x ...`

If either command is not found, reinstall Python from https://python.org and **tick "Add Python to PATH"**.

---

## 3. Getting the Project Files

### Option A — From ZIP file (recommended)
1. Download `AdvancedBiometricApplication_v2_Fixed.zip`
2. Right-click the ZIP → **Extract All**
3. Choose a location such as `C:\BiometricApp\`
4. You should now have: `C:\BiometricApp\AdvancedBiometricApplication_fixed\`

### Option B — From GitHub
Open Command Prompt and run:
```cmd
git clone https://github.com/SirajCse/AdvancedBiometricApplication.git
cd AdvancedBiometricApplication
```

> ⚠️ If cloning from GitHub, apply the v2.0 fixes first — the raw GitHub repository contains bugs. Use the fixed ZIP instead.

---

## 4. Complete Installation — Step by Step

> **Time required:** approximately 5–10 minutes

### STEP 1 — Open Command Prompt in the project folder

Navigate to the project folder. The easiest way:
1. Open File Explorer
2. Navigate to `C:\BiometricApp\AdvancedBiometricApplication_fixed\`
3. Click the address bar at the top
4. Type `cmd` and press Enter

This opens a Command Prompt already in the right folder.

### STEP 2 — Run the installer

```cmd
install.bat
```

This script automatically:
- ✅ Checks Python is installed
- ✅ Creates `data\`, `logs\`, `config\` directories
- ✅ Installs Python packages: `requests`, `psutil`
- ✅ Generates a 30-day trial license

**Expected output:**
```
===============================================
   Advanced Biometric Application Installer
===============================================

[OK]   Python 3.11.x found
[OK]   Directories created
[OK]   Dependencies installed
[OK]   Trial license generated

===============================================
   Installation Complete
===============================================

Next steps:
 1. Edit config\default_config.json
 2. Run health_check.bat to verify everything
 3. Run scripts\run_app.bat to start
```

If you see any `[FAIL]` lines, fix them before continuing (see Section 14).

### STEP 3 — Edit the configuration file

Open `config\default_config.json` in any text editor (Notepad, Notepad++, VS Code).

**Minimum changes required:**

Find the `"devices"` section and update these 3 values:

```json
"devices": [
  {
    "ip": "192.168.1.201",           ← PUT YOUR DEVICE IP HERE
    "port": 4370,
    "serial_number": "YOUR_DEVICE_SERIAL",  ← PUT YOUR SERIAL NUMBER HERE
    "name": "Main Entrance Device",
    "enabled": true,                 ← CHANGE false TO true
    "timeout": 30,
    "sync_time": true
  }
]
```

**If you have a remote web server to sync to**, also update:

```json
"server": {
  "url": "https://your-academy.com/",  ← YOUR SERVER URL (with trailing slash)
  "api_key": "your_secret_api_key",    ← YOUR API KEY
  "sync_enabled": true,
  "verify_ssl": true,
  "timeout": 30
}
```

If you do NOT have a server, leave `"url": ""` and `"sync_enabled": false`.  
Attendance will still be stored locally in the SQLite database.

**Save the file** (Ctrl+S).

### STEP 4 — Run the health check

```cmd
health_check.bat
```

All lines must show `[OK]` before proceeding. Example good output:

```
===============================================
   Advanced Biometric Application Health Check
===============================================

[OK]   Python 3.11.x
[OK]   requests
[OK]   sqlite3
[OK]   config\default_config.json found
[OK]   1 device(s) enabled
[OK]   data/ directory exists
[OK]   logs/ directory exists
[OK]   config/ directory exists
[OK]   License valid (364 days remaining)
[OK]   Database accessible: data/att.db

Health check PASSED. Application is ready to start.
```

### STEP 5 — Test the device connection

```cmd
python test_device.py 192.168.1.201
```

Replace `192.168.1.201` with your actual device IP.

**Expected success output:**
```
==================================================
ZKTeco Device Connection Test
==================================================
Target : 192.168.1.201:4370  serial=TEST_DEVICE  timeout=10s
Connecting...
PASS  Connected successfully

Device info:
  serial_number        : ABC123456789
  ip_address           : 192.168.1.201
  device_time          : 2026-05-20T10:30:00

Enrolled users : 45
Attendance logs: 1230
Disconnected cleanly.
```

If the test fails, see Section 14 — Troubleshooting before continuing.

### STEP 6 — Start the application

```cmd
scripts\run_app.bat
```

**Expected startup output:**
```
===============================================
   Advanced Biometric Application
===============================================

Starting application... Press Ctrl+C to stop.

2026-05-20 10:30:00 - INFO - Starting Advanced Biometric Application v2.0
2026-05-20 10:30:00 - INFO - Configuration loaded from: config/default_config.json
2026-05-20 10:30:01 - INFO - Connected to device 'ABC123456789' at 192.168.1.201
2026-05-20 10:30:01 - INFO - Time synced on device 'ABC123456789'
2026-05-20 10:30:01 - INFO - Started live capture on 1 device(s)
2026-05-20 10:30:01 - INFO - Attendance service started
2026-05-20 10:30:01 - INFO - All services started — press Ctrl+C to stop
```

The application is now running. When someone scans their finger on the device, you will see:
```
2026-05-20 10:31:15 - INFO - Recorded attendance for user 42
```

**To stop:** press `Ctrl+C` in the window.

---

## 5. Configuration Guide

The main configuration file is `config\default_config.json`.

### Complete configuration reference

```json
{
  "database": {
    "path": "data/att.db",      // Path to SQLite database file
    "auto_create": true,        // Create tables automatically on startup
    "encryption": false         // Database encryption (not yet implemented)
  },

  "logging": {
    "level": "INFO",            // Log verbosity: DEBUG | INFO | WARNING | ERROR
    "file": "logs/app.log",     // Log file location
    "max_size_mb": 10,          // Rotate log when it reaches this size
    "backup_count": 5           // Keep this many old log files
  },

  "sync": {
    "interval_seconds": 300,    // Push to server every N seconds (300 = 5 minutes)
    "retry_attempts": 3,        // Retry failed syncs this many times
    "retry_delay_seconds": 60,  // Wait this long between retries
    "batch_size": 100           // Send this many records per HTTP request
  },

  "devices": [
    {
      "ip": "192.168.1.201",           // Device IP address on your network
      "port": 4370,                    // ZKTeco protocol port — do not change
      "serial_number": "ABC123456789", // Device serial number
      "name": "Main Entrance",         // Human-friendly name for logs
      "enabled": true,                 // false = ignore this device on startup
      "timeout": 30,                   // Seconds to wait for connection
      "sync_time": true                // Sync device clock to PC clock on connect
    }
  ],

  "server": {
    "url": "https://your-site.com/",   // Your web server URL (with trailing slash)
    "api_key": "your_api_key",         // Sent as: Authorization: Bearer your_api_key
    "sync_enabled": true,              // Enable/disable server sync entirely
    "verify_ssl": true,                // false = allow self-signed SSL certs
    "timeout": 30                      // HTTP request timeout in seconds
  },

  "security": {
    "encryption_enabled": false,       // Config encryption (requires CONFIG_ENCRYPTION_KEY)
    "integrity_check": false           // Binary integrity check (requires APP_EXPECTED_HASH)
  },

  "application": {
    "auto_start": false,               // Register in Windows startup (use service instead)
    "minimize_to_tray": true,
    "language": "en"
  }
}
```

### Adding multiple devices

Add each device as a new object in the `"devices"` array:

```json
"devices": [
  {
    "ip": "192.168.1.201",
    "port": 4370,
    "serial_number": "SN001",
    "name": "Front Door",
    "enabled": true,
    "timeout": 30,
    "sync_time": true
  },
  {
    "ip": "192.168.1.202",
    "port": 4370,
    "serial_number": "SN002",
    "name": "Back Door",
    "enabled": true,
    "timeout": 30,
    "sync_time": true
  },
  {
    "ip": "192.168.1.203",
    "port": 4370,
    "serial_number": "SN003",
    "name": "Canteen",
    "enabled": false,
    "timeout": 30,
    "sync_time": false
  }
]
```

> Devices with `"enabled": false` are skipped on startup without error.

### Server sync endpoint

The application POSTs attendance data to `{url}biometric` (e.g. `https://your-site.com/biometric`).

**Request format:**
```json
{
  "uid": 42,
  "user_id": 42,
  "t": "2026-05-20T10:31:15",
  "ip": "192.168.1.201",
  "serial_number": "ABC123456789"
}
```

Your server must accept this POST and return HTTP 200 or 201 to confirm receipt.

---

## 6. License Setup

### Trial License (automatic)
On first run, a **30-day trial license** is automatically created at `config\license.json`.  
No action needed — the application works immediately.

### Generate a new license

```cmd
python generate_license.py
```

You will be prompted:
```
==================================================
Advanced Biometric Application - License Generator
==================================================

Enter license details:
Customer Name/Email: ACME School
Number of Devices: 3
Days Valid (365 for 1 year, 30 for trial): 365

==================================================
LICENSE GENERATED SUCCESSFULLY
==================================================
Customer    : ACME School
Devices     : 3
Valid for   : 365 days
License Key : A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6

License file saved to: config/license.json
```

Save the license key — you will need it to activate on other machines.

### View current license information

```cmd
python generate_license.py info
```

Output:
```
CURRENT LICENSE INFORMATION
========================================
Customer Name        : ACME School
Device Count         : 3
Issued Date          : 2026-05-20T10:00:00
Expiry Date          : 2027-05-20T10:00:00
Days Remaining       : 364
Type                 : commercial
License Key          : A1B2C3...D5D6
```

### Activate a license on a new machine

Double-click **`activate_license.bat`** and enter the key:

```
===============================================
   License Activation
===============================================

Enter your 32-character license key.
(Run: python generate_license.py  to create one)

License Key: A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6

[OK]  License activated successfully.

License details:
  Activation Date      : 2026-05-20T10:05:00
  Expiry Date          : 2027-05-20T10:05:00
```

### License renewal

When a license is close to expiry:
1. Run `python generate_license.py` to generate a new key
2. Run `activate_license.bat` and enter the new key
3. Or simply generate a fresh one — the old `config\license.json` is replaced

---

## 7. Test Your Device Connection

Always test the device before running the full application. This catches network and firewall problems early.

### Basic connection test

```cmd
python test_device.py 192.168.1.201
```

### Using an environment variable (useful in scripts)

```cmd
set DEVICE_IP=192.168.1.201
python test_device.py
```

### If you do not know the IP

Just run the script with no argument — it will prompt you:

```cmd
python test_device.py
```
```
Enter device IP address [192.168.1.201]:
```

### Reading the test output

| Output | Meaning |
|--------|---------|
| `PASS  Connected successfully` | Device is working correctly |
| `FAIL  Could not connect` | Network or firewall problem — see Section 14.3 |
| `Enrolled users: 0` | Device has no registered users yet |
| `WARN  Could not retrieve device info` | Connected but firmware is unusual — usually fine |

---

## 8. Running the Application

### Method 1 — Foreground mode (recommended for first use and testing)

```cmd
scripts\run_app.bat
```

Or directly:

```cmd
python src\main.py
```

- Application runs in the Command Prompt window
- You can see all log messages in real time
- Press `Ctrl+C` to stop cleanly
- If the window is closed, the application stops

### Method 2 — With a custom config file

```cmd
python src\main.py --config config\default_config.json
```

### Method 3 — Windows Service (for production — auto-starts with Windows)

See Section 9.

### Stopping the application

Press `Ctrl+C` in the terminal. The application will:
1. Stop accepting new attendance events
2. Disconnect all devices cleanly
3. Flush pending database writes
4. Stop the sync service

```
^C
2026-05-20 10:45:00 - INFO - Shutdown requested by user
2026-05-20 10:45:00 - INFO - Shutting down services...
2026-05-20 10:45:01 - INFO - Stopped all live capture threads
2026-05-20 10:45:01 - INFO - All devices disconnected
2026-05-20 10:45:01 - INFO - Shutdown complete
```

---

## 9. Windows Service Setup (Auto-Start)

Running as a **Windows Service** means the application starts automatically when Windows boots, runs in the background without a visible window, and restarts automatically if it crashes.

> ⚠️ **Administrator rights required for all steps in this section.**
> Right-click any bat file → **Run as administrator**

### 9.1 Installing the Service

**Step 1** — Right-click `scripts\install_service.bat` → **Run as administrator**

What the script does:
```
net session                          ← checks for admin rights
python --version                     ← checks Python is available
python src\main.py --install-service ← registers with Windows
sc start AdvancedBiometric           ← starts it immediately
```

**Expected output:**
```
===============================================
   Advanced Biometric Application Service Installer
===============================================

[OK]   Service installed.
[OK]   Service started successfully.

Service Name  : AdvancedBiometric
Display Name  : Advanced Biometric Application
Startup Type  : Automatic
```

**Step 2** — Verify it is running:
```cmd
sc query AdvancedBiometric
```

Expected:
```
SERVICE_NAME: AdvancedBiometric
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
```

### 9.2 Managing the Service

All commands must be run in an elevated (Administrator) Command Prompt.

| Action | Command |
|--------|---------|
| Start the service | `sc start AdvancedBiometric` |
| Stop the service | `sc stop AdvancedBiometric` |
| Restart the service | `sc stop AdvancedBiometric` then `sc start AdvancedBiometric` |
| Check status | `sc query AdvancedBiometric` |
| Open Services manager | `services.msc` |

### 9.3 Using Services Manager (GUI)

1. Press `Win + R` → type `services.msc` → Enter
2. Scroll to **Advanced Biometric Application**
3. Double-click to open Properties:
   - **Start type:** Automatic (starts at boot)
   - **Recovery tab:** Set "First failure" to **Restart the Service** for auto-recovery

### 9.4 Uninstalling the Service

**Right-click `scripts\uninstall_service.bat` → Run as administrator**

```
Stopping service...
Uninstalling service...
[OK]   Service uninstalled successfully.
```

The service is removed from Windows. The application files are not deleted.

### 9.5 Auto-Start Alternative (without a Service)

If you want the app to start when a specific user logs in (not at boot):

```cmd
python src\main.py --enable-autostart
```

To remove it:
```cmd
python src\main.py --disable-autostart
```

This adds/removes an entry in the Windows Registry at:
`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`

---

## 10. All Scripts Reference

| Script | Location | Admin? | Purpose |
|--------|----------|--------|---------|
| `install.bat` | Root | No | First-time installation — run once |
| `health_check.bat` | Root | No | Pre-flight system checks |
| `activate_license.bat` | Root | No | Enter a license key |
| `scripts\run_app.bat` | scripts\ | No | Start app in foreground |
| `scripts\install_service.bat` | scripts\ | **YES** | Register as Windows service |
| `scripts\uninstall_service.bat` | scripts\ | **YES** | Remove Windows service |
| `generate_license.py` | Root | No | Generate new license keys |
| `test_device.py` | Root | No | Test device connectivity |
| `setup.py` | Root | No | Build standalone .exe |

### install.bat — detailed behaviour

```cmd
install.bat
```

1. Checks Python ≥ 3.8 is installed
2. Creates: `data\`, `logs\`, `config\`
3. Runs: `pip install requests psutil`
4. Generates trial license if `config\license.json` does not exist
5. Prints next-step instructions

Run this **once** when first setting up. Safe to run again — it will not overwrite existing config or license.

### health_check.bat — detailed behaviour

```cmd
health_check.bat
```

Checks in order:
1. Python version (must be 3.8+)
2. `requests` package importable
3. `sqlite3` package importable
4. `config\default_config.json` exists and is valid JSON
5. At least one device is enabled
6. All required directories exist
7. `config\license.json` exists and is not expired
8. Database file can be opened

**Exit code:** 0 = pass, 1 = one or more failures.

Run this any time you change the configuration, or if the application is not behaving as expected.

### scripts\run_app.bat — detailed behaviour

```cmd
scripts\run_app.bat
```

1. Checks Python is installed
2. Creates `data\`, `logs\`, `config\` if they don't exist
3. Warns if no license found (app generates trial automatically)
4. Runs: `python src\main.py`
5. Shows exit code and log location on stop

### scripts\install_service.bat — detailed behaviour

```cmd
scripts\install_service.bat      (RIGHT-CLICK → Run as administrator)
```

1. Checks for Administrator rights — exits with error if not admin
2. Checks Python is installed
3. Runs: `python src\main.py --install-service`
4. Runs: `sc start AdvancedBiometric`
5. Confirms service is running

### scripts\uninstall_service.bat — detailed behaviour

```cmd
scripts\uninstall_service.bat    (RIGHT-CLICK → Run as administrator)
```

1. Checks for Administrator rights
2. Runs: `sc stop AdvancedBiometric`
3. Waits 3 seconds
4. Runs: `python src\main.py --uninstall-service`
5. Falls back to `sc delete AdvancedBiometric` if Python method fails

---

## 11. Verify Everything Is Working

After starting the application, use these checks to confirm it is operating correctly.

### Check 1 — Log file is being written

```cmd
type logs\app.log
```

You should see timestamped lines ending with `All services started`.  
If the file is empty or missing, there was a startup error.

### Check 2 — Database has the attendance table

```cmd
python -c "import sqlite3; conn=sqlite3.connect('data/att.db'); print([r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"
```

Expected: `['devices', 'attendance', 'configuration', 'users']`

### Check 3 — Attendance records are being stored

Scan a fingerprint on the device, then run:

```cmd
python -c "
import sqlite3
conn = sqlite3.connect('data/att.db')
rows = conn.execute('SELECT * FROM attendance ORDER BY id DESC LIMIT 5').fetchall()
for r in rows: print(r)
"
```

You should see recent punch records.

### Check 4 — Service is running (if installed)

```cmd
sc query AdvancedBiometric
```

Look for: `STATE : 4 RUNNING`

### Check 5 — Application responds to Ctrl+C cleanly

Stop the app with `Ctrl+C` and check the log for:
```
Shutdown complete
```
If you see this, the app stopped cleanly. If not, check for errors in the log.

### Check 6 — Sync is reaching your server

In `logs\app.log`, look for:
```
INFO - Synced record 1 for user 42
INFO - Marked 3 records as synced
```

If you see:
```
WARNING - Site URL not configured or using placeholder — skipping sync
```
Update the `"url"` in `config\default_config.json`.

---

## 12. Building a Standalone Executable (.exe)

Build a single `.exe` file that can be deployed to machines without Python installed.

> ⚠️ This step is optional. The Python source version works fine for most deployments.

### Step 1 — Set an encryption key (optional but recommended)

```cmd
set APP_ENCRYPTION_KEY=YourSecureKeyHereMin16Chars
```

> This key encrypts the Python bytecode inside the executable. Store it securely — you will need it to rebuild.

### Step 2 — Build

```cmd
python setup.py
```

This runs PyInstaller and produces `dist\Advanced Biometric Application.exe`.

Build output:
```
Building Advanced Biometric Application v2.0
Building with PyInstaller...
Build completed successfully: dist/Advanced Biometric Application.exe

Security features applied:
- Bytecode encryption
- Integrity verification system
- Restricted file permissions

Integrity hash saved to: integrity_verifier.py
```

### Step 3 — Verify the build

```cmd
python integrity_verifier.py
```

Expected: `Integrity check passed`

### Step 4 — Distribute

Copy these to the target machine:
```
dist\Advanced Biometric Application.exe
config\default_config.json           ← already configured with device details
```

On the target machine, run the `.exe` directly — no Python required.

### Step 5 — Install as service on target machine (optional)

On the target machine, from an admin Command Prompt:
```cmd
"Advanced Biometric Application.exe" --install-service
```

---

## 13. Daily Operations

### Starting and stopping

| Situation | Action |
|-----------|--------|
| Running as service | Starts automatically at boot — no action needed |
| Running in foreground | Double-click `scripts\run_app.bat` |
| Stop foreground | Press `Ctrl+C` in the window |
| Stop service | `sc stop AdvancedBiometric` (as admin) |
| Restart service | `sc stop AdvancedBiometric` then `sc start AdvancedBiometric` |

### Checking logs

The log file rotates automatically at 10MB and keeps 5 backups.

```cmd
type logs\app.log                   ← view current log
type logs\app.log.1                 ← view previous log
```

To watch the log live:
```cmd
powershell -command "Get-Content logs\app.log -Wait -Tail 20"
```

### Querying attendance records

View the last 20 attendance records:
```cmd
python -c "
import sqlite3, json
conn = sqlite3.connect('data/att.db')
rows = conn.execute('''
    SELECT user_id, punch_time, device_sn, status
    FROM attendance
    ORDER BY id DESC
    LIMIT 20
''').fetchall()
print(f'{'UserID':>8}  {'PunchTime':>22}  {'Device':>15}  Status')
print('-' * 65)
for r in rows:
    print(f'{str(r[0]):>8}  {str(r[1]):>22}  {str(r[2]):>15}  {r[3]}')
"
```

### Changing configuration

1. Edit `config\default_config.json`
2. Restart the application (Ctrl+C then run again, or `sc stop` / `sc start`)
3. Configuration is read at startup only — changes require a restart

### Adding a new device

1. Edit `config\default_config.json`
2. Add a new object to the `"devices"` array
3. Test it: `python test_device.py NEW_DEVICE_IP`
4. Restart the application

### Backing up data

The entire attendance database is in `data\att.db`. Back this file up regularly:
```cmd
copy data\att.db data\att_backup_%date:~-4,4%%date:~-10,2%%date:~-7,2%.db
```

---

## 14. Troubleshooting — A to Z

### 14.1 Installation Problems

**Problem: `python` command not found**
```
'python' is not recognized as an internal or external command
```
**Fix:**
1. Download Python from https://python.org
2. During installation, tick **"Add Python to PATH"**
3. Close and reopen Command Prompt
4. Run `python --version`

---

**Problem: `pip install` fails — no internet access**
```
Could not find a version that satisfies the requirement requests
```
**Fix:**
1. Check internet connection
2. If behind a proxy: `pip install requests --proxy http://proxy:port`
3. If air-gapped: download wheels manually from https://pypi.org and install with `pip install requests-2.x.x-py3-none-any.whl`

---

**Problem: Permission error during install**
```
PermissionError: [Errno 13] Permission denied
```
**Fix:** Run Command Prompt as Administrator, or add `--user` flag:
```cmd
pip install requests psutil --user
```

---

### 14.2 Configuration Problems

**Problem: `"No devices configured"` in logs**
```
WARNING - No devices configured. Add devices to config/default_config.json
```
**Fix:**
1. Open `config\default_config.json`
2. In the `"devices"` array, set `"enabled": true`
3. Set the correct `"ip"` and `"serial_number"`
4. Save and restart

---

**Problem: `"Site URL not configured — skipping sync"`**
```
DEBUG - Site URL not configured or using placeholder — skipping sync
```
**Fix:** This is normal if you have no server. To enable sync:
1. Set `"url"` in `"server"` section to your actual server URL
2. Set `"sync_enabled": true`
3. Restart

---

**Problem: Config file has JSON syntax error**
```
json.decoder.JSONDecodeError: Expecting value: line X column Y
```
**Fix:**
1. Open `config\default_config.json` in VS Code or Notepad++
2. Look at line X for the error (missing comma, unclosed bracket, etc.)
3. Common mistakes: trailing comma after last item, missing quotes around strings
4. Validate at: https://jsonlint.com

---

### 14.3 Device Connection Problems

**Problem: `FAIL Could not connect to 192.168.1.201:4370`**

Work through these checks in order:

1. **Is the device powered on?** Look for the LED on the device.

2. **Can the PC ping the device?**
   ```cmd
   ping 192.168.1.201
   ```
   If no reply: wrong IP, or device is on a different network subnet.

3. **Is port 4370 reachable?**
   ```cmd
   python -c "import socket; s=socket.socket(); s.settimeout(5); r=s.connect_ex(('192.168.1.201',4370)); print('OPEN' if r==0 else f'BLOCKED (code {r})'); s.close()"
   ```
   If BLOCKED: open port 4370 in Windows Firewall.

4. **Open Windows Firewall for port 4370:**
   - Open `Windows Defender Firewall with Advanced Security`
   - Inbound Rules → New Rule
   - Port → TCP → 4370 → Allow
   - Apply to all profiles

5. **Is the device already connected to another application?** Only one client can connect at a time. Close ZKTeco attendance software if it is running.

6. **Is the device IP correct?** Recheck: device → Menu → System → Network.

---

**Problem: Device connects but no attendance events appear**

The device may not support live capture via TCP. This is normal for older firmware.

**What happens:** The app falls back to periodic polling (`get_attendance()` instead of live stream). Records appear in the database after the next sync cycle (every 5 minutes by default).

To confirm this is happening, check `logs\app.log` for:
```
ERROR - Live capture error on ABC123456789: ...
INFO  - Started live capture on 1 device(s)   ← still running despite error
```

To speed up polling, reduce the sync interval:
```json
"sync": {
  "interval_seconds": 60
}
```

---

### 14.4 License Problems

**Problem: `"License expired"`**
```
WARNING - License issue: License has expired (continuing for demo)
```
**Fix:**
```cmd
python generate_license.py
```
Generate a new license. The old one is replaced.

---

**Problem: `"Invalid license key format"`**
```
[FAIL] Invalid license key format.
```
**Fix:** License keys are exactly 32 hexadecimal characters (0-9, A-F). Check for spaces or typos. Copy-paste from the generated output rather than typing.

---

### 14.5 Service Problems

**Problem: Service fails to install**
```
Access is denied.
```
**Fix:** You must run `scripts\install_service.bat` as Administrator.  
Right-click the file → **Run as administrator**.

---

**Problem: Service installs but does not start**
```
SERVICE_NAME: AdvancedBiometric
        STATE : 1  STOPPED
```
**Fix:**
1. Check `logs\app.log` for the startup error
2. Most common cause: device IP is wrong or unreachable
3. Fix the config, then: `sc start AdvancedBiometric`

---

**Problem: Service keeps stopping / restarting**

Open `services.msc`, find **Advanced Biometric Application**, open Properties → **Recovery** tab.  
Set First failure, Second failure, and Subsequent failures to **Restart the Service**.

Also increase the reset period:
```
Reset fail count after: 1 day
Restart service after: 1 minute
```

---

### 14.6 Windows-Specific Problems

**Problem: `ModuleNotFoundError: No module named 'winreg'`**

You are running on Linux or macOS. `winreg` is Windows-only.  
This is normal — the Windows service features are unavailable, but everything else works.

**Fix for development on Linux:** No fix needed. The app runs fine without winreg.

---

**Problem: `Debugger detected` message in logs**

```
[security] Debugger detected.
```

**Fix:** Set the environment variable before running:
```cmd
set DEV_MODE=1
python src\main.py
```
This bypasses the security check in development mode.

---

### 14.7 Sync / Server Problems

**Problem: Records not reaching server — HTTP 401**
```
WARNING - Server rejected record 1: HTTP 401
```
**Fix:** API key is wrong. Update `"api_key"` in config.

---

**Problem: Records not reaching server — HTTP 404**
```
WARNING - Server rejected record 1: HTTP 404
```
**Fix:** Server URL is wrong. The app posts to `{url}biometric`.  
If your URL is `https://example.com/api/`, the endpoint called is `https://example.com/api/biometric`.

---

**Problem: SSL certificate error**
```
requests.exceptions.SSLError: certificate verify failed
```
**Fix (development only):**
```json
"server": {
  "verify_ssl": false
}
```
For production, install a valid SSL certificate on your server.

---

**Problem: Timeout connecting to server**
```
ERROR - Timeout syncing record 1
```
**Fix:** Increase the timeout, or check your server is running:
```json
"server": {
  "timeout": 60
}
```

---

### 14.8 Application Crashes at Startup

**Step 1:** Run the health check:
```cmd
health_check.bat
```

**Step 2:** Enable debug logging:
```json
"logging": {
  "level": "DEBUG"
}
```

**Step 3:** Look at the full error in the log:
```cmd
type logs\app.log
```

**Step 4:** Search for the error message in this section. If not found, open an issue on GitHub with the full log output.

---

## 15. Project Structure Explained

```
AdvancedBiometricApplication/
│
├── src/                              APPLICATION SOURCE CODE
│   ├── main.py                       Entry point — arg parsing, startup, shutdown
│   │
│   ├── biometric/                    DEVICE COMMUNICATION
│   │   ├── zk_device.py              High-level ZKTeco device wrapper
│   │   └── zk_lib/                   ZK binary protocol implementation
│   │       ├── base.py               TCP/UDP socket communication, packet builder
│   │       ├── const.py              Protocol command codes and constants
│   │       ├── attendance.py         Attendance record data class
│   │       ├── user.py               User data class
│   │       ├── finger.py             Fingerprint template data class
│   │       └── exception.py          ZKErrorConnection, ZKNetworkError
│   │
│   ├── core/                         BUSINESS LOGIC
│   │   ├── database.py               SQLite wrapper — all DB reads/writes
│   │   ├── device_manager.py         Manages multiple devices, live capture threads
│   │   └── attendance_service.py     Sync loop — DB → HTTP → server
│   │
│   └── utils/                        UTILITIES
│       ├── config_manager.py         JSON/INI config loader with validation
│       ├── license_manager.py        License generation, validation, activation
│       ├── logger.py                 Rotating file + console logging setup
│       └── windows_utils.py          Registry, service management, integrity tools
│
├── config/                           CONFIGURATION
│   ├── default_config.json           Main config file — EDIT THIS
│   ├── app_config.ini                INI-format alternative config
│   └── license.json                  Generated automatically on first run
│
├── data/                             DATA (auto-created)
│   └── att.db                        SQLite database — all attendance records
│
├── logs/                             LOGS (auto-created)
│   ├── app.log                       Current application log
│   └── app.log.1, .2, ...            Rotated old logs
│
├── scripts/                          OPERATIONAL SCRIPTS
│   ├── run_app.bat                   Start in foreground
│   ├── install_service.bat           Install Windows service (needs admin)
│   ├── uninstall_service.bat         Remove Windows service (needs admin)
│   └── config/
│       ├── default_config.json       Scripts-folder config copy
│       └── license.json              Scripts-folder license copy
│
├── install.bat                       First-time installer
├── health_check.bat                  System verification
├── activate_license.bat              License activation
├── generate_license.py               License key generator
├── test_device.py                    Device connectivity tester
├── custom_runtime.py                 Security checks (DEV_MODE bypass)
├── setup.py                          PyInstaller build script
└── requirements.txt                  Python dependencies list
```

### Database schema

```sql
-- All connected ZKTeco devices
CREATE TABLE devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    port INTEGER DEFAULT 4370,
    serial_number TEXT NOT NULL UNIQUE,
    name TEXT,
    last_sync TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- All attendance punch events
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,       -- ZKTeco user ID
    punch_time TIMESTAMP NOT NULL,  -- When the punch happened
    device_ip TEXT,                 -- Which device recorded it
    device_sn TEXT,                 -- Device serial number
    status TEXT DEFAULT 'pending',  -- 'pending' or 'synced'
    sync_time TIMESTAMP,            -- When it was sent to server
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- App configuration key/value store
CREATE TABLE configuration (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- User records synced from device
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    privilege INTEGER,
    password TEXT,
    last_updated TIMESTAMP
);
```

---

## 16. How the Application Works Internally

Understanding the flow helps when diagnosing problems.

```
Startup
  │
  ├─ Load config/default_config.json
  ├─ Validate license (auto-create trial if missing)
  ├─ Open / create SQLite database
  │
  ├─ For each enabled device:
  │    ├─ TCP connect to device:port
  │    ├─ ZK handshake (session key)
  │    ├─ Sync device clock to PC
  │    └─ Start LiveCapture thread
  │
  ├─ Start AttendanceService thread
  │
  └─ Main thread sleeps (Ctrl+C waits here)

LiveCapture thread (one per device)
  │
  └─ Loop forever:
       ├─ Send CMD_REG_EVENT to device
       ├─ Wait for EF_ATTLOG packets
       ├─ Parse packet → Attendance record
       ├─ Put record on attendance_queue
       └─ On disconnect: wait 30s, reconnect

AttendanceService thread
  │
  └─ Every sync_interval seconds:
       ├─ Drain attendance_queue → INSERT into SQLite
       └─ SELECT pending records → POST to server
            └─ On HTTP 200/201: UPDATE status='synced'

Shutdown (Ctrl+C or sc stop)
  │
  ├─ Signal all threads to stop
  ├─ Join threads (5s timeout each)
  ├─ Disconnect all devices
  └─ Log "Shutdown complete"
```

---

## 17. Bug Fixes Applied in v2.0

The following bugs were present in the original GitHub repository and are fixed in this release.

| # | File | Bug Description | Fix Applied |
|---|------|----------------|-------------|
| 1 | `zk_lib/const.py` | Missing `CMD_CONNECT`, `CMD_ACK_OK`, `EF_ATTLOG`, `CMD_REG_EVENT`, `FC_PC_USERS` — app crashed immediately on import | All 30+ missing ZK protocol constants added |
| 2 | `zk_lib/base.py` | `ZK.connect()`, `get_users()`, `get_attendance()`, `live_capture()`, `set_time()` were incomplete stubs | Full ZK binary protocol implemented with proper packet encoding/decoding |
| 3 | `src/__init__.py` | Eagerly imported `windows_utils`, causing `ModuleNotFoundError: winreg` on every non-Windows machine | All eager imports removed; lazy import in main.py only |
| 4 | `src/utils/__init__.py` | `from .windows_utils import WindowsStartupManager` at module level crashed on Linux | Removed from `__init__`; imported on-demand |
| 5 | `windows_utils.py` | `import winreg` at top level — crashes on every non-Windows platform | Wrapped in `try/except ImportError`; `_WINREG_AVAILABLE` flag |
| 6 | `zk_device.py` | Hard-coded `from src.biometric...` import broke when `src/` was on sys.path | Dual try/except import (absolute then relative) |
| 7 | `device_manager.py` | `from queue import Queue` but `Empty` not imported — `get_nowait()` raised unhandled exception | Added `Empty` to import; queue given `maxsize=10000` |
| 8 | `device_manager.py` | Reconnect loop had no sleep — busy-looped at 100% CPU on disconnection | Added `time.sleep(30)` between reconnect attempts |
| 9 | `attendance_service.py` | Wrong column names: `UserID`, `PunchDateTime`, `IPAddr`, `SrNo`, `ID` — no records ever synced | Fixed to `user_id`, `punch_time`, `device_ip`, `device_sn`, `id` |
| 10 | `attendance_service.py` | Stop loop used `time.sleep(interval)` — stop() blocked for up to 5 minutes | Changed to 1-second increments with `is_running` check |
| 11 | `custom_runtime.py` | Anti-debugger check killed the process under coverage.py, pytest, and any profiler | `DEV_MODE=1` env var bypasses all security checks |
| 12 | `custom_runtime.py` | `verify_binary_integrity()` always returned `True` — no actual check | Real SHA256 comparison via `APP_EXPECTED_HASH` env var |
| 13 | `generate_license.py` | `ImportError` caught and swallowed — script printed error but exited with code 0 | Re-raises via `sys.exit(1)` so callers detect failure |
| 14 | `test_device.py` | Double `sys.path.insert` caused module resolution to fail in some environments | Single `sys.path.insert(0, repo_root)` |
| 15 | `test_device.py` | Hardcoded IP `192.168.1.201` with no way to override — hung in CI | Reads from `DEVICE_IP` env var; prompts user; accepts CLI arg |
| 16 | `test_device.py` | Always exited with code 0 — failure invisible to scripts | `sys.exit(0 if success else 1)` |
| 17 | `scripts/config/license.json` | Expiry date was `2025-09-23` — license expired before the ZIP was even downloaded | Regenerated with 365-day validity from current date |
| 18 | `config/default_config.json` | Example device had `"enabled": true` and placeholder serial number — app tried to connect and failed on every fresh install | `"enabled": false` by default; blank server URL |
| 19 | `activate_license.bat` | Called `activate_license.py` which does not exist anywhere in the repository | Rewritten to call `LicenseManager` directly via inline Python |
| 20 | `install.bat` | Missing closing `)` caused batch syntax error — install always failed | Fixed syntax; added auto trial license generation |
| 21 | `health_check.bat` | Only printed "All systems operational" with no actual checks | Real checks: Python version, packages, config, license, DB, dirs |
| 22 | `requirements.txt` | Listed `pyzk` which is not needed — project has its own `zk_lib` implementation | Removed `pyzk`; corrected to `requests`, `psutil`, `pywin32` |

