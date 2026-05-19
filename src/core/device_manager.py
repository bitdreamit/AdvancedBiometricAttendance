# src/core/device_manager.py
import threading
import time
import logging
from typing import Dict, List, Optional
from queue import Queue, Empty

try:
    from src.biometric.zk_device import ZKDevice
    from src.core.database import DatabaseManager
except ImportError:
    from biometric.zk_device import ZKDevice
    from core.database import DatabaseManager

logger = logging.getLogger(__name__)


class DeviceManager:
    def __init__(self, db_manager: DatabaseManager, config: Dict = None):
        self.db = db_manager
        self.config = config or {}
        self.devices: Dict[str, ZKDevice] = {}
        self.attendance_queue = Queue(maxsize=10000)
        self.is_running = False
        self.live_capture_threads: Dict[str, threading.Thread] = {}
        self._reconnect_interval = 30  # seconds before retrying a failed device

    def initialize_devices(self, devices_config=None):
        """Initialize and connect to all configured devices"""
        if devices_config is None:
            devices_config = self.config.get('devices', [])

        if not devices_config:
            logger.warning("No devices configured. Add devices to config/default_config.json")
            return

        for device_info in devices_config:
            if not device_info.get('enabled', True):
                logger.info(f"Skipping disabled device {device_info.get('serial_number', device_info.get('ip'))}")
                continue

            serial = device_info.get('serial_number') or device_info['ip']
            try:
                device = ZKDevice(
                    ip=device_info['ip'],
                    port=device_info.get('port', 4370),
                    serial_number=serial,
                    timeout=device_info.get('timeout', 30)
                )

                if device.connect():
                    self.devices[serial] = device
                    logger.info(f"Connected to device '{serial}' at {device_info['ip']}")

                    if device_info.get('sync_time', True):
                        if device.sync_time():
                            logger.info(f"Time synced on device '{serial}'")
                        else:
                            logger.warning(f"Time sync failed on device '{serial}'")
                else:
                    logger.error(f"Failed to connect to device '{serial}' at {device_info['ip']}")

            except Exception as e:
                logger.error(f"Error initialising device '{serial}': {e}", exc_info=True)

    def start_live_capture(self):
        """Start live capture threads for all connected devices"""
        if self.is_running:
            return
        self.is_running = True

        for serial, device in self.devices.items():
            self._start_capture_thread(serial, device)

        logger.info(f"Started live capture on {len(self.devices)} device(s)")

    def _start_capture_thread(self, serial: str, device: ZKDevice):
        """Start a single capture thread"""
        thread = threading.Thread(
            target=self._live_capture_loop,
            args=(device,),
            daemon=True,
            name=f"LiveCapture-{serial}"
        )
        self.live_capture_threads[serial] = thread
        thread.start()

    def stop_live_capture(self):
        """Signal all capture threads to stop and wait for them"""
        self.is_running = False
        for serial, thread in self.live_capture_threads.items():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning(f"Capture thread for '{serial}' did not stop cleanly")
        self.live_capture_threads.clear()
        logger.info("Stopped all live capture threads")

    def _live_capture_loop(self, device: ZKDevice):
        """Continuously capture live attendance events from a single device"""
        while self.is_running:
            try:
                if not device.is_connected():
                    logger.info(f"Reconnecting to device '{device.serial_number}'...")
                    if not device.connect():
                        logger.warning(f"Reconnect failed for '{device.serial_number}', retrying in {self._reconnect_interval}s")
                        time.sleep(self._reconnect_interval)
                        continue

                for attendance in device.live_capture():
                    if not self.is_running:
                        break
                    if attendance:
                        record = {
                            'user_id': attendance['user_id'],
                            'punch_time': attendance['timestamp'].isoformat()
                                         if hasattr(attendance['timestamp'], 'isoformat')
                                         else str(attendance['timestamp']),
                            'device_ip': device.ip,
                            'device_sn': device.serial_number,
                            'status': attendance.get('status', 0),
                            'punch': attendance.get('punch', 0)
                        }
                        try:
                            self.attendance_queue.put_nowait(record)
                        except Exception:
                            logger.warning("Attendance queue full — dropping record")

            except Exception as e:
                logger.error(f"Error in capture loop for '{device.serial_number}': {e}")
                device.is_connected_flag = False
                time.sleep(self._reconnect_interval)

    def process_attendance_queue(self):
        """Drain the queue and write records to the database"""
        processed = []
        while True:
            try:
                record = self.attendance_queue.get_nowait()
            except Empty:
                break
            try:
                success = self.db.insert_attendance(
                    user_id=record['user_id'],
                    punch_time=record['punch_time'],
                    device_ip=record['device_ip'],
                    device_sn=record['device_sn']
                )
                if success:
                    processed.append(record)
                    logger.debug(f"Recorded attendance for user {record['user_id']}")
            except Exception as e:
                logger.error(f"Error writing attendance record to DB: {e}")
            finally:
                self.attendance_queue.task_done()
        return processed

    def get_device_status(self, serial: str) -> Optional[Dict]:
        device = self.devices.get(serial)
        if not device:
            return None
        try:
            info = device.get_device_info() if device.is_connected() else None
            return {
                'connected': device.is_connected(),
                'serial_number': serial,
                'ip': device.ip,
                'info': info
            }
        except Exception as e:
            logger.error(f"Error getting status for '{serial}': {e}")
            return None

    def get_all_devices_status(self) -> List[Dict]:
        return [s for s in (self.get_device_status(sn) for sn in self.devices) if s]

    def disconnect_all(self):
        """Disconnect all devices cleanly"""
        self.stop_live_capture()
        for serial, device in self.devices.items():
            try:
                device.disconnect()
                logger.info(f"Disconnected device '{serial}'")
            except Exception as e:
                logger.error(f"Error disconnecting '{serial}': {e}")
        self.devices.clear()
        logger.info("All devices disconnected")
