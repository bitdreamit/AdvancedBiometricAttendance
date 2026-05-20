# src/biometric/zk_device.py
"""
High-level ZKTeco device wrapper.

Wraps the low-level ZK protocol driver and exposes clean methods
used by DeviceManager and BatchAttendancePuller.

live_capture() is a generator that yields dicts — one per punch event.
get_live_attendance() fetches all stored records in one batch call.
"""
import threading
import logging
from datetime import datetime
from typing import List, Dict, Optional, Generator

try:
    from src.biometric.zk_lib.base import ZK
    from src.biometric.zk_lib.attendance import Attendance
    from src.biometric.zk_lib.exception import ZKErrorConnection, ZKNetworkError
except ImportError:
    from biometric.zk_lib.base import ZK
    from biometric.zk_lib.attendance import Attendance
    from biometric.zk_lib.exception import ZKErrorConnection, ZKNetworkError

logger = logging.getLogger(__name__)


def _att_to_dict(att: Attendance, device_ip: str, device_sn: str) -> Dict:
    """Convert an Attendance object to the standard record dict."""
    ts = att.timestamp
    punch_time = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    return {
        'user_id':    str(att.user_id).strip(),
        'punch_time': punch_time,
        'timestamp':  ts,
        'device_ip':  device_ip,
        'device_sn':  device_sn,
        'status':     getattr(att, 'status', 0),
        'punch':      getattr(att, 'punch',  0),
    }


class ZKDevice:
    def __init__(self, ip: str, port: int = 4370,
                 serial_number: str = None, timeout: int = 30):
        self.ip              = ip
        self.port            = port
        self.serial_number   = serial_number or ip
        self.timeout         = timeout
        self._zk             = None          # ZK low-level driver instance
        self.is_connected_flag = False
        self._lock           = threading.RLock()

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    def connect(self, timeout: int = None) -> bool:
        with self._lock:
            if self.is_connected():
                return True
            try:
                zk = ZK(
                    ip         = self.ip,
                    port       = self.port,
                    timeout    = timeout or self.timeout,
                    ommit_ping = True,          # we do our own reachability check
                )
                conn = zk.connect()
                if conn:
                    self._zk = zk
                    self.is_connected_flag = True
                    logger.info(f"Connected to '{self.serial_number}' at {self.ip}:{self.port}")
                    return True
            except ZKErrorConnection as e:
                logger.error(f"Connection refused by {self.ip}: {e}")
            except ZKNetworkError as e:
                logger.error(f"Network error reaching {self.ip}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error connecting to {self.ip}: {e}")
            self._cleanup()
            return False

    def disconnect(self):
        with self._lock:
            if self._zk:
                try:
                    self._zk.disconnect()
                except Exception:
                    pass
            self._cleanup()

    def _cleanup(self):
        self._zk               = None
        self.is_connected_flag = False

    def is_connected(self) -> bool:
        return self.is_connected_flag and self._zk is not None

    # ------------------------------------------------------------------ #
    # Live capture — yields one dict per punch, runs forever              #
    # ------------------------------------------------------------------ #

    def live_capture(self, event_timeout: int = 10) -> Generator[Optional[Dict], None, None]:
        """
        Stream real-time attendance events from the device.

        Yields a dict for each finger/face punch.
        Yields None as a heartbeat tick (caller checks is_running).
        Returns (StopIteration) on disconnect.

        The caller (DeviceManager._live_capture_loop) handles reconnection.
        """
        if not self.is_connected():
            logger.warning(f"live_capture called but {self.serial_number} is not connected")
            return

        try:
            for att in self._zk.live_capture(event_timeout=event_timeout):
                if att is None:
                    yield None          # heartbeat
                else:
                    yield _att_to_dict(att, self.ip, self.serial_number)
        except Exception as e:
            logger.error(f"live_capture error on '{self.serial_number}': {e}")
            self.is_connected_flag = False

    # ------------------------------------------------------------------ #
    # Batch fetch — returns all stored records at once                    #
    # ------------------------------------------------------------------ #

    def get_live_attendance(self) -> List[Dict]:
        """Fetch ALL stored attendance records from device memory (batch mode)."""
        if not self.is_connected():
            return []
        try:
            records = self._zk.get_attendance()
            return [_att_to_dict(r, self.ip, self.serial_number) for r in records]
        except Exception as e:
            logger.error(f"get_attendance error on '{self.serial_number}': {e}")
            self.is_connected_flag = False
            return []

    # ------------------------------------------------------------------ #
    # Device info and utilities                                           #
    # ------------------------------------------------------------------ #

    def get_device_info(self) -> Optional[Dict]:
        if not self.is_connected():
            return None
        try:
            device_time = self._zk.get_time()
            return {
                'serial_number': self.serial_number,
                'ip_address':    self.ip,
                'device_time':   device_time.isoformat() if device_time else 'Unknown',
                'device_name':   f'ZK Device {self.ip}',
            }
        except Exception as e:
            logger.error(f"get_device_info error on '{self.serial_number}': {e}")
            return None

    def sync_time(self) -> bool:
        if not self.is_connected():
            return False
        try:
            ok = self._zk.set_time(datetime.now())
            if ok:
                logger.info(f"Time synced on '{self.serial_number}'")
            return ok
        except Exception as e:
            logger.error(f"sync_time error on '{self.serial_number}': {e}")
            return False

    def clear_attendance_log(self) -> bool:
        if not self.is_connected():
            return False
        try:
            return self._zk.clear_attendance()
        except Exception as e:
            logger.error(f"clear_attendance error on '{self.serial_number}': {e}")
            return False

    def get_users(self) -> List[Dict]:
        if not self.is_connected():
            return []
        try:
            return [
                {'uid': u.uid, 'name': u.name,
                 'privilege': u.privilege, 'user_id': u.user_id}
                for u in self._zk.get_users()
            ]
        except Exception as e:
            logger.error(f"get_users error on '{self.serial_number}': {e}")
            return []
