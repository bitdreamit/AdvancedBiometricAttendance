# Advanced Biometric Attendance — Offline Agent

> **Version 2.2** | Python 3.8+ | Windows 10/11 | ZKTeco Devices

A **minimal offline bridge** between ZKTeco biometric devices and any online system
(Laravel, Django, Node.js, or any CMS). It captures fingerprint / face / card punches
in real time, stores them locally, and syncs bidirectionally with your server.

---

## Contents

1. [What This Tool Does — and Does NOT Do](#1-what-this-tool-does--and-does-not-do)
2. [System Architecture](#2-system-architecture)
3. [Database Design — 4 Tables Only](#3-database-design--4-tables-only)
4. [Bidirectional Sync — Exact API Contract](#4-bidirectional-sync--exact-api-contract)
5. [Tenant Support](#5-tenant-support)
6. [Shared Columns — What Both Sides Must Store](#6-shared-columns--what-both-sides-must-store)
7. [Installation](#7-installation)
8. [Configuration](#8-configuration)
9. [Auto Device Discovery](#9-auto-device-discovery)
10. [Running the Application](#10-running-the-application)
11. [Windows Service](#11-windows-service)
12. [Batch Attendance Pull](#12-batch-attendance-pull)
13. [All Scripts Reference](#13-all-scripts-reference)
14. [How Live Capture Works](#14-how-live-capture-works)
15. [Troubleshooting](#15-troubleshooting)
16. [Roadmap — Laravel Package](#16-roadmap--laravel-package)
17. [Changelog](#17-changelog)

---

## 1. What This Tool Does — and Does NOT Do

### ✅ This tool IS responsible for

| Responsibility | Details |
|---|---|
| Connect to ZKTeco devices | TCP port 4370, ZK binary protocol |
| Capture live punch events | Fingerprint, face, card, PIN |
| Store punches locally | SQLite — works fully offline |
| Sync punches to your server | HTTP POST on a schedule |
| Pull employees from your server | HTTP GET — keeps local mirror up to date |
| Push employee records to device | User ID, name, card number |
| Auto-discover devices on network | 128-thread subnet scanner |
| Batch pull stored records | Fallback for older device firmware |
| Run as Windows Service | Starts at boot, no login required |

### ❌ This tool is NOT responsible for

| Not here | Where it lives |
|---|---|
| Shift management | Your online system |
| Late / overtime calculation | Your online system |
| Leave management | Your online system |
| Attendance reports | Your online system |
| Department / HR data | Your online system |
| Web dashboard | Your online system |
| Payroll | Your online system |

**Design principle:** This tool is a **device sync bridge**. Keep it minimal so it works
with Laravel, Django, WordPress, custom APIs — anything. Your online system handles
all the business logic.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    OFFLINE AGENT (this tool)                            │
│                    runs on Windows PC on-site                           │
│                                                                         │
│   ZKTeco Devices ──TCP 4370──► Live Capture                            │
│   (finger/face/card)            Batch Pull        ┌───────────────┐    │
│                                 Auto Discover ───►│  SQLite DB    │    │
│                                                   │  4 tables     │    │
│                                                   │  works offline│    │
│                                                   └───────┬───────┘    │
└───────────────────────────────────────────────────────────┼────────────┘
                                                            │
                                              HTTP REST API │
                                            ┌───────────────┴───────────────┐
                                            │  ONLINE SERVER (your system)  │
                                            │  Laravel / Django / Node /    │
                                            │  any CMS                      │
                                            │                               │
                                            │  POST /api/biometric/attendance│ ◄── punches
                                            │  GET  /api/biometric/employees │ ──► employees
                                            │                               │
                                            │  Handles:                     │
                                            │  - Shifts & schedules         │
                                            │  - Late / overtime            │
                                            │  - Leave management           │
                                            │  - Reports & dashboard        │
                                            │  - HR & payroll               │
                                            └───────────────────────────────┘
```

### Sync flow summary

```
Online server ──(GET employees)──► Offline agent ──(push user record)──► ZK Device
ZK Device ──(punch event)──► Offline agent ──(POST punches)──► Online server
```

---

## 3. Database Design — 4 Tables Only

The local SQLite database has **exactly 4 tables**. Nothing more.

```sql
devices        — ZKTeco hardware connected to this agent
employees      — Mirror of online employee list (synced FROM server)
attendance     — Raw punch buffer (synced TO server)
configuration  — Agent settings (server URL, API key, etc.)
```

### Why only 4?

Your online system already has employees, departments, shifts, leave, reports.
Duplicating those tables here creates sync conflicts and maintenance burden.
This agent only stores what it absolutely needs to operate offline.

### `devices` table

```sql
CREATE TABLE devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT,                    -- NULL = single-tenant
    ip            TEXT NOT NULL,
    port          INTEGER DEFAULT 4370,
    serial_number TEXT NOT NULL UNIQUE,    -- hardware serial, never changes
    name          TEXT,                    -- friendly name e.g. "Main Gate"
    location      TEXT,                    -- e.g. "Ground Floor", "Block B"
    is_active     INTEGER DEFAULT 1,
    last_seen_at  TIMESTAMP,               -- last successful TCP connection
    -- sync columns (shared with online)
    remote_id     TEXT,                    -- device ID on your online server
    sync_status   TEXT DEFAULT 'local',    -- local | synced | conflict
    synced_at     TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Who manages it:** This agent writes it. Online server can mirror for dashboard visibility.

---

### `employees` table

```sql
CREATE TABLE employees (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT,                    -- NULL = single-tenant
    -- identity — must match online system exactly
    remote_id     TEXT,                    -- PK on your online server (UUID or int)
    employee_code TEXT NOT NULL,           -- e.g. EMP001
    name          TEXT NOT NULL,
    -- ZKTeco device identity
    zk_user_id    TEXT,                    -- integer 1–65535 stored on device
    card_number   TEXT,                    -- RFID card number if used
    -- minimal context (enriches punch data sent to server)
    department    TEXT,                    -- flat string, not a FK
    designation   TEXT,
    status        TEXT DEFAULT 'active',   -- active | inactive
    -- sync columns
    sync_status   TEXT DEFAULT 'pending',
    --  pending  = received from server, not yet pushed to ZK device
    --  synced   = confirmed on ZK device
    --  deleted  = server removed this employee
    synced_at     TIMESTAMP,
    checksum      TEXT,                    -- detects if server record changed
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(employee_code, tenant_id),
    UNIQUE(zk_user_id,    tenant_id)
);
```

**Who manages it:** Online server is master. This agent only mirrors.
Online pushes updates → agent stores locally → agent pushes user record to ZK device.

---

### `attendance` table

```sql
CREATE TABLE attendance (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT,                -- copied from employee.tenant_id
    -- punch identity
    zk_user_id        TEXT NOT NULL,       -- from ZK packet (device-side ID)
    employee_id       INTEGER,             -- local employee.id (may be NULL if unknown)
    remote_employee_id TEXT,              -- employee.remote_id (for your server)
    employee_code     TEXT,               -- denormalised — no join needed for sync
    -- punch data
    punched_at        TIMESTAMP NOT NULL, -- exact time from device clock
    device_sn         TEXT NOT NULL,      -- which device recorded the punch
    device_ip         TEXT,
    punch_type        TEXT,               -- NULL (server decides check_in/check_out)
    verify_type       TEXT,               -- fingerprint | face | card | pin | password
    -- sync columns
    sync_status       TEXT DEFAULT 'pending',
    --  pending   = waiting to be pushed to server
    --  synced    = server confirmed receipt
    --  error     = server returned error (see sync_error)
    --  duplicate = server already had this record
    remote_id         TEXT,              -- ID assigned by server after sync
    sync_error        TEXT,              -- last error message if status=error
    synced_at         TIMESTAMP,
    retry_count       INTEGER DEFAULT 0,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Who manages it:** This agent writes it from device events. Online server reads it via POST.

---

### `configuration` table

```sql
CREATE TABLE configuration (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Default keys seeded on first run:

| Key | Default | Purpose |
|-----|---------|---------|
| `server_url` | `''` | Online server base URL |
| `api_key` | `''` | Bearer token for API auth |
| `tenant_id` | `''` | Empty = single-tenant mode |
| `sync_interval` | `300` | Seconds between sync cycles |
| `retry_limit` | `5` | Max retries for failed records |
| `batch_size` | `100` | Records per HTTP request |
| `verify_ssl` | `true` | SSL certificate verification |
| `timezone` | `Asia/Dhaka` | For timestamp display |
| `agent_version` | `2.2` | This agent version |

---

## 4. Bidirectional Sync — Exact API Contract

Your online system must implement exactly 2 endpoints.

---

### Direction 1 — Online → Offline: Employee pull

**Agent calls:** `GET {server_url}/api/biometric/employees`

**Headers sent by agent:**
```
Authorization: Bearer {api_key}
X-Tenant-ID:   {tenant_id}      ← only if tenant_id is set
Content-Type:  application/json
Accept:        application/json
```

**Your server must return:**
```json
{
  "data": [
    {
      "id":            "uuid-or-integer",
      "employee_code": "EMP001",
      "name":          "Alice Rahman",
      "zk_user_id":    "5",
      "card_number":   "0012345678",
      "department":    "Engineering",
      "designation":   "Software Developer",
      "status":        "active",
      "tenant_id":     "tenant-abc"
    }
  ],
  "deleted_ids": ["uuid-of-removed-employee"]
}
```

**What the agent does with this:**
1. Upserts each employee into local `employees` table
2. Sets `sync_status = 'pending'` for new/changed employees
3. Pushes `pending` employees to ZK device (user ID + name + card)
4. Soft-deletes employees listed in `deleted_ids`

**Laravel example route:**
```php
Route::get('/api/biometric/employees', [BiometricController::class, 'employees'])
    ->middleware('auth:sanctum');
```

**Django example:**
```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def biometric_employees(request):
    employees = Employee.objects.filter(status='active')
    return Response({'data': EmployeeSerializer(employees, many=True).data, 'deleted_ids': []})
```

---

### Direction 2 — Offline → Online: Attendance push

**Agent calls:** `POST {server_url}/api/biometric/attendance`

**Headers sent by agent:**
```
Authorization: Bearer {api_key}
X-Tenant-ID:   {tenant_id}
Content-Type:  application/json
```

**Payload sent by agent:**
```json
{
  "punches": [
    {
      "id":                  1,
      "tenant_id":           "tenant-abc",
      "zk_user_id":          "5",
      "remote_employee_id":  "uuid-or-integer",
      "employee_code":       "EMP001",
      "punched_at":          "2026-05-20T09:05:00",
      "device_sn":           "ABC123456789",
      "device_ip":           "192.168.1.201",
      "punch_type":          null,
      "verify_type":         "fingerprint"
    }
  ]
}
```

**`punch_type` is always `null` from this agent.**
Your server determines check_in / check_out based on shift rules.
The raw timestamp and ZK user ID are what matters.

**Your server must return:**
```json
{
  "synced":     [1, 2, 3],
  "duplicates": [4],
  "errors":     [{"id": 5, "error": "employee not found"}]
}
```

Or with remote IDs (preferred — lets agent track server-side IDs):
```json
{
  "synced": [
    {"id": 1, "remote_id": "server-uuid-abc"},
    {"id": 2, "remote_id": "server-uuid-def"}
  ],
  "duplicates": [],
  "errors": []
}
```

**HTTP status codes:**
| Status | Meaning |
|--------|---------|
| 200 or 201 | Success — read body for synced/duplicates/errors |
| 207 | Multi-status — some synced, some errors |
| 409 | All duplicates |
| 401 | Bad API key |
| 422 | Validation error |
| 5xx | Server error — agent retries later |

**Laravel example:**
```php
Route::post('/api/biometric/attendance', [BiometricController::class, 'storePunches'])
    ->middleware('auth:sanctum');
```

```php
public function storePunches(Request $request)
{
    $synced = [];
    $duplicates = [];
    $errors = [];

    foreach ($request->input('punches', []) as $punch) {
        // Check duplicate
        $exists = Attendance::where('device_sn', $punch['device_sn'])
            ->where('zk_user_id', $punch['zk_user_id'])
            ->where('punched_at', $punch['punched_at'])
            ->exists();

        if ($exists) {
            $duplicates[] = $punch['id'];
            continue;
        }

        $record = Attendance::create([
            'tenant_id'          => $punch['tenant_id'],
            'employee_id'        => Employee::where('remote_id', $punch['remote_employee_id'])->value('id'),
            'zk_user_id'         => $punch['zk_user_id'],
            'employee_code'      => $punch['employee_code'],
            'punched_at'         => $punch['punched_at'],
            'device_sn'          => $punch['device_sn'],
            'verify_type'        => $punch['verify_type'],
        ]);

        $synced[] = ['id' => $punch['id'], 'remote_id' => $record->id];
    }

    return response()->json(compact('synced', 'duplicates', 'errors'));
}
```

---

## 5. Tenant Support

Multi-tenant means one agent installation serves multiple companies/branches.
Single-tenant means one agent for one company.

### Single-tenant setup (default)

Leave `tenant_id` blank in config. All records have `tenant_id = NULL`.
Your server does not need to send or receive `tenant_id`.

```json
"server": {
  "url":       "https://myschool.com/",
  "api_key":   "my-api-key",
  "tenant_id": ""
}
```

### Multi-tenant setup

Set `tenant_id` in config. The agent will:
- Filter all DB queries by `tenant_id`
- Include `tenant_id` in every punch payload
- Send `X-Tenant-ID` header on every request

```json
"server": {
  "url":       "https://saas-platform.com/",
  "api_key":   "client-abc-api-key",
  "tenant_id": "tenant-abc"
}
```

### How `tenant_id` maps to your online system

| Online system | Maps to |
|---|---|
| Laravel Tenancy (stancl/tenancy) | Tenant UUID |
| Filament multi-tenant | Team ID |
| Your User model | `user_id` or `company_id` |
| Client / school | Any unique string |
| No multi-tenancy | Leave empty (NULL) |

**Your server assigns tenant_id values. This agent just stores and forwards them.**

### Using `tenant_id` as a user/client ID

If your system uses "user = tenant" (SaaS model where each school/company is a user):

```json
"tenant_id": "user-uuid-from-your-system"
```

Your server receives `X-Tenant-ID: user-uuid-from-your-system` on every request
and can scope all data to that user.

---

## 6. Shared Columns — What Both Sides Must Store

These columns exist in both the offline agent and your online system.
They are the **sync contract** — changing them breaks sync.

### Shared in `employees`

| Column | Offline (this agent) | Online (your server) | Notes |
|--------|---------------------|----------------------|-------|
| `remote_id` | `employees.remote_id` | `employees.id` or `employees.uuid` | Primary key on server, foreign ref offline |
| `employee_code` | `employees.employee_code` | `employees.code` or `employees.emp_id` | Must be unique per tenant |
| `name` | `employees.name` | `employees.name` | Used in logs only |
| `zk_user_id` | `employees.zk_user_id` | `employees.zk_user_id` | Integer 1–65535, set on device, must match exactly |
| `card_number` | `employees.card_number` | `employees.card_number` | RFID card number |
| `tenant_id` | `employees.tenant_id` | `employees.tenant_id` | Null in single-tenant mode |
| `status` | `employees.status` | `employees.status` | active \| inactive |

### Shared in `attendance`

| Column | Offline (this agent) | Online (your server) | Notes |
|--------|---------------------|----------------------|-------|
| `remote_employee_id` | `attendance.remote_employee_id` | `attendance.employee_id` | Links punch to employee |
| `zk_user_id` | `attendance.zk_user_id` | `attendance.zk_user_id` | Device-side user ID — use for dedup |
| `employee_code` | `attendance.employee_code` | `attendance.employee_code` | Denormalised for easy display |
| `punched_at` | `attendance.punched_at` | `attendance.punched_at` | ISO 8601 timestamp — source of truth |
| `device_sn` | `attendance.device_sn` | `attendance.device_sn` | Which device, used for deduplication |
| `verify_type` | `attendance.verify_type` | `attendance.verify_type` | fingerprint \| face \| card \| pin |
| `tenant_id` | `attendance.tenant_id` | `attendance.tenant_id` | Scopes data |

### NOT shared (online only)

These columns exist only on your online system — the agent never sends or receives them:

| Column | Reason |
|--------|--------|
| `punch_type` (check_in/check_out) | Server determines from shift rules |
| `shift_id` | Server assigns |
| `late_minutes` | Server calculates |
| `working_hours` | Server calculates |
| `department_id` | Server manages HR structure |
| `leave_id` | Server manages leave |

### Deduplication rule

Your server must deduplicate using: `(zk_user_id + device_sn + punched_at)`.
This combination uniquely identifies any punch. If all three match an existing record,
return it in `duplicates[]`, not `errors[]`.

---

## 7. Installation

### Step 1 — Install Python 3.8+

Download from https://python.org — tick **Add Python to PATH**.

### Step 2 — Extract the project

Unzip to e.g. `C:\BiometricApp\`

### Step 3 — Run installer

```cmd
install.bat
```

Creates directories, installs dependencies, generates 30-day trial license.

### Step 4 — Configure

Open `config\default_config.json`:

```json
{
  "devices": [
    {
      "ip":            "192.168.1.201",
      "port":          4370,
      "serial_number": "YOUR_SERIAL_NUMBER",
      "name":          "Main Entrance",
      "enabled":       true,
      "sync_time":     true
    }
  ],
  "server": {
    "url":        "https://your-server.com/",
    "api_key":    "your-api-key",
    "tenant_id":  "",
    "sync_enabled": true
  },
  "sync": {
    "interval_seconds": 300
  }
}
```

### Step 5 — Health check

```cmd
health_check.bat
```

All lines must show `[OK]`.

### Step 6 — Test device

```cmd
python test_device.py 192.168.1.201
```

Expected: `PASS  Connected successfully`

### Step 7 — Start

```cmd
scripts\run_app.bat
```

---

## 8. Configuration

### Full `config\default_config.json` reference

```json
{
  "database": {
    "path": "data/att.db"
  },
  "logging": {
    "level": "INFO",
    "file": "logs/app.log",
    "max_size_mb": 10,
    "backup_count": 5
  },
  "sync": {
    "interval_seconds": 300,
    "batch_size": 100,
    "retry_limit": 5
  },
  "devices": [
    {
      "ip":            "192.168.1.201",
      "port":          4370,
      "serial_number": "SN001",
      "name":          "Front Door",
      "enabled":       true,
      "timeout":       30,
      "sync_time":     true
    }
  ],
  "server": {
    "url":          "",
    "api_key":      "",
    "tenant_id":    "",
    "sync_enabled": false,
    "verify_ssl":   true,
    "timeout":      30
  }
}
```

---

## 9. Auto Device Discovery

If you do not know the device IP address:

```cmd
scripts\auto_detect.bat
```

Or from command line:

```cmd
python auto_detect_devices.py                        ← scan local /24 subnet
python auto_detect_devices.py 192.168.10.0/24        ← specific subnet
python auto_detect_devices.py --save                 ← save results to config
python auto_detect_devices.py --timeout 2            ← more thorough scan
```

Scans 254 hosts with 128 parallel threads. Takes 5–15 seconds.

Output:
```
  Found 2 device(s):

  #     IP Address     Serial Number     Users   Device Time
  --  ---------------  ----------------  ------  -------------------
   1  192.168.1.201    ABC123456789          45  2026-05-20T10:30:00
   2  192.168.1.202    DEF987654321         120  2026-05-20T10:30:01
```

---

## 10. Running the Application

### Foreground (recommended for first run)

```cmd
scripts\run_app.bat
```

Expected output:
```
2026-05-20 10:30:00 - INFO - Starting Advanced Biometric Attendance v2.2
2026-05-20 10:30:01 - INFO - Connected to device 'ABC123456' at 192.168.1.201
2026-05-20 10:30:01 - INFO - Time synced on device 'ABC123456'
2026-05-20 10:30:01 - INFO - Started live capture on 1 device(s)
2026-05-20 10:30:01 - INFO - SyncEngine started — interval=300s tenant=none
```

When a finger/face/card is verified:
```
2026-05-20 10:31:15 - INFO - [LIVE] 192.168.1.201 → user=5 time=2026-05-20T10:31:15
2026-05-20 10:31:15 - INFO - Recorded: user=5 at=2026-05-20T10:31:15 device=ABC123456
```

When sync runs:
```
2026-05-20 10:35:00 - INFO - Pulled 45 employees from server
2026-05-20 10:35:01 - INFO - Pushed 2 new employees to ZK devices
2026-05-20 10:35:01 - INFO - Attendance push: 12 synced, 0 dupes, 0 errors
```

Stop: `Ctrl+C`

---

## 11. Windows Service

Runs at boot, no login required.

```cmd
scripts\install_service.bat     ← right-click → Run as administrator
sc query AdvancedBiometric      ← verify: STATE: 4 RUNNING
scripts\uninstall_service.bat   ← right-click → Run as administrator
```

Commands (from admin Command Prompt):

| Action | Command |
|--------|---------|
| Start | `sc start AdvancedBiometric` |
| Stop | `sc stop AdvancedBiometric` |
| Status | `sc query AdvancedBiometric` |
| GUI | `services.msc` |

---

## 12. Batch Attendance Pull

Pull all stored records from device in one pass (fallback for older firmware):

```cmd
scripts\batch_pull.bat
```

Or:
```cmd
python batch_pull_attendance.py                   ← one time, all records
python batch_pull_attendance.py --hours 24        ← last 24 hours
python batch_pull_attendance.py --sync            ← pull + push to server
python batch_pull_attendance.py --loop 300        ← repeat every 5 minutes
python batch_pull_attendance.py --clear           ← clear device log after pull
```

Deduplicates automatically — will not create double entries.

---

## 13. All Scripts Reference

| Script | Admin? | Purpose |
|--------|--------|---------|
| `install.bat` | No | First-time installer |
| `health_check.bat` | No | Pre-flight system checks |
| `activate_license.bat` | No | Enter a license key |
| `scripts\run_app.bat` | No | Start in foreground |
| `scripts\auto_detect.bat` | No | Scan network for ZK devices |
| `scripts\batch_pull.bat` | No | Batch attendance pull menu |
| `scripts\install_service.bat` | **YES** | Register Windows service |
| `scripts\uninstall_service.bat` | **YES** | Remove Windows service |

Python commands:
```cmd
python auto_detect_devices.py [subnet] [--save] [--timeout N]
python batch_pull_attendance.py [--ip IP] [--hours N] [--sync] [--clear] [--loop N]
python test_device.py [IP]
python generate_license.py [info]
```

---

## 14. How Live Capture Works

```
ZK Device firmware
  └── Employee puts finger/face/card on reader
  └── Device matches against stored templates internally
  └── If NOT enrolled → silent reject → 0 network traffic
  └── If enrolled → sends ONE 40-byte TCP packet to Python agent

Python agent
  └── LiveCapture thread receives packet
  └── Parses: zk_user_id + punched_at + verify_type
  └── Looks up employee in local DB by zk_user_id
  └── Inserts into attendance table (status=pending)
  └── SyncEngine thread picks it up every sync_interval seconds
  └── POSTs to your server → marks status=synced

Key point: 20,000 people walking past a camera = 0 network packets.
Only enrolled users who successfully verify generate any traffic.
CPU load between punch events is effectively zero.
```

---

## 15. Troubleshooting

**Device not connecting**
```cmd
python test_device.py 192.168.1.201
```
- Check `ping 192.168.1.201`
- Open firewall: `Windows Defender Firewall → Inbound → New Rule → Port → TCP 4370 → Allow`
- Close any ZKTeco software (only one TCP client at a time)

**No employees being pulled**
- Set `server_url` and `api_key` in config
- Check your server returns `GET /api/biometric/employees`
- Check `logs\app.log` for HTTP error codes

**Punches not reaching server**
- Check `logs\app.log` for sync errors
- Verify endpoint: `POST /api/biometric/attendance`
- Check API key: `Authorization: Bearer {api_key}`
- Try `python batch_pull_attendance.py --sync` to force an immediate sync

**Sync skipped every cycle**
```
DEBUG - Server not configured — skipping sync cycle
```
Set `server_url` and `api_key` in config. Restart the app.

**winreg error (Linux/macOS)**
Normal — Windows service features not available. All attendance features work fine.

**Debugger killed on startup**
```cmd
set DEV_MODE=1
python src\main.py
```

**Check database directly**
```cmd
python -c "
import sqlite3
conn = sqlite3.connect('data/att.db')
print('Pending:', conn.execute(\"SELECT COUNT(*) FROM attendance WHERE sync_status='pending'\").fetchone()[0])
print('Synced:',  conn.execute(\"SELECT COUNT(*) FROM attendance WHERE sync_status='synced'\").fetchone()[0])
print('Employees:', conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0])
"
```

---

## 16. Roadmap — Laravel Package

The companion Laravel package `bitdreamit/biometric-attendance` (in development)
will implement the two API endpoints and provide a full web panel.

### Endpoints it will provide

```
GET  /api/biometric/employees        ← this agent pulls from here
POST /api/biometric/attendance       ← this agent pushes to here
```

### Features planned

- Employee and department management
- ZK user ID and card assignment UI
- Shift builder (Morning, Evening, Night, Flexible, custom)
- Attendance processing: check_in/check_out determination, late/overtime
- Leave management with approval workflow
- Daily and monthly reports with export (CSV, PDF)
- Real-time punch notifications (Pusher / WebSockets)
- Multi-tenant support (stancl/tenancy compatible)
- Role-based access: Admin, HR, Manager, Employee
- Mobile-friendly dashboard

### How to implement the endpoints yourself (any framework)

**Minimum viable server (Python Flask example):**

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/biometric/employees')
def employees():
    # Return your employee list
    return jsonify({
        "data": [
            {
                "id": "1",
                "employee_code": "EMP001",
                "name": "Alice Rahman",
                "zk_user_id": "5",
                "card_number": None,
                "department": "Engineering",
                "designation": "Developer",
                "status": "active",
                "tenant_id": None
            }
        ],
        "deleted_ids": []
    })

@app.route('/api/biometric/attendance', methods=['POST'])
def attendance():
    punches = request.json.get('punches', [])
    synced = []
    for punch in punches:
        # Save to your DB here
        # YourModel.create(punch)
        synced.append({"id": punch["id"], "remote_id": "server-generated-id"})
    return jsonify({"synced": synced, "duplicates": [], "errors": []})
```

---

## 17. Changelog

### v2.2 — 2026-05-20

- Simplified database to 4 tables only (removed shifts, leave, departments, attendance_log)
- Added `tenant_id` to employees and attendance for multi-tenant support
- Added `remote_id`, `sync_status`, `synced_at`, `checksum` sync columns
- New `SyncEngine` handles all bidirectional sync
- Employee pull: GET employees from server → store locally → push to ZK device
- Attendance push: POST punches in batches with retry logic and error tracking
- Duplicate detection in attendance: exact-second guard on insert
- `X-Tenant-ID` header sent on all server requests
- `deleted_ids` handling: soft-deletes employees removed on server
- Fully documented API contract (request/response format, status codes)
- `AttendanceService` simplified — delegates sync to `SyncEngine`

### v2.1 — 2026-05-20

- Auto device discovery (128-thread subnet scanner)
- Batch attendance pull with deduplication
- `scripts\auto_detect.bat`, `scripts\batch_pull.bat`

### v2.0 — 2026-05-20

- Complete rewrite fixing 22 bugs from original repository
- Full ZK binary protocol implementation
- Windows service support
- Cross-platform import fixes (winreg guard)

---

## Project Structure

```
AdvancedBiometricAttendance/
├── src/
│   ├── main.py
│   ├── biometric/
│   │   ├── auto_detect.py          Subnet scanner
│   │   ├── zk_device.py            Device wrapper
│   │   └── zk_lib/                 ZK binary protocol
│   │       ├── base.py
│   │       ├── const.py
│   │       ├── attendance.py
│   │       ├── user.py
│   │       ├── finger.py
│   │       └── exception.py
│   ├── core/
│   │   ├── database.py             4-table SQLite manager
│   │   ├── sync.py                 Bidirectional sync engine
│   │   ├── device_manager.py       Multi-device + live capture
│   │   ├── attendance_service.py   Queue drain + sync orchestration
│   │   └── batch_attendance.py     Scheduled batch pull
│   └── utils/
│       ├── config_manager.py
│       ├── license_manager.py
│       ├── logger.py
│       └── windows_utils.py
├── config/
│   └── default_config.json         Edit this — ONLY file you need to change
├── data/att.db                     Auto-created SQLite database
├── logs/app.log                    Auto-created log file
├── scripts/
│   ├── run_app.bat
│   ├── auto_detect.bat
│   ├── batch_pull.bat
│   ├── install_service.bat         Run as administrator
│   └── uninstall_service.bat       Run as administrator
├── install.bat
├── health_check.bat
├── activate_license.bat
├── auto_detect_devices.py
├── batch_pull_attendance.py
├── test_device.py
├── generate_license.py
└── requirements.txt
```

---

*bitdreamit/AdvancedBiometricAttendance — v2.2 — 2026-05-20*
