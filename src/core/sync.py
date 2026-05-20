# src/core/sync.py
"""
Bidirectional sync between this offline agent and the online server.

DIRECTION 1 — Online → Offline  (pull)
────────────────────────────────────────
  The online server is the master for employee data.
  This agent GETs the employee list and upserts into local employees table.
  After receiving employees, it pushes new/updated ones to ZK devices.

  Online endpoint: GET /api/biometric/employees
  Response:
    {
      "data": [
        {
          "id":            "uuid-or-int",    ← remote_id
          "employee_code": "EMP001",
          "name":          "Alice Rahman",
          "zk_user_id":    "1",             ← integer id on the device
          "card_number":   "0012345678",     ← null if not using card
          "department":    "Engineering",
          "designation":   "Developer",
          "status":        "active",
          "tenant_id":     "tenant-abc"      ← null if single-tenant
        }
      ],
      "deleted_ids": ["uuid-1", "uuid-2"]   ← remote_ids removed on server
    }

DIRECTION 2 — Offline → Online  (push)
────────────────────────────────────────
  This agent is the master for raw punch data.
  It POSTs pending attendance records to the online server in batches.
  On success it marks them synced. On 409 (duplicate) marks duplicate.
  On 4xx/5xx marks error and retries later.

  Online endpoint: POST /api/biometric/attendance
  Payload:
    {
      "punches": [
        {
          "id":                  1,              ← local id (for tracking)
          "tenant_id":           "tenant-abc",   ← null if single-tenant
          "zk_user_id":          "42",
          "remote_employee_id":  "uuid-or-int",
          "employee_code":       "EMP001",
          "punched_at":          "2026-05-20T10:31:15",
          "device_sn":           "ABC123456",
          "device_ip":           "192.168.1.201",
          "punch_type":          null,           ← server decides check_in/out
          "verify_type":         "fingerprint"   ← fingerprint|face|card|pin
        }
      ]
    }
  Response:
    {
      "synced":     [1, 2, 3],              ← local ids confirmed saved
      "duplicates": [4],                    ← local ids already on server
      "errors":     [{"id": 5, "error": "..."}]
    }

DEVICE ENROLLMENT — Online → Device  (push to hardware)
────────────────────────────────────────────────────────
  After pulling employees, this agent checks which ones have
  sync_status='pending' (not yet on device) and enrolls them
  on the ZK device via the ZK protocol.
  NOTE: fingerprint/face templates must already be enrolled on
  the device physically. This just ensures the user record
  (user_id, name, card_number) exists on the device.
"""
import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

try:
    from src.core.database import DatabaseManager
    from src.biometric.zk_device import ZKDevice
except ImportError:
    from core.database import DatabaseManager
    from biometric.zk_device import ZKDevice

logger = logging.getLogger(__name__)

# How long to wait before retrying a failed record (seconds)
RETRY_BACKOFF = [60, 300, 900, 3600, 14400]  # 1m 5m 15m 1h 4h


