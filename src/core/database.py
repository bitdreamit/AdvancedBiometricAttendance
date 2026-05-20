# src/core/database.py
"""
Advanced Biometric Attendance — Offline Agent Database

DESIGN PHILOSOPHY
─────────────────
This tool is a DEVICE BRIDGE, not an HR system.

It holds ONLY what it needs to:
  1. Know which employees exist (to map ZK user_id → employee)
  2. Know which devices to connect to
  3. Buffer raw punch events until they are synced online
  4. Support bidirectional sync with any online system

All HR logic (shifts, leave, overtime, reports, departments)
lives ONLY in the online system (Laravel, Django, etc.).

TABLES (4 only)
───────────────
  devices       — ZKTeco hardware inventory
  employees     — Minimal employee registry (synced FROM online)
  attendance    — Raw punch buffer (synced TO online)
  configuration — Agent settings (server URL, API key, etc.)

TENANT SUPPORT
──────────────
  tenant_id on employees and attendance.
  NULL tenant_id = single-tenant / no multi-tenancy.
  Non-null = the employee/record belongs to that tenant.
  The online system assigns tenant_id values.

BIDIRECTIONAL SYNC
──────────────────
  Online → Offline : employees table (who is enrolled)
  Offline → Online : attendance table (punch events)

SYNC COLUMNS (present on both sides)
─────────────────────────────────────
  remote_id      — primary key on the online server
  synced_at      — when this row was last confirmed synced
  sync_status    — pending | synced | error | conflict
  checksum       — SHA-256 of key fields for conflict detection
"""

