# Integration Contract
## AdvancedBiometricAttendance (Python) ↔ laravel-biometric-attendance

This document is the single canonical contract between the offline Python agent
and the online Laravel server. Both repos reference this file.

---

## Two endpoints. That is all the server needs.

| Direction | Method | URL | Purpose |
|-----------|--------|-----|---------|
| Server → Agent | `GET` | `/api/biometric/employees` | Agent pulls employee list |
| Agent → Server | `POST` | `/api/biometric/attendance` | Agent pushes raw punches |
| Agent → Server | `POST` | `/api/biometric/heartbeat` | Agent reports health (optional) |
| Server → Agent | `GET` | `/api/biometric/agent-commands` | Agent polls for commands (optional) |

Authentication: `Authorization: Bearer {api_key}` on every request.
Tenant header: `X-Tenant-ID: {tenant_id}` when multi-tenant mode is enabled.

---

## GET /api/biometric/employees

Agent calls this every `sync.interval_seconds` (default 5 minutes).

### Response the server must return

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
      "designation":   "Developer",
      "status":        "active",
      "tenant_id":     "tenant-abc"
    }
  ],
  "deleted_ids": ["uuid-of-removed-employee"]
}
```

### What the agent does

1. Upserts each employee into local `employees` table
2. Sets `sync_status = 'pending'` for new or changed employees
3. Pushes pending employees to ZKTeco device (user ID + name + card)
4. Soft-deletes employees in `deleted_ids`

---

## POST /api/biometric/attendance

Agent calls this every `sync.interval_seconds` with a batch of pending punches.

### Payload the agent sends

```json
{
  "punches": [
    {
      "id":                 1,
      "tenant_id":          "tenant-abc",
      "zk_user_id":         "5",
      "remote_employee_id": "uuid-or-integer",
      "employee_code":      "EMP001",
      "punched_at":         "2026-05-20T09:05:00",
      "device_sn":          "ABC123456789",
      "device_ip":          "192.168.1.201",
      "punch_type":         null,
      "verify_type":        "fingerprint"
    }
  ]
}
```

**`punch_type` is always `null` from the agent.**
The server determines `check_in` / `check_out` from shift rules.

### Response the server must return

```json
{
  "synced":     [{"id": 1, "remote_id": "server-uuid-abc"}],
  "duplicates": [2],
  "errors":     [{"id": 3, "error": "employee not found"}]
}
```

Short form also accepted:

```json
{
  "synced":     [1, 2],
  "duplicates": [],
  "errors":     []
}
```

### HTTP status codes

| Code | Meaning |
|------|---------|
| 200 / 201 | Success |
| 207 | Multi-status (some synced, some errors) |
| 409 | All duplicates |
| 401 | Bad API key |
| 5xx | Server error — agent retries with exponential backoff |

---

## POST /api/biometric/heartbeat (optional)

Agent posts this every sync cycle. Server can use it to show agent health on the dashboard.

```json
{
  "tenant_id":     "tenant-abc",
  "agent_version": "2.2",
  "devices": [
    { "serial_number": "ABC123", "ip": "192.168.1.201", "connected": true }
  ],
  "queue": {
    "pending": 5,
    "synced": 1240,
    "error": 0,
    "duplicate": 3
  }
}
```

Server should respond with `{"status": "ok"}`.

---

## GET /api/biometric/agent-commands (optional)

Agent polls this every sync cycle when `agent_api.enabled = true`.
Server returns a list of commands for the agent to execute.

```json
{
  "commands": [
    { "type": "sync_now" },
    { "type": "clear_device_log", "data": { "device_sn": "ABC123" } },
    { "type": "enroll_user", "data": {
        "device_sn": "ABC123",
        "employee": { "zk_user_id": "5", "name": "Alice", "card_number": "0012345678" }
    }}
  ]
}
```

Supported command types: `sync_now`, `clear_device_log`, `enroll_user`

---

## Deduplication rule

The server must deduplicate using: **(zk_user_id + device_sn + punched_at)**
within a ±60 second window. If all three match an existing record, return it
in `duplicates[]`, not `errors[]`.

---

## Shared columns — must exist in both databases

| Column | Python (offline) | Laravel (online) | Notes |
|--------|-----------------|------------------|-------|
| `remote_id` | `employees.remote_id` | `biometric_employees.id` | Server's PK |
| `employee_code` | `employees.employee_code` | `biometric_employees.employee_code` | Unique per tenant |
| `zk_user_id` | `employees.zk_user_id` | `biometric_employees.zk_user_id` | Integer on device |
| `card_number` | `employees.card_number` | `biometric_employees.card_number` | RFID |
| `tenant_id` | both tables | both tables | Null = single-tenant |
| `punched_at` | `attendance.punched_at` | `biometric_attendance.punched_at` | ISO 8601 |
| `device_sn` | `attendance.device_sn` | `biometric_attendance.device_sn` | For dedup |
| `verify_type` | `attendance.verify_type` | `biometric_attendance.verify_type` | fingerprint/face/card/pin |

---

## Tenant ID mapping

| Your system | Set tenant_id to |
|-------------|-----------------|
| Single company | `""` (leave blank) |
| Laravel stancl/tenancy | Tenant UUID |
| Filament multi-tenant | Team ID |
| SaaS (company per client) | `company_id` or `user_id` |

The agent sends `X-Tenant-ID` header on every request.
The server must scope all queries to that tenant.

---

## Agent HTTP API (optional, localhost only)

When `agent_api.enabled = true` in config, the agent runs a local HTTP server:

| Method | URL | Description |
|--------|-----|-------------|
| GET | `http://127.0.0.1:5000/status` | Agent health snapshot |
| POST | `http://127.0.0.1:5000/sync-now` | Trigger immediate sync |
| GET | `http://127.0.0.1:5000/commands` | Poll + execute Laravel commands |

Protect with `agent_api.token` in config.

---

*AdvancedBiometricAttendance v2.2 — bitdreamit*
