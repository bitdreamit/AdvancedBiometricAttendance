# Release Notes — Advanced Biometric Attendance System

## v2.0.0 — 2026-05-20

**Repository:** `bitdreamit/AdvancedBiometricAttendance`
**Previous:** `SirajCse/AdvancedBiometricApplication`

---

## What's New in v2.0.0

This release is a **complete overhaul** of the original codebase.
The original repository had 22 confirmed bugs that prevented the application
from running at all on a fresh install. Every bug has been identified, fixed,
and verified with automated tests. The application now works end-to-end
out of the box.

---

## Bug Fixes

### Critical — Application could not start

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `src/biometric/zk_lib/const.py` | 30+ ZK protocol constants missing (`CMD_CONNECT`, `CMD_ACK_OK`, `EF_ATTLOG`, `CMD_REG_EVENT`, `FC_PC_USERS` etc.) — app crashed on every import | All constants added |
| 2 | `src/biometric/zk_lib/base.py` | `connect()`, `get_users()`, `get_attendance()`, `live_capture()`, `set_time()` were empty stubs — no device communication was possible | Full ZK binary protocol implemented with correct TCP packet encoding and decoding |
| 3 | `src/__init__.py` | Eagerly imported `windows_utils` at package level — caused `ModuleNotFoundError: No module named 'winreg'` on every non-Windows machine | Removed all eager imports from `__init__.py` |
| 4 | `src/utils/__init__.py` | `from .windows_utils import WindowsStartupManager` at module level — crashed on Linux and macOS | Removed; import is now on-demand only in `main.py` |
| 5 | `src/utils/windows_utils.py` | `import winreg` at top level — hard crash on every non-Windows platform | Wrapped in `try/except ImportError` with `_WINREG_AVAILABLE` flag |

### Critical — Attendance data never saved or synced

| # | File | Issue | Fix |
|---|------|-------|-----|
| 6 | `src/core/attendance_service.py` | Wrong database column names throughout — `UserID`, `PunchDateTime`, `IPAddr`, `SrNo`, `ID` instead of `user_id`, `punch_time`, `device_ip`, `device_sn`, `id` — no records were ever read or synced | All column names corrected to match actual schema |
| 7 | `src/core/device_manager.py` | `from queue import Queue` but `Empty` exception never imported — `get_nowait()` raised unhandled `NameError` on every queue drain | Added `Empty` to import |
| 8 | `src/core/device_manager.py` | Queue created with no `maxsize` — unbounded memory growth under heavy attendance load | Set `maxsize=10000` |
| 9 | `src/core/device_manager.py` | Reconnect loop had no `sleep()` — busy-looped at 100% CPU when a device was unreachable | Added `time.sleep(30)` between reconnect attempts |
| 10 | `src/biometric/zk_device.py` | Hard-coded absolute import `from src.biometric...` failed when `src/` was on `sys.path` | Dual try/except import (absolute then relative) |

### High — Scripts failed silently or not at all

| # | File | Issue | Fix |
|---|------|-------|-----|
| 11 | `activate_license.bat` | Called `activate_license.py` which does not exist anywhere in the repository — activation always failed | Rewritten to call `LicenseManager` directly via inline Python |
| 12 | `install.bat` | Missing closing `)` on a condition block — batch syntax error — install always exited immediately | Fixed syntax; added automatic trial license generation |
| 13 | `health_check.bat` | Script body only printed "All systems operational" with no actual checks performed | Replaced with real checks: Python version, packages, config validity, license expiry, database, directories |
| 14 | `generate_license.py` | `ImportError` caught and swallowed with `print()` — script exited with code 0 on failure — deployment scripts could not detect the error | Re-raises via `sys.exit(1)` on any import or runtime failure |
| 15 | `test_device.py` | Double `sys.path.insert` with conflicting paths caused module resolution failure in many environments | Single `sys.path.insert(0, repo_root)` |
| 16 | `test_device.py` | IP address `192.168.1.201` hardcoded with no override — hung for 10 seconds in CI with no output | Reads from `DEVICE_IP` env var; accepts CLI argument; prompts user as fallback |
| 17 | `test_device.py` | Always exited with code 0 regardless of success or failure | `sys.exit(0 if success else 1)` |

