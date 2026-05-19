# src/biometric/zk_device.py
import threading
import logging
from datetime import datetime
from typing import List, Dict, Optional, Generator

logger = logging.getLogger(__name__)

# Fix: use relative imports (this file lives inside the src package)
try:
    from src.biometric.zk_lib.base import ZK
    from src.biometric.zk_lib.attendance import Attendance
except ImportError:
    from biometric.zk_lib.base import ZK
    from biometric.zk_lib.attendance import Attendance


class ZKDevice:
    def __init__(self, ip: str, port: int = 4370, serial_number: str = None, timeout: int = 30):
        self.ip = ip
        self.port = port
        self.serial_number = serial_number
        self.timeout = timeout
        self.zk_client = None
        self.is_connected_flag = False
        self.lock = threading.RLock()

    def connect(self, timeout: int = None) -> bool:
        """Connect to the device using the ZK library"""
        if timeout is None:
            timeout = self.timeout

        with self.lock:
            try:
                if self.is_connected():
                    return True

                self.zk_client = ZK(
                    ip=self.ip,
                    port=self.port,
                    timeout=timeout,
                    ommit_ping=True
                )

                conn = self.zk_client.connect()
                if conn:
                    self.is_connected_flag = True
                    logger.info(f"Connected to device {self.serial_number or self.ip}")
                    return True
                else:
                    logger.error(f"ZK.connect() returned falsy for {self.ip}:{self.port}")

            except Exception as e:
                logger.error(f"Connection failed to {self.ip}:{self.port}: {e}")
                self.disconnect()

            return False

    def disconnect(self):
        """Disconnect from the device"""
        with self.lock:
            if self.zk_client:
                try:
                    self.zk_client.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting: {e}")
                finally:
                    self.zk_client = None
            self.is_connected_flag = False

    def is_connected(self) -> bool:
        """Check if connected to the device"""
        return self.is_connected_flag and self.zk_client is not None

    def get_live_attendance(self) -> List[Dict]:
        """Get historical attendance data from device"""
        if not self.is_connected():
            return []

        try:
            records = self.zk_client.get_attendance()
            return [
                {
                    'user_id': record.user_id,
                    'timestamp': record.timestamp,
                    'status': record.status,
                    'punch': record.punch
                }
                for record in (records or [])
            ]
        except Exception as e:
            logger.error(f"Error getting attendance from device {self.serial_number}: {e}")
            return []

    def live_capture(self) -> Generator[Dict, None, None]:
        """Live capture of attendance events using ZK library"""
        if not self.is_connected():
            logger.warning(f"live_capture called but device {self.serial_number} is not connected")
            return

        try:
            for attendance in self.zk_client.live_capture():
                if attendance is not None:
                    yield {
                        'user_id': attendance.user_id,
                        'timestamp': attendance.timestamp,
                        'status': attendance.status,
                        'punch': attendance.punch
                    }
        except Exception as e:
            logger.error(f"Error in live capture for device {self.serial_number}: {e}")

    def get_device_info(self) -> Optional[Dict]:
        """Get device information"""
        if not self.is_connected():
            return None

        try:
            device_time = self.zk_client.get_time()
            return {
                'serial_number': self.serial_number or 'Unknown',
                'ip_address': self.ip,
                'device_time': device_time.isoformat() if device_time else 'Unknown',
                'platform': 'ZK Device',
                'device_name': f'ZK Device {self.ip}'
            }
        except Exception as e:
            logger.error(f"Error getting device info: {e}")
            return None

    def sync_time(self) -> bool:
        """Synchronize device time with system time"""
        if not self.is_connected():
            return False

        try:
            result = self.zk_client.set_time(datetime.now())
            return bool(result)
        except Exception as e:
            logger.error(f"Error syncing time with device {self.serial_number}: {e}")
            return False

    def clear_attendance_log(self) -> bool:
        """Clear attendance log on device"""
        if not self.is_connected():
            return False

        try:
            result = self.zk_client.clear_attendance()
            return bool(result)
        except Exception as e:
            logger.error(f"Error clearing attendance log on device {self.serial_number}: {e}")
            return False

    def get_users(self) -> List[Dict]:
        """Get users from device"""
        if not self.is_connected():
            return []

        try:
            users = self.zk_client.get_users() or []
            return [
                {
                    'uid': user.uid,
                    'name': user.name,
                    'privilege': user.privilege,
                    'user_id': user.user_id
                }
                for user in users
            ]
        except Exception as e:
            logger.error(f"Error getting users from device {self.serial_number}: {e}")
            return []