import sqlite3
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, db_path: str = "data/att.db", config: Dict = None):
        self.db_path = db_path
        self.config  = config or {}
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    # ── Connection ────────────────────────────────────────────────────── #

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ── Schema ────────────────────────────────────────────────────────── #

    def _init_database(self):
        ddl = """

        -- ── devices ─────────────────────────────────────────────────────
        -- Who:    managed by this offline agent
        -- Sync:   agent registers devices; online can read device list
        -- Online: may mirror this table for dashboard visibility
        CREATE TABLE IF NOT EXISTS devices (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     TEXT,               -- NULL = no multi-tenancy
            ip            TEXT NOT NULL,
            port          INTEGER NOT NULL DEFAULT 4370,
            serial_number TEXT NOT NULL UNIQUE,
            name          TEXT,
            location      TEXT,
            is_active     INTEGER NOT NULL DEFAULT 1,
            last_seen_at  TIMESTAMP,          -- last successful connection
            -- sync columns
            remote_id     TEXT,               -- device ID on online server
            sync_status   TEXT NOT NULL DEFAULT 'local',
            --   local     = exists only offline, not yet pushed
            --   synced    = confirmed on online server
            --   conflict  = mismatch between local and remote
            synced_at     TIMESTAMP,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── employees ────────────────────────────────────────────────────
        -- Who:    seeded FROM online system (bidirectional)
        -- Why:    needed offline to map ZK user_id → employee
        -- Rule:   online system is master; this is a local mirror
        -- Sync:   online pushes new/updated employees → agent stores here
        --         agent reads this to enrich attendance records
        CREATE TABLE IF NOT EXISTS employees (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     TEXT,               -- NULL = single-tenant mode
            -- identity (must match online system exactly)
            remote_id     TEXT,               -- PK on online server (UUID or int)
            employee_code TEXT NOT NULL,      -- e.g. EMP001 — used in reports
            name          TEXT NOT NULL,
            -- ZKTeco device identity
            -- The ZK device stores users by zk_user_id (integer, 1–65535)
            -- This is what appears in attendance punch packets
            zk_user_id    TEXT,               -- ZK device user id
            card_number   TEXT,               -- RFID card number if used
            -- minimal context (enough to enrich punch data sent to server)
            department    TEXT,               -- flat string, not FK
            designation   TEXT,
            -- status
            status        TEXT NOT NULL DEFAULT 'active', -- active | inactive
            -- sync columns
            sync_status   TEXT NOT NULL DEFAULT 'pending',
            --   pending   = received from server, not yet pushed to device
            --   synced    = confirmed on device
            --   conflict  = local device data differs from server
            --   deleted   = server deleted this employee
            synced_at     TIMESTAMP,          -- when last synced from server
            checksum      TEXT,               -- SHA-256 of remote_id+employee_code+name
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_code, tenant_id),
            UNIQUE(zk_user_id,    tenant_id)
        );

        -- ── attendance ───────────────────────────────────────────────────
        -- Who:    written by this offline agent (from ZK device events)
        -- Why:    buffer of raw punch events until pushed to online server
        -- Rule:   this is the SOURCE OF TRUTH for punch timestamps
        -- Sync:   agent pushes rows to online; online processes them
        CREATE TABLE IF NOT EXISTS attendance (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     TEXT,               -- copied from employee.tenant_id
            -- punch identity
            zk_user_id    TEXT NOT NULL,      -- from ZK packet (device-side id)
            employee_id   INTEGER REFERENCES employees(id) ON DELETE SET NULL,
            remote_employee_id TEXT,          -- employee.remote_id (for server)
            employee_code TEXT,               -- denormalised for easy sync
            -- punch data
            punched_at    TIMESTAMP NOT NULL, -- exact time from device
            device_sn     TEXT NOT NULL,      -- which device
            device_ip     TEXT,
            punch_type    TEXT,               -- check_in | check_out | NULL (server decides)
            verify_type   TEXT,               -- fingerprint | face | card | pin | password
            -- sync columns
            sync_status   TEXT NOT NULL DEFAULT 'pending',
            --   pending   = waiting to be pushed to online server
            --   synced    = confirmed received by online server
            --   error     = server returned error (see sync_error)
            --   duplicate = server said it already has this record
            remote_id     TEXT,               -- PK assigned by online server after sync
            sync_error    TEXT,               -- last error message if status=error
            synced_at     TIMESTAMP,          -- when server confirmed receipt
            retry_count   INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── configuration ────────────────────────────────────────────────
        -- Agent settings — server URL, API key, sync interval, etc.
        CREATE TABLE IF NOT EXISTS configuration (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Indexes ──────────────────────────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_att_zk_user    ON attendance(zk_user_id);
        CREATE INDEX IF NOT EXISTS idx_att_punched_at ON attendance(punched_at);
        CREATE INDEX IF NOT EXISTS idx_att_sync       ON attendance(sync_status);
        CREATE INDEX IF NOT EXISTS idx_att_tenant     ON attendance(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_emp_remote     ON employees(remote_id);
        CREATE INDEX IF NOT EXISTS idx_emp_zk_user    ON employees(zk_user_id);
        CREATE INDEX IF NOT EXISTS idx_emp_code       ON employees(employee_code);
        CREATE INDEX IF NOT EXISTS idx_emp_tenant     ON employees(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_emp_card       ON employees(card_number);
        CREATE INDEX IF NOT EXISTS idx_dev_sn         ON devices(serial_number);
        CREATE INDEX IF NOT EXISTS idx_dev_tenant     ON devices(tenant_id);
        """

        with self._get_connection() as conn:
            # Use executescript which handles full SQL including comments
            try:
                conn.executescript(ddl)
            except sqlite3.Error as e:
                # executescript stops on first error; fall back to statement-by-statement
                logger.warning(f"executescript failed ({e}), retrying per-statement")
                import re
                # Strip single-line comments, then split on semicolons
                clean = re.sub(r'--[^\n]*', '', ddl)
                for stmt in clean.split(';'):
                    s = stmt.strip()
                    if s and any(kw in s.upper() for kw in ('CREATE','INSERT','DROP','ALTER')):
                        try:
                            conn.execute(s)
                        except sqlite3.Error as e2:
                            logger.debug(f"DDL stmt error: {e2} | {s[:60]}")
            self._seed_defaults(conn)
            conn.commit()
        logger.info("Database initialised — 4 tables")

    def _seed_defaults(self, conn):
        defaults = {
            'server_url':       '',
            'api_key':          '',
            'tenant_id':        '',        # empty = single-tenant
            'sync_interval':    '300',     # seconds
            'retry_limit':      '5',       # max retry attempts per record
            'batch_size':       '100',     # records per HTTP request
            'verify_ssl':       'true',
            'timezone':         'Asia/Dhaka',
            'agent_version':    '2.2',
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO configuration (key, value) VALUES (?, ?)",
                (k, v)
            )

    # ── Helpers ───────────────────────────────────────────────────────── #

    def _conn(self):
        return self._get_connection()

    def fetchall(self, sql: str, params=()) -> List[Dict]:
        try:
            with self._conn() as conn:
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.Error as e:
            logger.error(f"fetchall: {e}")
            return []

    def fetchone(self, sql: str, params=()) -> Optional[Dict]:
        try:
            with self._conn() as conn:
                r = conn.execute(sql, params).fetchone()
                return dict(r) if r else None
        except sqlite3.Error as e:
            logger.error(f"fetchone: {e}")
            return None

    def execute(self, sql: str, params=(), commit: bool = True) -> bool:
        try:
            with self._conn() as conn:
                conn.execute(sql, params)
                if commit:
                    conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"execute: {e} | {sql[:60]}")
            return False

    @staticmethod
    def _checksum(*parts) -> str:
        raw = '|'.join(str(p or '') for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Configuration ─────────────────────────────────────────────────── #

    def get_config(self, key: str, default: Any = None) -> Any:
        r = self.fetchone("SELECT value FROM configuration WHERE key=?", (key,))
        return r['value'] if r else default

    def set_config(self, key: str, value: Any) -> bool:
        return self.execute(
            "INSERT OR REPLACE INTO configuration (key,value,updated_at) "
            "VALUES (?,?,CURRENT_TIMESTAMP)",
            (key, str(value))
        )

    def get_all_config(self) -> Dict:
        rows = self.fetchall("SELECT key, value FROM configuration")
        return {r['key']: r['value'] for r in rows}

    # ── Devices ───────────────────────────────────────────────────────── #

    def upsert_device(self, ip: str, port: int, serial_number: str,
                      name: str = None, location: str = None,
                      tenant_id: str = None, remote_id: str = None) -> bool:
        return self.execute(
            """INSERT INTO devices (ip, port, serial_number, name, location,
                                   tenant_id, remote_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(serial_number) DO UPDATE SET
                 ip=excluded.ip, port=excluded.port, name=excluded.name,
                 location=excluded.location, remote_id=excluded.remote_id,
                 last_seen_at=CURRENT_TIMESTAMP""",
            (ip, port, serial_number, name, location, tenant_id, remote_id)
        )

    # backwards compat alias
    def add_device(self, ip, port, serial_number, name=None, location=None):
        return self.upsert_device(ip, port, serial_number, name, location)

    def get_devices(self, tenant_id: str = None) -> List[Dict]:
        if tenant_id:
            return self.fetchall(
                "SELECT * FROM devices WHERE is_active=1 AND tenant_id=? ORDER BY name",
                (tenant_id,)
            )
        return self.fetchall(
            "SELECT * FROM devices WHERE is_active=1 ORDER BY name"
        )

    def touch_device(self, serial_number: str) -> bool:
        return self.execute(
            "UPDATE devices SET last_seen_at=CURRENT_TIMESTAMP WHERE serial_number=?",
            (serial_number,)
        )

    def mark_device_synced(self, serial_number: str, remote_id: str) -> bool:
        return self.execute(
            "UPDATE devices SET remote_id=?, sync_status='synced', synced_at=CURRENT_TIMESTAMP "
            "WHERE serial_number=?",
            (remote_id, serial_number)
        )

    # ── Employees ─────────────────────────────────────────────────────── #

    def upsert_employee(self, employee_code: str, name: str,
                        remote_id: str = None,
                        zk_user_id: str = None,
                        card_number: str = None,
                        department: str = None,
                        designation: str = None,
                        status: str = 'active',
                        tenant_id: str = None) -> Optional[int]:
        """
        Insert or update an employee record.
        Called when the online server pushes employee data to this agent.
        Returns local id.
        """
        checksum = self._checksum(remote_id, employee_code, name, tenant_id)
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO employees
                       (tenant_id, remote_id, employee_code, name,
                        zk_user_id, card_number, department, designation,
                        status, checksum, sync_status, synced_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'synced',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                       ON CONFLICT(employee_code, tenant_id) DO UPDATE SET
                         remote_id     = excluded.remote_id,
                         name          = excluded.name,
                         zk_user_id    = excluded.zk_user_id,
                         card_number   = excluded.card_number,
                         department    = excluded.department,
                         designation   = excluded.designation,
                         status        = excluded.status,
                         checksum      = excluded.checksum,
                         sync_status   = 'synced',
                         synced_at     = CURRENT_TIMESTAMP,
                         updated_at    = CURRENT_TIMESTAMP""",
                    (tenant_id, remote_id, employee_code, name,
                     str(zk_user_id) if zk_user_id else None,
                     card_number, department, designation, status, checksum)
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id FROM employees WHERE employee_code=? AND (tenant_id=? OR (tenant_id IS NULL AND ? IS NULL))",
                    (employee_code, tenant_id, tenant_id)
                ).fetchone()
                return row['id'] if row else None
        except sqlite3.Error as e:
            logger.error(f"upsert_employee: {e}")
            return None

    def get_employee_by_zk_id(self, zk_user_id: str,
                               tenant_id: str = None) -> Optional[Dict]:
        """Resolve a ZK punch user_id to an employee record."""
        if tenant_id:
            return self.fetchone(
                "SELECT * FROM employees WHERE zk_user_id=? AND tenant_id=? AND status='active'",
                (str(zk_user_id), tenant_id)
            )
        return self.fetchone(
            "SELECT * FROM employees WHERE zk_user_id=? AND status='active'",
            (str(zk_user_id),)
        )

    def get_employee_by_card(self, card_number: str,
                              tenant_id: str = None) -> Optional[Dict]:
        if tenant_id:
            return self.fetchone(
                "SELECT * FROM employees WHERE card_number=? AND tenant_id=? AND status='active'",
                (card_number, tenant_id)
            )
        return self.fetchone(
            "SELECT * FROM employees WHERE card_number=? AND status='active'",
            (card_number,)
        )

    def get_employees(self, tenant_id: str = None,
                      active_only: bool = True) -> List[Dict]:
        sql    = "SELECT * FROM employees WHERE 1=1"
        params = []
        if active_only:
            sql += " AND status='active'"
        if tenant_id:
            sql += " AND tenant_id=?"
            params.append(tenant_id)
        sql += " ORDER BY name"
        return self.fetchall(sql, params)

    def mark_employee_deleted(self, remote_id: str,
                               tenant_id: str = None) -> bool:
        """Soft-delete when online server removes an employee."""
        if tenant_id:
            return self.execute(
                "UPDATE employees SET status='inactive', sync_status='deleted', "
                "updated_at=CURRENT_TIMESTAMP WHERE remote_id=? AND tenant_id=?",
                (remote_id, tenant_id)
            )
        return self.execute(
            "UPDATE employees SET status='inactive', sync_status='deleted', "
            "updated_at=CURRENT_TIMESTAMP WHERE remote_id=?",
            (remote_id,)
        )

    def get_employees_pending_device_push(self,
                                          tenant_id: str = None) -> List[Dict]:
        """Employees synced from server but not yet pushed to ZK device."""
        sql    = "SELECT * FROM employees WHERE sync_status='pending'"
        params = []
        if tenant_id:
            sql += " AND tenant_id=?"
            params.append(tenant_id)
        return self.fetchall(sql, params)

    def mark_employee_pushed(self, employee_id: int) -> bool:
        """Mark employee as successfully pushed to ZK device."""
        return self.execute(
            "UPDATE employees SET sync_status='synced', synced_at=CURRENT_TIMESTAMP WHERE id=?",
            (employee_id,)
        )

    # ── Attendance ────────────────────────────────────────────────────── #

    def insert_attendance(self, zk_user_id: str, punched_at: str,
                           device_sn: str, device_ip: str = None,
                           verify_type: str = None,
                           tenant_id: str = None) -> bool:
        """
        Record a raw punch event from a ZK device.
        Enriches with employee data if available.
        Skips true duplicates (same user + same second on same device).
        """
        # Duplicate guard — exact same second on same device
        existing = self.fetchone(
            """SELECT id FROM attendance
               WHERE zk_user_id=? AND device_sn=?
                 AND ABS(strftime('%s',punched_at)-strftime('%s',?)) < 2""",
            (str(zk_user_id), device_sn, punched_at)
        )
        if existing:
            logger.debug(f"Duplicate punch skipped: user={zk_user_id} at={punched_at}")
            return False

        # Resolve employee
        emp = self.get_employee_by_zk_id(str(zk_user_id), tenant_id)
        emp_id         = emp['id']            if emp else None
        remote_emp_id  = emp['remote_id']     if emp else None
        employee_code  = emp['employee_code'] if emp else None
        resolved_tenant= emp['tenant_id']     if emp else tenant_id

        return self.execute(
            """INSERT INTO attendance
               (tenant_id, zk_user_id, employee_id, remote_employee_id,
                employee_code, punched_at, device_sn, device_ip, verify_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (resolved_tenant, str(zk_user_id), emp_id, remote_emp_id,
             employee_code, punched_at, device_sn, device_ip, verify_type)
        )

    def get_pending_attendance(self, limit: int = 100,
                                tenant_id: str = None) -> List[Dict]:
        """Records waiting to be pushed to the online server."""
        sql    = "SELECT * FROM attendance WHERE sync_status='pending' ORDER BY punched_at LIMIT ?"
        params = [limit]
        if tenant_id:
            sql = ("SELECT * FROM attendance WHERE sync_status='pending' "
                   "AND tenant_id=? ORDER BY punched_at LIMIT ?")
            params = [tenant_id, limit]
        return self.fetchall(sql, params)

    def get_failed_attendance(self, max_retries: int = 5,
                               tenant_id: str = None) -> List[Dict]:
        """Records that errored but have retries remaining."""
        sql    = ("SELECT * FROM attendance WHERE sync_status='error' "
                  "AND retry_count < ? ORDER BY punched_at LIMIT 100")
        params = [max_retries]
        if tenant_id:
            sql = ("SELECT * FROM attendance WHERE sync_status='error' "
                   "AND retry_count < ? AND tenant_id=? ORDER BY punched_at LIMIT 100")
            params = [max_retries, tenant_id]
        return self.fetchall(sql, params)

    def mark_attendance_synced(self, ids: List[int],
                                remote_ids: Dict[int, str] = None) -> bool:
        """Mark records as successfully received by the online server."""
        if not ids:
            return True
        remote_ids = remote_ids or {}
        try:
            with self._conn() as conn:
                for rid in ids:
                    conn.execute(
                        """UPDATE attendance SET
                             sync_status = 'synced',
                             remote_id   = ?,
                             synced_at   = CURRENT_TIMESTAMP,
                             sync_error  = NULL
                           WHERE id = ?""",
                        (remote_ids.get(rid), rid)
                    )
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"mark_attendance_synced: {e}")
            return False

    def mark_attendance_error(self, ids: List[int], error: str) -> bool:
        if not ids:
            return True
        ph = ','.join('?' * len(ids))
        return self.execute(
            f"UPDATE attendance SET sync_status='error', sync_error=?, "
            f"retry_count=retry_count+1 WHERE id IN ({ph})",
            [error] + ids
        )

    def mark_attendance_duplicate(self, ids: List[int]) -> bool:
        if not ids:
            return True
        ph = ','.join('?' * len(ids))
        return self.execute(
            f"UPDATE attendance SET sync_status='duplicate' WHERE id IN ({ph})", ids
        )

    def get_attendance_stats(self, tenant_id: str = None) -> Dict:
        sql    = "SELECT sync_status, COUNT(*) as cnt FROM attendance"
        params = []
        if tenant_id:
            sql += " WHERE tenant_id=?"
            params.append(tenant_id)
        sql += " GROUP BY sync_status"
        rows = self.fetchall(sql, params)
        return {r['sync_status']: r['cnt'] for r in rows}

    # ── Sync helpers ──────────────────────────────────────────────────── #

    def get_unsynced_attendance(self, limit: int = 100) -> List[Dict]:
        """Alias kept for backwards compatibility."""
        return self.get_pending_attendance(limit)