class SyncEngine:
    """
    Handles all bidirectional sync between this offline agent
    and the online server.
    """

    def __init__(self, db: DatabaseManager,
                 devices: Dict[str, ZKDevice] = None,
                 config: Dict = None):
        self.db      = db
        self.devices = devices or {}
        self.config  = config or {}
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

        # Load from DB config if not passed
        self.server_url    = (config.get('server', {}).get('url', '') or
                              db.get_config('server_url', ''))
        self.api_key       = (config.get('server', {}).get('api_key', '') or
                              db.get_config('api_key', ''))
        self.tenant_id     = (config.get('tenant_id') or
                              db.get_config('tenant_id') or None)
        self.batch_size    = int(db.get_config('batch_size', 100))
        self.retry_limit   = int(db.get_config('retry_limit', 5))
        self.verify_ssl    = db.get_config('verify_ssl', 'true').lower() == 'true'

        if self.tenant_id == '':
            self.tenant_id = None

    # ── Public API ─────────────────────────────────────────────────── #

    def start(self, interval: int = 300):
        """Start background sync thread."""
        if self.is_running:
            return
        self.is_running = True
        self._interval  = interval
        self._thread    = threading.Thread(
            target=self._sync_loop, daemon=True, name="SyncEngine"
        )
        self._thread.start()
        logger.info(f"SyncEngine started — interval={interval}s "
                    f"tenant={self.tenant_id or 'none'}")

    def stop(self):
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("SyncEngine stopped")

    def sync_now(self) -> Dict:
        """Run a full sync cycle immediately (blocking). Returns summary."""
        return self._run_cycle()

    def update_devices(self, devices: Dict[str, ZKDevice]):
        """Update device map after new connections."""
        self.devices = devices

    # ── Internal ───────────────────────────────────────────────────── #

    def _sync_loop(self):
        self._run_cycle()
        while self.is_running:
            for _ in range(self._interval):
                if not self.is_running:
                    return
                time.sleep(1)
            if self.is_running:
                self._run_cycle()

    def _run_cycle(self) -> Dict:
        summary = {
            'employees_pulled':   0,
            'employees_to_device':0,
            'punches_pushed':     0,
            'duplicates':         0,
            'errors':             0,
        }

        if not self._server_configured():
            logger.debug("Server not configured — skipping sync cycle")
            return summary

        # Direction 1: pull employees from server → local DB → ZK device
        pulled, to_device = self._pull_employees()
        summary['employees_pulled']    = pulled
        summary['employees_to_device'] = to_device

        # Direction 2: push pending punches → server
        pushed, dupes, errors = self._push_attendance()
        summary['punches_pushed'] = pushed
        summary['duplicates']     = dupes
        summary['errors']         = errors

        # Also retry previously errored records
        self._retry_failed()

        if any(v for v in summary.values()):
            logger.info(
                f"Sync cycle: employees_pulled={pulled} "
                f"to_device={to_device} "
                f"punches_pushed={pushed} dupes={dupes} errors={errors}"
            )
        return summary

    def _server_configured(self) -> bool:
        if not self.server_url or 'example.com' in self.server_url:
            return False
        if not self.api_key or self.api_key in ('', 'your_api_key_here'):
            return False
        return True

    # ── Direction 1: Online → Offline (employee pull) ──────────────── #

    def _pull_employees(self) -> Tuple[int, int]:
        """
        GET employees from online server.
        Upserts into local employees table.
        Pushes new/updated employees to ZK devices.
        Returns (pulled_count, pushed_to_device_count).
        """
        url = self._url('employees')
        try:
            resp = self._get(url)
            if not resp:
                return 0, 0

            data     = resp.json()
            employees = data.get('data', [])
            deleted   = data.get('deleted_ids', [])
            pulled    = 0

            for emp in employees:
                local_id = self.db.upsert_employee(
                    employee_code = emp.get('employee_code', ''),
                    name          = emp.get('name', ''),
                    remote_id     = str(emp.get('id', '')),
                    zk_user_id    = emp.get('zk_user_id'),
                    card_number   = emp.get('card_number'),
                    department    = emp.get('department'),
                    designation   = emp.get('designation'),
                    status        = emp.get('status', 'active'),
                    tenant_id     = emp.get('tenant_id') or self.tenant_id,
                )
                if local_id:
                    pulled += 1

            for remote_id in deleted:
                self.db.mark_employee_deleted(str(remote_id), self.tenant_id)

            if pulled:
                logger.info(f"Pulled {pulled} employees from server "
                            f"({len(deleted)} deleted)")

            # Now push pending employees to ZK devices
            to_device = self._push_employees_to_devices()
            return pulled, to_device

        except requests.RequestException as e:
            logger.error(f"Employee pull failed: {e}")
            return 0, 0
        except Exception as e:
            logger.error(f"Employee pull unexpected error: {e}", exc_info=True)
            return 0, 0

    def _push_employees_to_devices(self) -> int:
        """
        Push pending employee records to connected ZK devices.
        Only pushes user record (id, name, card) — not biometric templates.
        Templates must be enrolled physically on the device.
        Returns count pushed.
        """
        if not self.devices:
            return 0

        pending = self.db.get_employees_pending_device_push(self.tenant_id)
        if not pending:
            return 0

        pushed = 0
        for emp in pending:
            zk_uid = emp.get('zk_user_id')
            if not zk_uid:
                logger.warning(f"Employee {emp['employee_code']} has no zk_user_id — "
                               f"cannot push to device")
                continue

            success_on_any = False
            for serial, device in self.devices.items():
                if not device.is_connected():
                    continue
                try:
                    # ZK user push: set user record on device
                    ok = self._push_user_to_device(device, emp)
                    if ok:
                        success_on_any = True
                        logger.info(f"Employee {emp['employee_code']} pushed to device {serial}")
                except Exception as e:
                    logger.error(f"Error pushing {emp['employee_code']} to {serial}: {e}")

            if success_on_any:
                self.db.mark_employee_pushed(emp['id'])
                pushed += 1

        if pushed:
            logger.info(f"Pushed {pushed} new employees to ZK devices")
        return pushed

    def _push_user_to_device(self, device: ZKDevice, emp: Dict) -> bool:
        """
        Set a user record on the ZK device.
        Uses the ZK set_user command if available.
        Silently skips if device does not support it.
        """
        try:
            if not hasattr(device, '_zk') or not device._zk:
                return False
            zk = device._zk
            # CMD_USER_WRQ — write user to device
            from struct import pack
            uid       = int(emp['zk_user_id'])
            name_b    = emp['name'].encode('UTF-8', errors='ignore')[:24].ljust(24, b'\x00')
            card_b    = (emp.get('card_number') or '').encode('ascii')[:8].ljust(8, b'\x00')
            privilege = 0  # normal user
            pwd_b     = b'\x00' * 5
            data = pack('<HB', uid, privilege) + pwd_b + name_b + b'\x00\x00\x00\x00\x00'
            from src.biometric.zk_lib.const import CMD_USER_WRQ
            resp = zk._send_command(CMD_USER_WRQ, data)
            return resp.get('status', False)
        except Exception as e:
            logger.debug(f"push_user_to_device: {e}")
            return False

    # ── Direction 2: Offline → Online (attendance push) ────────────── #

    def _push_attendance(self) -> Tuple[int, int, int]:
        """
        POST pending attendance records to the online server in batches.
        Returns (synced_count, duplicate_count, error_count).
        """
        records = self.db.get_pending_attendance(self.batch_size, self.tenant_id)
        if not records:
            return 0, 0, 0

        payload = {
            'punches': [
                {
                    'id':                 r['id'],
                    'tenant_id':          r.get('tenant_id') or self.tenant_id,
                    'zk_user_id':         r['zk_user_id'],
                    'remote_employee_id': r.get('remote_employee_id'),
                    'employee_code':      r.get('employee_code'),
                    'punched_at':         r['punched_at'],
                    'device_sn':          r['device_sn'],
                    'device_ip':          r.get('device_ip'),
                    'punch_type':         r.get('punch_type'),
                    'verify_type':        r.get('verify_type'),
                }
                for r in records
            ]
        }

        try:
            resp = self._post(self._url('attendance'), payload)
            if not resp:
                self.db.mark_attendance_error([r['id'] for r in records],
                                              "No response from server")
                return 0, 0, len(records)

            result     = resp.json()
            synced_ids = result.get('synced',     [])
            dupe_ids   = result.get('duplicates', [])
            error_list = result.get('errors',     [])

            # Build remote_id map if server returns them
            remote_map = {}
            if isinstance(synced_ids, list) and synced_ids:
                if isinstance(synced_ids[0], dict):
                    remote_map = {item['id']: item.get('remote_id') for item in synced_ids}
                    synced_ids = list(remote_map.keys())

            if synced_ids:
                self.db.mark_attendance_synced(synced_ids, remote_map)
            if dupe_ids:
                self.db.mark_attendance_duplicate(dupe_ids)
            for err in error_list:
                self.db.mark_attendance_error([err['id']], err.get('error', 'server error'))

            logger.info(f"Attendance push: {len(synced_ids)} synced, "
                        f"{len(dupe_ids)} dupes, {len(error_list)} errors")
            return len(synced_ids), len(dupe_ids), len(error_list)

        except requests.RequestException as e:
            logger.error(f"Attendance push failed: {e}")
            self.db.mark_attendance_error([r['id'] for r in records], str(e))
            return 0, 0, len(records)
        except Exception as e:
            logger.error(f"Attendance push unexpected error: {e}", exc_info=True)
            return 0, 0, 0

    def _retry_failed(self):
        """Retry records that errored and still have retries remaining."""
        failed = self.db.get_failed_attendance(self.retry_limit, self.tenant_id)
        if not failed:
            return
        # Reset status to pending so next cycle picks them up
        ids = [r['id'] for r in failed]
        ph  = ','.join('?' * len(ids))
        self.db.execute(
            f"UPDATE attendance SET sync_status='pending' WHERE id IN ({ph})", ids
        )
        logger.debug(f"Re-queued {len(ids)} failed attendance records for retry")

    # ── HTTP helpers ───────────────────────────────────────────────── #

    def _url(self, endpoint: str) -> str:
        base = self.server_url.rstrip('/')
        return f"{base}/api/biometric/{endpoint}"

    def _headers(self) -> Dict:
        h = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.api_key:
            h['Authorization'] = f'Bearer {self.api_key}'
        if self.tenant_id:
            h['X-Tenant-ID'] = self.tenant_id
        return h

    def _get(self, url: str) -> Optional[requests.Response]:
        try:
            resp = requests.get(
                url, headers=self._headers(),
                timeout=30, verify=self.verify_ssl
            )
            if resp.status_code == 200:
                return resp
            logger.warning(f"GET {url} → HTTP {resp.status_code}")
            return None
        except requests.Timeout:
            logger.error(f"GET {url} timed out")
            return None
        except requests.ConnectionError:
            logger.error(f"Cannot reach server: {url}")
            return None

    def _post(self, url: str, data: Dict) -> Optional[requests.Response]:
        try:
            resp = requests.post(
                url, json=data, headers=self._headers(),
                timeout=30, verify=self.verify_ssl
            )
            if resp.status_code in (200, 201, 207):
                return resp
            if resp.status_code == 409:
                # All duplicates
                return resp
            logger.warning(f"POST {url} → HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        except requests.Timeout:
            logger.error(f"POST {url} timed out")
            return None
        except requests.ConnectionError:
            logger.error(f"Cannot reach server: {url}")
            return None
