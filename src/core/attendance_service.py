# src/core/attendance_service.py
import threading
import time
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime

try:
    from src.core.database import DatabaseManager
    from src.core.device_manager import DeviceManager
except ImportError:
    from core.database import DatabaseManager
    from core.device_manager import DeviceManager

logger = logging.getLogger(__name__)


class AttendanceService:
    def __init__(self, db_manager: DatabaseManager, device_manager: DeviceManager, config: Dict = None):
        self.db = db_manager
        self.device_manager = device_manager
        self.config = config or {}
        self.is_running = False
        self.sync_thread = None
        self.sync_interval = int(self.config.get('sync', {}).get('interval_seconds', 300))

    def start(self, sync_config: Dict = None):
        """Start the attendance sync service"""
        if sync_config is None:
            sync_config = self.config.get('sync', {})

        if self.is_running:
            return

        self.is_running = True
        self.sync_interval = int(sync_config.get('interval_seconds', 300))
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True, name="AttendanceSync")
        self.sync_thread.start()
        logger.info("Attendance service started")

    def stop(self):
        """Stop the attendance sync service"""
        self.is_running = False
        if self.sync_thread and self.sync_thread.is_alive():
            self.sync_thread.join(timeout=5.0)
        logger.info("Attendance service stopped")

    def _sync_loop(self):
        """Main sync loop"""
        while self.is_running:
            try:
                self.device_manager.process_attendance_queue()
                self.sync_attendance()
            except Exception as e:
                logger.error(f"Error in sync loop: {e}", exc_info=True)
            # Sleep in small increments so stop() responds quickly
            for _ in range(self.sync_interval):
                if not self.is_running:
                    break
                time.sleep(1)

    def sync_attendance(self):
        """Sync pending attendance records to the server"""
        site_url = self.db.get_config_value('site_url', '')
        if not site_url or 'example.com' in site_url or site_url == 'enter your Website URL':
            logger.debug("Site URL not configured or using placeholder — skipping sync")
            return

        unsynced_records = self.db.get_unsynced_attendance()
        if not unsynced_records:
            return

        successful_syncs = []
        server_config = self.config.get('server', {})
        verify_ssl = server_config.get('verify_ssl', True)
        req_timeout = int(server_config.get('timeout', 30))
        api_key = server_config.get('api_key', '')

        headers = {}
        if api_key and api_key != 'your_api_key_here':
            headers['Authorization'] = f'Bearer {api_key}'

        for record in unsynced_records:
            try:
                json_data = {
                    'uid': record.get('user_id'),
                    'user_id': record.get('user_id'),
                    't': record.get('punch_time'),
                    'ip': record.get('device_ip'),
                    'serial_number': record.get('device_sn')
                }

                response = requests.post(
                    f"{site_url.rstrip('/')}/biometric",
                    json=json_data,
                    headers=headers,
                    timeout=req_timeout,
                    verify=verify_ssl
                )

                if response.status_code in (200, 201):
                    successful_syncs.append(record['id'])
                    logger.info(f"Synced record {record['id']} for user {record.get('user_id')}")
                else:
                    logger.warning(f"Server rejected record {record['id']}: HTTP {response.status_code}")

            except requests.Timeout:
                logger.error(f"Timeout syncing record {record.get('id')}")
            except requests.ConnectionError:
                logger.error("Cannot reach server — will retry next cycle")
                break  # Stop trying if server is unreachable
            except Exception as e:
                logger.error(f"Error syncing record {record.get('id')}: {e}")

        if successful_syncs:
            self.db.mark_attendance_synced(successful_syncs)
            logger.info(f"Marked {len(successful_syncs)} records as synced")

    def get_sync_status(self) -> Dict:
        unsynced = self.db.get_unsynced_attendance()
        return {
            'unsynced_count': len(unsynced),
            'sync_interval': self.sync_interval,
            'is_running': self.is_running,
            'last_check': datetime.now().isoformat()
        }
