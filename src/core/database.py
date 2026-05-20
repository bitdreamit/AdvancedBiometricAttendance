# src/core/database.py
"""
Complete database layer for the Advanced Biometric Attendance System.

Tables:
  devices        — ZKTeco hardware devices
  employees      — Staff registered in the system
  biometrics     — Finger/face/card data per employee
  shifts         — Shift definitions (Morning, Evening, Night, Flexible)
  employee_shifts— Which employee works which shift
  attendance     — Raw punch records from devices
  attendance_log — Processed IN/OUT pairs with calculated hours
  leave_types    — Leave categories (Annual, Sick, Casual, etc.)
  leave_requests — Employee leave applications
  configuration  — App key/value settings
"""
import sqlite3
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = "data/att.db", config: Dict = None):
        self.db_path = db_path
        self.config  = config or {}
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row          # rows behave like dicts
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ------------------------------------------------------------------ #
    # Schema                                                               #
    # ------------------------------------------------------------------ #

    def _init_database(self):
        ddl = """

        -- ── Devices ─────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS devices (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ip            TEXT    NOT NULL,
            port          INTEGER NOT NULL DEFAULT 4370,
            serial_number TEXT    NOT NULL UNIQUE,
            name          TEXT,
            location      TEXT,
            last_sync     TIMESTAMP,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Departments ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS departments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Employees ────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS employees (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_code TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL,
            email         TEXT,
            phone         TEXT,
            department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
            designation   TEXT,
            join_date     DATE,
            status        TEXT    NOT NULL DEFAULT 'active',  -- active | inactive
            synced_to_server INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Biometric data (finger / face / card per device) ─────────────
        CREATE TABLE IF NOT EXISTS biometrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            device_sn   TEXT    NOT NULL REFERENCES devices(serial_number) ON DELETE CASCADE,
            type        TEXT    NOT NULL DEFAULT 'fingerprint',  -- fingerprint | face | card | pin
            template    BLOB,       -- raw template bytes (fingerprint / face)
            card_number TEXT,       -- for RFID card
            pin         TEXT,       -- numeric PIN
            finger_index INTEGER,   -- 0-9 finger position
            is_primary  INTEGER NOT NULL DEFAULT 1,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, device_sn, type, finger_index)
        );

        -- ── Shifts ───────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS shifts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL UNIQUE,
            start_time      TEXT    NOT NULL,  -- HH:MM  e.g. '09:00'
            end_time        TEXT    NOT NULL,  -- HH:MM  e.g. '18:00'
            grace_late      INTEGER NOT NULL DEFAULT 15,   -- minutes allowed late
            grace_early_out INTEGER NOT NULL DEFAULT 10,   -- minutes allowed early leave
            overtime_after  INTEGER NOT NULL DEFAULT 30,   -- minutes before overtime starts
            is_overnight    INTEGER NOT NULL DEFAULT 0,    -- 1 if shift crosses midnight
            is_flexible     INTEGER NOT NULL DEFAULT 0,    -- 1 for flexible/work-from-home
            working_days    TEXT    NOT NULL DEFAULT 'Mon,Tue,Wed,Thu,Fri',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Employee ↔ Shift assignment ───────────────────────────────────
        CREATE TABLE IF NOT EXISTS employee_shifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            shift_id    INTEGER NOT NULL REFERENCES shifts(id)    ON DELETE CASCADE,
            effective_from DATE NOT NULL,
            effective_to   DATE,   -- NULL = currently active
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, effective_from)
        );

        -- ── Raw attendance punches from device ────────────────────────────
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT    NOT NULL,  -- ZKTeco user_id (device-side)
            employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
            punch_time  TIMESTAMP NOT NULL,
            punch_type  TEXT NOT NULL DEFAULT 'auto',  -- check_in | check_out | auto
            device_ip   TEXT,
            device_sn   TEXT,
            status      TEXT NOT NULL DEFAULT 'pending',  -- pending | synced | error
            sync_time   TIMESTAMP,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Processed daily attendance (IN/OUT pairs) ────────────────────
        CREATE TABLE IF NOT EXISTS attendance_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id     INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            work_date       DATE    NOT NULL,
            check_in        TIMESTAMP,
            check_out       TIMESTAMP,
            working_minutes INTEGER,  -- actual minutes worked
            late_minutes    INTEGER  NOT NULL DEFAULT 0,
            early_out_minutes INTEGER NOT NULL DEFAULT 0,
            overtime_minutes  INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'present',
            -- present | absent | half_day | on_leave | holiday | weekend
            remarks         TEXT,
            shift_id        INTEGER REFERENCES shifts(id),
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, work_date)
        );

        -- ── Leave types ───────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS leave_types (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL UNIQUE,  -- Annual, Sick, Casual, ...
            days_allowed    INTEGER NOT NULL DEFAULT 0,  -- per year (0 = unlimited)
            is_paid         INTEGER NOT NULL DEFAULT 1,
            carry_forward   INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Leave requests ────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS leave_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id  INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            leave_type_id INTEGER NOT NULL REFERENCES leave_types(id),
            from_date    DATE    NOT NULL,
            to_date      DATE    NOT NULL,
            days         INTEGER NOT NULL,
            reason       TEXT,
            status       TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
            approved_by  TEXT,  -- name or ID of approver
            applied_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── App configuration ─────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS configuration (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Indexes ───────────────────────────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_attendance_user     ON attendance(user_id);
        CREATE INDEX IF NOT EXISTS idx_attendance_time     ON attendance(punch_time);
        CREATE INDEX IF NOT EXISTS idx_attendance_status   ON attendance(status);
        CREATE INDEX IF NOT EXISTS idx_att_log_emp_date    ON attendance_log(employee_id, work_date);
        CREATE INDEX IF NOT EXISTS idx_leave_emp           ON leave_requests(employee_id);
        CREATE INDEX IF NOT EXISTS idx_emp_dept            ON employees(department_id);
        CREATE INDEX IF NOT EXISTS idx_biometrics_emp      ON biometrics(employee_id);
        """

        with self._get_connection() as conn:
            for stmt in ddl.split(';'):
                stmt = stmt.strip()
                if stmt:
                    try:
                        conn.execute(stmt)
                    except sqlite3.Error as e:
                        logger.error(f"DDL error: {e}\nStatement: {stmt[:80]}")

            self._seed_defaults(conn)
            conn.commit()
        logger.info("Database initialised")

    def _seed_defaults(self, conn):
        """Insert default configuration, leave types, and shifts if empty."""
        # Config defaults
        defaults = {
            'site_url':       '',
            'api_key':        '',
            'sync_interval':  '300',
            'timezone':       'Asia/Dhaka',
            'date_format':    'Y-m-d',
            'time_format':    'H:i',
            'work_week_start':'Mon',
            'log_level':      'INFO',
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO configuration (key, value) VALUES (?, ?)", (k, v)
            )

        # Default leave types
        leave_types = [
            ('Annual Leave',   20, 1, 1),
            ('Sick Leave',     10, 1, 0),
            ('Casual Leave',    8, 1, 0),
            ('Unpaid Leave',    0, 0, 0),
            ('Maternity Leave',90, 1, 0),
            ('Paternity Leave', 7, 1, 0),
        ]
        for name, days, paid, carry in leave_types:
            conn.execute(
                "INSERT OR IGNORE INTO leave_types (name, days_allowed, is_paid, carry_forward) "
                "VALUES (?, ?, ?, ?)", (name, days, paid, carry)
            )

        # Default shifts
        shifts = [
            ('Morning Shift',  '08:00', '16:00', 15, 10, 30, 0, 0, 'Mon,Tue,Wed,Thu,Fri'),
            ('Day Shift',      '09:00', '17:00', 15, 10, 30, 0, 0, 'Mon,Tue,Wed,Thu,Fri'),
            ('Evening Shift',  '14:00', '22:00', 15, 10, 30, 0, 0, 'Mon,Tue,Wed,Thu,Fri'),
            ('Night Shift',    '22:00', '06:00', 15, 10, 30, 1, 0, 'Mon,Tue,Wed,Thu,Fri'),
            ('Flexible',       '08:00', '20:00',  0,  0, 30, 0, 1, 'Mon,Tue,Wed,Thu,Fri'),
            ('Half Day AM',    '08:00', '12:00', 10,  5,  0, 0, 0, 'Mon,Tue,Wed,Thu,Fri'),
        ]
        for s in shifts:
            conn.execute(
                "INSERT OR IGNORE INTO shifts "
                "(name, start_time, end_time, grace_late, grace_early_out, "
                " overtime_after, is_overnight, is_flexible, working_days) "
                "VALUES (?,?,?,?,?,?,?,?,?)", s
            )

        # Default department
        conn.execute(
            "INSERT OR IGNORE INTO departments (name) VALUES (?)", ('General',)
        )

    # ------------------------------------------------------------------ #
    # Generic helpers                                                      #
    # ------------------------------------------------------------------ #

    def execute_query(self, sql: str, params=(), commit: bool = False):
        try:
            with self._get_connection() as conn:
                cur = conn.execute(sql, params)
                if commit:
                    conn.commit()
                return cur
        except sqlite3.Error as e:
            logger.error(f"DB error: {e} | SQL: {sql[:80]}")
            return None

    def fetchall(self, sql: str, params=()) -> List[Dict]:
        try:
            with self._get_connection() as conn:
                cur = conn.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"fetchall error: {e}")
            return []

    def fetchone(self, sql: str, params=()) -> Optional[Dict]:
        try:
            with self._get_connection() as conn:
                cur = conn.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"fetchone error: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Configuration                                                        #
    # ------------------------------------------------------------------ #

    def get_config_value(self, key: str, default: Any = None) -> Any:
        row = self.fetchone("SELECT value FROM configuration WHERE key = ?", (key,))
        return row['value'] if row else default

    def set_config_value(self, key: str, value: Any) -> bool:
        cur = self.execute_query(
            "INSERT OR REPLACE INTO configuration (key, value, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, str(value)), commit=True
        )
        return cur is not None

    # ------------------------------------------------------------------ #
    # Devices                                                              #
    # ------------------------------------------------------------------ #

    def get_devices(self) -> List[Dict]:
        return self.fetchall(
            "SELECT * FROM devices WHERE is_active = 1 ORDER BY name"
        )

    def add_device(self, ip: str, port: int, serial_number: str,
                   name: str = None, location: str = None) -> bool:
        cur = self.execute_query(
            "INSERT OR REPLACE INTO devices (ip, port, serial_number, name, location) "
            "VALUES (?, ?, ?, ?, ?)",
            (ip, port, serial_number, name, location), commit=True
        )
        return cur is not None

    def delete_device(self, serial_number: str) -> bool:
        cur = self.execute_query(
            "UPDATE devices SET is_active = 0 WHERE serial_number = ?",
            (serial_number,), commit=True
        )
        return cur is not None

    # ------------------------------------------------------------------ #
    # Departments                                                          #
    # ------------------------------------------------------------------ #

    def get_departments(self) -> List[Dict]:
        return self.fetchall("SELECT * FROM departments ORDER BY name")

    def add_department(self, name: str) -> Optional[int]:
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO departments (name) VALUES (?)", (name,)
                )
                conn.commit()
                return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"add_department: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Employees                                                            #
    # ------------------------------------------------------------------ #

    def add_employee(self, employee_code: str, name: str,
                     department_id: int = None, designation: str = None,
                     email: str = None, phone: str = None,
                     join_date: str = None) -> Optional[int]:
        """Register a new employee. Returns employee id or None."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO employees
                       (employee_code, name, email, phone, department_id,
                        designation, join_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (employee_code, name, email, phone, department_id,
                     designation, join_date or date.today().isoformat())
                )
                conn.commit()
                logger.info(f"Employee registered: {name} ({employee_code})")
                return cur.lastrowid
        except sqlite3.IntegrityError:
            logger.warning(f"Employee code already exists: {employee_code}")
            return None
        except sqlite3.Error as e:
            logger.error(f"add_employee: {e}")
            return None

    def get_employees(self, active_only: bool = True) -> List[Dict]:
        sql = """
            SELECT e.*, d.name as department_name
            FROM employees e
            LEFT JOIN departments d ON e.department_id = d.id
        """
        if active_only:
            sql += " WHERE e.status = 'active'"
        sql += " ORDER BY e.name"
        return self.fetchall(sql)

    def get_employee(self, employee_id: int = None,
                     employee_code: str = None) -> Optional[Dict]:
        if employee_id:
            sql    = "SELECT e.*, d.name as department_name FROM employees e LEFT JOIN departments d ON e.department_id = d.id WHERE e.id = ?"
            params = (employee_id,)
        elif employee_code:
            sql    = "SELECT e.*, d.name as department_name FROM employees e LEFT JOIN departments d ON e.department_id = d.id WHERE e.employee_code = ?"
            params = (employee_code,)
        else:
            return None
        return self.fetchone(sql, params)

    def update_employee(self, employee_id: int, **fields) -> bool:
        allowed = {'name', 'email', 'phone', 'department_id',
                   'designation', 'status', 'join_date'}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        values     = list(updates.values()) + [employee_id]
        cur = self.execute_query(
            f"UPDATE employees SET {set_clause} WHERE id = ?",
            values, commit=True
        )
        return cur is not None

    def get_employee_by_zk_user_id(self, user_id: str) -> Optional[Dict]:
        """Map a ZKTeco user_id → employee record."""
        return self.fetchone(
            """SELECT e.* FROM employees e
               JOIN biometrics b ON b.employee_id = e.id
               WHERE b.card_number = ? OR CAST(e.id AS TEXT) = ?
               LIMIT 1""",
            (str(user_id), str(user_id))
        )

    # ------------------------------------------------------------------ #
    # Biometrics                                                           #
    # ------------------------------------------------------------------ #

    def register_biometric(self, employee_id: int, device_sn: str,
                            bio_type: str = 'fingerprint',
                            template: bytes = None,
                            card_number: str = None,
                            pin: str = None,
                            finger_index: int = 0) -> bool:
        """Store finger/face/card/PIN data for an employee on a device."""
        cur = self.execute_query(
            """INSERT OR REPLACE INTO biometrics
               (employee_id, device_sn, type, template, card_number, pin, finger_index)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (employee_id, device_sn, bio_type, template,
             card_number, pin, finger_index),
            commit=True
        )
        if cur:
            logger.info(f"Biometric ({bio_type}) registered for employee {employee_id} on {device_sn}")
        return cur is not None

    def get_employee_biometrics(self, employee_id: int) -> List[Dict]:
        return self.fetchall(
            "SELECT * FROM biometrics WHERE employee_id = ? ORDER BY type, finger_index",
            (employee_id,)
        )

    def delete_biometric(self, employee_id: int, device_sn: str,
                          bio_type: str = None) -> bool:
        if bio_type:
            cur = self.execute_query(
                "DELETE FROM biometrics WHERE employee_id=? AND device_sn=? AND type=?",
                (employee_id, device_sn, bio_type), commit=True
            )
        else:
            cur = self.execute_query(
                "DELETE FROM biometrics WHERE employee_id=? AND device_sn=?",
                (employee_id, device_sn), commit=True
            )
        return cur is not None

    # ------------------------------------------------------------------ #
    # Shifts                                                               #
    # ------------------------------------------------------------------ #

    def get_shifts(self) -> List[Dict]:
        return self.fetchall("SELECT * FROM shifts ORDER BY start_time")

    def get_shift(self, shift_id: int) -> Optional[Dict]:
        return self.fetchone("SELECT * FROM shifts WHERE id = ?", (shift_id,))

    def add_shift(self, name: str, start_time: str, end_time: str,
                  grace_late: int = 15, grace_early_out: int = 10,
                  overtime_after: int = 30, is_overnight: int = 0,
                  is_flexible: int = 0,
                  working_days: str = 'Mon,Tue,Wed,Thu,Fri') -> Optional[int]:
        """Create a new shift definition."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO shifts
                       (name, start_time, end_time, grace_late, grace_early_out,
                        overtime_after, is_overnight, is_flexible, working_days)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (name, start_time, end_time, grace_late, grace_early_out,
                     overtime_after, is_overnight, is_flexible, working_days)
                )
                conn.commit()
                logger.info(f"Shift created: {name} ({start_time}-{end_time})")
                return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"add_shift: {e}")
            return None

    def assign_shift(self, employee_id: int, shift_id: int,
                     effective_from: str = None,
                     effective_to: str = None) -> bool:
        """Assign a shift to an employee from a given date."""
        if not effective_from:
            effective_from = date.today().isoformat()
        try:
            with self._get_connection() as conn:
                # Close any open assignment
                conn.execute(
                    """UPDATE employee_shifts
                       SET effective_to = ?
                       WHERE employee_id = ? AND effective_to IS NULL""",
                    (effective_from, employee_id)
                )
                conn.execute(
                    """INSERT INTO employee_shifts
                       (employee_id, shift_id, effective_from, effective_to)
                       VALUES (?, ?, ?, ?)""",
                    (employee_id, shift_id, effective_from, effective_to)
                )
                conn.commit()
                logger.info(f"Shift {shift_id} assigned to employee {employee_id} from {effective_from}")
                return True
        except sqlite3.Error as e:
            logger.error(f"assign_shift: {e}")
            return False

    def get_employee_shift(self, employee_id: int,
                            on_date: str = None) -> Optional[Dict]:
        """Get the active shift for an employee on a given date."""
        if not on_date:
            on_date = date.today().isoformat()
        return self.fetchone(
            """SELECT s.* FROM shifts s
               JOIN employee_shifts es ON es.shift_id = s.id
               WHERE es.employee_id = ?
                 AND es.effective_from <= ?
                 AND (es.effective_to IS NULL OR es.effective_to >= ?)
               ORDER BY es.effective_from DESC
               LIMIT 1""",
            (employee_id, on_date, on_date)
        )

    # ------------------------------------------------------------------ #
    # Attendance — raw punches                                             #
    # ------------------------------------------------------------------ #

    def insert_attendance(self, user_id, punch_time: str,
                           device_ip: str, device_sn: str,
                           punch_type: str = 'auto') -> bool:
        # Try to resolve employee_id from user_id
        emp = self.fetchone(
            "SELECT id FROM employees WHERE id = ? OR employee_code = ?",
            (str(user_id), str(user_id))
        )
        emp_id = emp['id'] if emp else None

        cur = self.execute_query(
            """INSERT INTO attendance
               (user_id, employee_id, punch_time, punch_type, device_ip, device_sn)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(user_id), emp_id, punch_time, punch_type, device_ip, device_sn),
            commit=True
        )
        return cur is not None

    def get_unsynced_attendance(self, limit: int = 100) -> List[Dict]:
        return self.fetchall(
            """SELECT a.*, e.name as employee_name, e.employee_code
               FROM attendance a
               LEFT JOIN employees e ON e.id = a.employee_id
               WHERE a.status = 'pending'
               ORDER BY a.punch_time
               LIMIT ?""",
            (limit,)
        )

    def mark_attendance_synced(self, ids: List[int]) -> bool:
        if not ids:
            return True
        ph  = ','.join('?' * len(ids))
        cur = self.execute_query(
            f"UPDATE attendance SET status='synced', sync_time=CURRENT_TIMESTAMP WHERE id IN ({ph})",
            ids, commit=True
        )
        return cur is not None

    def get_attendance_by_date(self, work_date: str,
                                employee_id: int = None) -> List[Dict]:
        sql    = """
            SELECT a.*, e.name as employee_name, e.employee_code
            FROM attendance a
            LEFT JOIN employees e ON e.id = a.employee_id
            WHERE DATE(a.punch_time) = ?
        """
        params = [work_date]
        if employee_id:
            sql += " AND a.employee_id = ?"
            params.append(employee_id)
        sql += " ORDER BY a.punch_time"
        return self.fetchall(sql, params)

    # ------------------------------------------------------------------ #
    # Attendance log — processed IN/OUT                                   #
    # ------------------------------------------------------------------ #

    def upsert_attendance_log(self, employee_id: int, work_date: str,
                               check_in: str = None, check_out: str = None,
                               working_minutes: int = None,
                               late_minutes: int = 0,
                               early_out_minutes: int = 0,
                               overtime_minutes: int = 0,
                               status: str = 'present',
                               shift_id: int = None,
                               remarks: str = None) -> bool:
        cur = self.execute_query(
            """INSERT INTO attendance_log
               (employee_id, work_date, check_in, check_out, working_minutes,
                late_minutes, early_out_minutes, overtime_minutes, status,
                shift_id, remarks)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(employee_id, work_date) DO UPDATE SET
                 check_in        = excluded.check_in,
                 check_out       = excluded.check_out,
                 working_minutes = excluded.working_minutes,
                 late_minutes    = excluded.late_minutes,
                 early_out_minutes = excluded.early_out_minutes,
                 overtime_minutes = excluded.overtime_minutes,
                 status          = excluded.status,
                 shift_id        = excluded.shift_id,
                 remarks         = excluded.remarks""",
            (employee_id, work_date, check_in, check_out, working_minutes,
             late_minutes, early_out_minutes, overtime_minutes, status,
             shift_id, remarks),
            commit=True
        )
        return cur is not None

    def get_attendance_log(self, employee_id: int = None,
                            from_date: str = None,
                            to_date: str = None) -> List[Dict]:
        sql = """
            SELECT al.*, e.name as employee_name, e.employee_code,
                   s.name as shift_name
            FROM attendance_log al
            LEFT JOIN employees e ON e.id = al.employee_id
            LEFT JOIN shifts s    ON s.id = al.shift_id
            WHERE 1=1
        """
        params = []
        if employee_id:
            sql += " AND al.employee_id = ?"
            params.append(employee_id)
        if from_date:
            sql += " AND al.work_date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND al.work_date <= ?"
            params.append(to_date)
        sql += " ORDER BY al.work_date DESC, e.name"
        return self.fetchall(sql, params)

    def get_attendance_summary(self, employee_id: int,
                                year: int, month: int) -> Dict:
        """Monthly summary: present/absent/late/overtime counts."""
        from_date = f"{year}-{month:02d}-01"
        to_date   = f"{year}-{month:02d}-31"
        rows = self.get_attendance_log(employee_id, from_date, to_date)
        summary = {
            'present': 0, 'absent': 0, 'late': 0, 'half_day': 0,
            'on_leave': 0, 'total_working_minutes': 0,
            'total_overtime_minutes': 0, 'total_late_minutes': 0,
        }
        for r in rows:
            s = r.get('status', '')
            if s == 'present':        summary['present']  += 1
            elif s == 'absent':       summary['absent']   += 1
            elif s == 'half_day':     summary['half_day'] += 1
            elif s == 'on_leave':     summary['on_leave'] += 1
            if r.get('late_minutes', 0) > 0:
                summary['late'] += 1
            summary['total_working_minutes']  += r.get('working_minutes', 0) or 0
            summary['total_overtime_minutes'] += r.get('overtime_minutes', 0) or 0
            summary['total_late_minutes']     += r.get('late_minutes', 0) or 0
        return summary

    # ------------------------------------------------------------------ #
    # Leave                                                                #
    # ------------------------------------------------------------------ #

    def get_leave_types(self) -> List[Dict]:
        return self.fetchall("SELECT * FROM leave_types ORDER BY name")

    def apply_leave(self, employee_id: int, leave_type_id: int,
                    from_date: str, to_date: str,
                    reason: str = None) -> Optional[int]:
        from_d = datetime.strptime(from_date, '%Y-%m-%d').date()
        to_d   = datetime.strptime(to_date,   '%Y-%m-%d').date()
        days   = (to_d - from_d).days + 1
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO leave_requests
                       (employee_id, leave_type_id, from_date, to_date, days, reason)
                       VALUES (?,?,?,?,?,?)""",
                    (employee_id, leave_type_id, from_date, to_date, days, reason)
                )
                conn.commit()
                logger.info(f"Leave applied: employee {employee_id} {from_date}→{to_date}")
                return cur.lastrowid
        except sqlite3.Error as e:
            logger.error(f"apply_leave: {e}")
            return None

    def approve_leave(self, leave_id: int, approved_by: str = 'Admin') -> bool:
        cur = self.execute_query(
            """UPDATE leave_requests
               SET status='approved', approved_by=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (approved_by, leave_id), commit=True
        )
        return cur is not None

    def reject_leave(self, leave_id: int, approved_by: str = 'Admin') -> bool:
        cur = self.execute_query(
            """UPDATE leave_requests
               SET status='rejected', approved_by=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (approved_by, leave_id), commit=True
        )
        return cur is not None

    def get_leave_requests(self, employee_id: int = None,
                            status: str = None) -> List[Dict]:
        sql = """
            SELECT lr.*, e.name as employee_name, e.employee_code,
                   lt.name as leave_type_name, lt.is_paid
            FROM leave_requests lr
            JOIN employees   e  ON e.id  = lr.employee_id
            JOIN leave_types lt ON lt.id = lr.leave_type_id
            WHERE 1=1
        """
        params = []
        if employee_id:
            sql += " AND lr.employee_id = ?"
            params.append(employee_id)
        if status:
            sql += " AND lr.status = ?"
            params.append(status)
        sql += " ORDER BY lr.applied_at DESC"
        return self.fetchall(sql, params)

    def get_leave_balance(self, employee_id: int, year: int) -> List[Dict]:
        """How many days of each leave type an employee has used this year."""
        return self.fetchall(
            """SELECT lt.name, lt.days_allowed, lt.is_paid,
                      COALESCE(SUM(CASE WHEN lr.status='approved' THEN lr.days ELSE 0 END), 0) as used,
                      lt.days_allowed - COALESCE(SUM(CASE WHEN lr.status='approved' THEN lr.days ELSE 0 END), 0) as remaining
               FROM leave_types lt
               LEFT JOIN leave_requests lr
                      ON lr.leave_type_id = lt.id
                     AND lr.employee_id   = ?
                     AND strftime('%Y', lr.from_date) = ?
               GROUP BY lt.id
               ORDER BY lt.name""",
            (employee_id, str(year))
        )

    # ------------------------------------------------------------------ #
    # Reports                                                              #
    # ------------------------------------------------------------------ #

    def get_daily_report(self, work_date: str) -> List[Dict]:
        return self.fetchall(
            """SELECT e.employee_code, e.name, d.name as department,
                      s.name as shift,
                      al.check_in, al.check_out, al.working_minutes,
                      al.late_minutes, al.overtime_minutes, al.status
               FROM employees e
               LEFT JOIN attendance_log al ON al.employee_id = e.id AND al.work_date = ?
               LEFT JOIN departments d     ON d.id = e.department_id
               LEFT JOIN shifts s          ON s.id = al.shift_id
               WHERE e.status = 'active'
               ORDER BY d.name, e.name""",
            (work_date,)
        )

    def get_monthly_report(self, year: int, month: int) -> List[Dict]:
        from_date = f"{year}-{month:02d}-01"
        to_date   = f"{year}-{month:02d}-31"
        return self.fetchall(
            """SELECT e.employee_code, e.name, d.name as department,
                      COUNT(CASE WHEN al.status='present'  THEN 1 END) as present_days,
                      COUNT(CASE WHEN al.status='absent'   THEN 1 END) as absent_days,
                      COUNT(CASE WHEN al.status='on_leave' THEN 1 END) as leave_days,
                      COUNT(CASE WHEN al.late_minutes > 0  THEN 1 END) as late_days,
                      COALESCE(SUM(al.working_minutes),  0) as total_minutes,
                      COALESCE(SUM(al.overtime_minutes), 0) as overtime_minutes,
                      COALESCE(SUM(al.late_minutes),     0) as late_minutes
               FROM employees e
               LEFT JOIN attendance_log al ON al.employee_id = e.id
                                          AND al.work_date BETWEEN ? AND ?
               LEFT JOIN departments d ON d.id = e.department_id
               WHERE e.status = 'active'
               GROUP BY e.id
               ORDER BY d.name, e.name""",
            (from_date, to_date)
        )
