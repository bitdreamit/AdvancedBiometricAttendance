# src/core/attendance_service.py
"""
AttendanceService — thin wrapper that wires DeviceManager → SyncEngine.

Responsibilities:
  1. Drain the device attendance queue → insert into local DB
  2. Delegate all server sync to SyncEngine
"""
import threading
import time
import logging
from typing import Dict, Optional

try:
    from src.core.database import DatabaseManager
    from src.core.device_manager import DeviceManager
    from src.core.sync import SyncEngine
except ImportError:
    from core.database import DatabaseManager
    from core.device_manager import DeviceManager
    from core.sync import SyncEngine

logger = logging.getLogger(__name__)


class AttendanceService:

    def __init__(self, db: DatabaseManager,
                 device_manager: DeviceManager,
                 config: Dict = None):
        self.db             = db
        self.device_manager = device_manager
        self.config         = config or {}
        self.is_running     = False
        self._thread: Optional[threading.Thread] = None
        self.sync_engine    = SyncEngine(
            db      = db,
            devices = device_manager.devices if device_manager else {},
            config  = config,
        )

    def start(self, sync_config: Dict = None):
        if self.is_running:
            return
        cfg = sync_config or self.config.get('sync', {})
        interval = int(cfg.get('interval_seconds', 300))

        self.is_running = True

        # Thread: drain device queue → DB every 5 seconds
        self._thread = threading.Thread(
            target=self._drain_loop, daemon=True, name="AttendanceService"
        )
        self._thread.start()

        # SyncEngine handles server push/pull on its own interval
        self.sync_engine.start(interval=interval)
        logger.info("AttendanceService started")

    def stop(self):
        self.is_running = False
        self.sync_engine.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("AttendanceService stopped")

    def _drain_loop(self):
        """Drain attendance_queue from DeviceManager into SQLite every 5s."""
        while self.is_running:
            try:
                self._drain_queue()
            except Exception as e:
                logger.error(f"Drain loop error: {e}")
            for _ in range(5):
                if not self.is_running:
                    return
                time.sleep(1)

    def _drain_queue(self):
        """Move all items from in-memory queue to the database."""
        processed = 0
        while True:
            try:
                from queue import Empty
                record = self.device_manager.attendance_queue.get_nowait()
            except Exception:
                break
            try:
                ok = self.db.insert_attendance(
                    zk_user_id  = record['user_id'],
                    punched_at  = record['punch_time'],
                    device_sn   = record['device_sn'],
                    device_ip   = record.get('device_ip'),
                    verify_type = record.get('verify_type'),
                    tenant_id   = self.db.get_config('tenant_id') or None,
                )
                if ok:
                    processed += 1
                    logger.info(
                        f"Recorded: user={record['user_id']} "
                        f"at={record['punch_time']} device={record['device_sn']}"
                    )
            except Exception as e:
                logger.error(f"Error inserting attendance: {e}")
            finally:
                self.device_manager.attendance_queue.task_done()

        # Keep SyncEngine device map current
        if self.device_manager.devices != self.sync_engine.devices:
            self.sync_engine.update_devices(self.device_manager.devices)

    # Kept for backward compat / direct call from tests
    def sync_attendance(self):
        self.sync_engine.sync_now()

    def get_sync_status(self) -> Dict:
        stats = self.db.get_attendance_stats()
        return {
            'pending':    stats.get('pending',   0),
            'synced':     stats.get('synced',    0),
            'error':      stats.get('error',     0),
            'duplicate':  stats.get('duplicate', 0),
            'is_running': self.is_running,
        }