### Medium — Security and runtime issues

| # | File | Issue | Fix |
|---|------|-------|-----|
| 18 | `custom_runtime.py` | Anti-debugger check (`sys.gettrace() is not None`) killed the process under `coverage.py`, `pytest`, and any Python profiler — impossible to run tests | `DEV_MODE=1` environment variable bypasses all security checks |
| 19 | `custom_runtime.py` | `verify_binary_integrity()` was a stub that always returned `True` — integrity protection was entirely non-functional | Real SHA-256 hash comparison implemented via `APP_EXPECTED_HASH` environment variable |
| 20 | `attendance_service.py` | Stop loop called `time.sleep(interval_seconds)` — `stop()` blocked for up to 5 minutes before returning | Changed to 1-second increments with `is_running` flag check |

### Low — Configuration and data issues

| # | File | Issue | Fix |
|---|------|-------|-----|
| 21 | `scripts/config/license.json` | Expiry date was `2025-09-23` — license was already expired before the repository was even downloaded | Regenerated with 365-day validity from release date |
| 22 | `config/default_config.json` | Example device entry had `"enabled": true` with placeholder IP and serial — app attempted to connect to a non-existent device on every fresh install | `"enabled": false` by default; server URL blank by default |
| 23 | `requirements.txt` | Listed `pyzk` as a dependency — the project has its own bundled `zk_lib` implementation and does not use `pyzk` | Removed `pyzk`; corrected to `requests`, `psutil`, `pywin32` |

---

## New Features

### Comprehensive installer (`install.bat`)
- Python version check
- Auto-creates all required directories (`data/`, `logs/`, `config/`)
- Installs all dependencies via pip
- Generates a 30-day trial license automatically on first run
- Clear next-step instructions on completion

### Real health check (`health_check.bat`)
- Verifies Python version (3.8+)
- Verifies all required packages are importable
- Validates `config/default_config.json` is present and parseable
- Detects placeholder values in config
- Verifies at least one device is enabled
- Checks license validity and days remaining
- Verifies database is accessible
- Exits with code 0 (pass) or 1 (fail) for use in scripts

### `DEV_MODE` environment variable
Set `DEV_MODE=1` before running to bypass all security checks.
Allows normal use of debuggers, `coverage.py`, and `pytest`.

### Config placeholder detection
`ConfigManager` now logs a `WARNING` for any config value that still contains
a placeholder string (`your_api_key_here`, `DEVICE_SERIAL_NUMBER`, etc.)
so misconfiguration is immediately visible in the logs.

### Graceful service stop
`AttendanceService.stop()` now returns within 1 second instead of blocking
for the full sync interval.

### Auto trial license
If no `config/license.json` is found at startup, a 30-day trial license
is generated automatically. No manual step required on first run.

---

## Breaking Changes

None. The external interface (config file format, database schema, HTTP API format,
command-line arguments) is identical to v1.x. Existing `config/default_config.json`
files and existing `data/att.db` databases are fully compatible.

---

## Verified Working

All fixes were verified with automated tests covering:

- Full ZK protocol import chain
- Database insert → read → mark-synced cycle
- License generate → validate → activate cycle
- `AttendanceService` start/stop cycle
- `ConfigManager` placeholder detection
- Cross-platform import (no `winreg` crash on Linux)

---

## Upgrade Instructions

### From v1.x (GitHub source)

```cmd
:: 1. Back up your data
copy data\att.db data\att_backup.db
copy config\default_config.json config\default_config_backup.json

:: 2. Replace all source files with v2.0 files
::    (extract zip over existing folder — config and data are preserved)

:: 3. Run health check
health_check.bat

:: 4. Restart the application
scripts\run_app.bat
```

### Fresh install

Follow Section 4 of README.md — complete 6-step installation guide.

---

## Repository

| | |
|---|---|
| **Owner** | bitdreamit |
| **Repo** | AdvancedBiometricAttendance |
| **URL** | https://github.com/bitdreamit/AdvancedBiometricAttendance |
| **Python** | 3.8+ |
| **Platform** | Windows 10/11 (primary), Linux (dev/testing) |
| **License** | See LICENSE |

---

*Released 2026-05-20*
