# src/core/batch_attendance.py
"""
Batch attendance puller.

For each connected ZKTeco device, fetches ALL stored attendance
records in one pass, deduplicates against the local database,
inserts new ones, then optionally clears the device log.

This is the fallback/complement to live_capture for devices that
do not support real-time event streaming (older firmware).
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

try:
    from src.biometric.zk_device import ZKDevice
    from src.core.database import DatabaseManager
except ImportError:
    from biometric.zk_device import ZKDevice
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class BatchAttendancePuller:
    """
    Pulls stored attendance logs from one or more ZKTeco devices
    in a scheduled background thread.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        devices: Dict[str, ZKDevice],
        interval_seconds: int = 300,
        clear_after_pull: bool = False,
        since_hours: int = 0,
    ):
        """
        Args:
            db_manager:        Database manager instance.
            devices:           Dict of {serial_number: ZKDevice}.
            interval_seconds:  How often to pull from devices (seconds).
            clear_after_pull:  If True, clears device log after pulling.
                               USE WITH CAUTION — data is only safe after DB write.
            since_hours:       Only import records from the last N hours (0 = all).
        """
        self.db             = db_manager
        self.devices        = devices
        self.interval       = interval_seconds
        self.clear_after    = clear_after_pull
        self.since_hours    = since_hours
        self.is_running     = False
        self._thread: Optional[threading.Thread] = None
        self._stats: Dict   = {"total_pulled": 0, "total_new": 0, "last_run": None, "errors": 0}
        self._lock          = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start the background batch pull thread."""
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="BatchAttendancePuller"
        )
        self._thread.start()
        logger.info(f"BatchAttendancePuller started — interval={self.interval}s "
                    f"clear_after={self.clear_after} since_hours={self.since_hours}")

    def stop(self):
        """Stop the background thread cleanly."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("BatchAttendancePuller stopped.")

    def pull_now(self) -> Dict:
        """
        Run an immediate pull from all devices (blocking).
        Returns a summary dict.
        """
        return self._pull_all_devices()

    def get_stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self):
        """Background loop — pull every interval_seconds."""
        # Pull immediately on start
        self._pull_all_devices()

        while self.is_running:
            # Sleep in 1-second chunks so stop() responds quickly
            for _ in range(self.interval):
                if not self.is_running:
                    return
                time.sleep(1)
            if self.is_running:
                self._pull_all_devices()

    def _pull_all_devices(self) -> Dict:
        """Pull attendance from every device. Returns summary."""
        summary = {
            "started_at": datetime.now().isoformat(),
            "devices":    {},
            "total_pulled": 0,
            "total_new":    0,
            "errors":       0,
        }

        for serial, device in list(self.devices.items()):
            result = self._pull_device(device)
            summary["devices"][serial] = result
            summary["total_pulled"] += result.get("pulled",   0)
            summary["total_new"]    += result.get("inserted", 0)
            if result.get("error"):
                summary["errors"] += 1

        summary["finished_at"] = datetime.now().isoformat()

        with self._lock:
            self._stats["total_pulled"] += summary["total_pulled"]
            self._stats["total_new"]    += summary["total_new"]
            self._stats["errors"]       += summary["errors"]
            self._stats["last_run"]      = summary["finished_at"]

        logger.info(
            f"Batch pull complete — devices={len(self.devices)} "
            f"pulled={summary['total_pulled']} new={summary['total_new']} "
            f"errors={summary['errors']}"
        )
        return summary

    def _pull_device(self, device: ZKDevice) -> Dict:
        """Pull attendance records from a single device."""
        result = {
            "serial":   device.serial_number,
            "ip":       device.ip,
            "pulled":   0,
            "inserted": 0,
            "skipped":  0,
            "error":    None,
        }

        try:
            # Reconnect if needed
            if not device.is_connected():
                logger.info(f"Reconnecting to {device.serial_number} ({device.ip}) …")
                if not device.connect():
                    result["error"] = "Could not connect"
                    logger.warning(f"Batch pull skipped {device.serial_number} — not reachable")
                    return result

            records: List[Dict] = device.get_live_attendance()
            result["pulled"] = len(records)

            if not records:
                logger.debug(f"No attendance records on {device.serial_number}")
                return result

            # Determine cutoff time
            cutoff = None
            if self.since_hours > 0:
                cutoff = datetime.now() - timedelta(hours=self.since_hours)

            inserted = 0
            skipped  = 0

            for rec in records:
                try:
                    punch_dt = rec.get("timestamp")
                    if isinstance(punch_dt, str):
                        punch_dt = datetime.fromisoformat(punch_dt)

                    # Apply time filter
                    if cutoff and punch_dt and punch_dt < cutoff:
                        skipped += 1
                        continue

                    punch_str = punch_dt.isoformat() if punch_dt else datetime.now().isoformat()
                    user_id   = rec.get("user_id", 0)

                    # Skip duplicates already in DB
                    if self._is_duplicate(user_id, punch_str, device.serial_number):
                        skipped += 1
                        continue

                    ok = self.db.insert_attendance(
                        user_id   = user_id,
                        punch_time= punch_str,
                        device_ip = device.ip,
                        device_sn = device.serial_number,
                    )
                    if ok:
                        inserted += 1
                    else:
                        skipped += 1

                except Exception as e:
                    logger.debug(f"Error processing record from {device.serial_number}: {e}")
                    skipped += 1

            result["inserted"] = inserted
            result["skipped"]  = skipped

            logger.info(
                f"  {device.serial_number}: pulled={len(records)} "
                f"new={inserted} skipped={skipped}"
            )

            # Clear device log only after successful DB write
            if self.clear_after and inserted > 0:
                try:
                    if device.clear_attendance_log():
                        logger.info(f"  {device.serial_number}: device log cleared")
                    else:
                        logger.warning(f"  {device.serial_number}: could not clear device log")
                except Exception as e:
                    logger.error(f"  {device.serial_number}: error clearing log: {e}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Batch pull error on {device.serial_number}: {e}", exc_info=True)

        return result

    def _is_duplicate(self, user_id, punch_time: str, device_sn: str) -> bool:
        """Check if this exact punch already exists in the database."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db.db_path)
            cur = conn.cursor()
            # Allow 60-second window for duplicate detection (clock drift)
            cur.execute("""
                SELECT 1 FROM attendance
                WHERE user_id = ?
                  AND device_sn = ?
                  AND ABS(strftime('%s', punch_time) - strftime('%s', ?)) < 60
                LIMIT 1
            """, (user_id, device_sn, punch_time))
            found = cur.fetchone() is not None
            conn.close()
            return found
        except Exception as e:
            logger.debug(f"Duplicate check error: {e}")
            return False
