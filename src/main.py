# src/main.py
import time
import sys
import os
import logging
import argparse
from pathlib import Path

_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from core.database import DatabaseManager
from core.device_manager import DeviceManager
from core.attendance_service import AttendanceService
from core.batch_attendance import BatchAttendancePuller
from utils.logger import setup_logging
from utils.config_manager import ConfigManager

APP_NAME    = "Advanced Biometric Attendance"
APP_VERSION = "2.2"


def check_license() -> bool:
    try:
        from utils.license_manager import LicenseManager
        lm = LicenseManager()
        ok, msg = lm.validate_license()
        if not ok:
            if not lm.license_data:
                key = lm.generate_license("Trial User", 1, 30)
                logging.getLogger(__name__).info(
                    f"Auto-generated 30-day trial license: {key[:8]}..."
                )
            else:
                logging.getLogger(__name__).warning(f"License: {msg} — continuing")
    except Exception as e:
        logging.getLogger(__name__).warning(f"License check skipped: {e}")
    return True


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    parser.add_argument('--config',            default='config/default_config.json')
    parser.add_argument('--install-service',   action='store_true')
    parser.add_argument('--uninstall-service', action='store_true')
    parser.add_argument('--enable-autostart',  action='store_true')
    parser.add_argument('--disable-autostart', action='store_true')
    args = parser.parse_args()

    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    cfg_mgr = ConfigManager()
    config  = cfg_mgr.load_config(args.config)

    log_cfg = config.get('logging', {})
    setup_logging(
        log_cfg.get('file', 'logs/app.log'),
        level=log_cfg.get('level', 'INFO'),
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")

    check_license()

    # ── Windows service / autostart commands ─────────────────────────
    if any([args.install_service, args.uninstall_service,
            args.enable_autostart, args.disable_autostart]):
        try:
            from utils.windows_utils import WindowsStartupManager
            app_path = sys.executable if getattr(sys, 'frozen', False) \
                else os.path.abspath(__file__)
            if args.install_service:
                ok = WindowsStartupManager.install_windows_service(
                    "AdvancedBiometric", APP_NAME, app_path)
            elif args.uninstall_service:
                ok = WindowsStartupManager.uninstall_windows_service("AdvancedBiometric")
            elif args.enable_autostart:
                ok = WindowsStartupManager.enable_auto_start("AdvancedBiometric", app_path)
            else:
                ok = WindowsStartupManager.disable_auto_start("AdvancedBiometric")
            sys.exit(0 if ok else 1)
        except Exception as e:
            logger.error(f"Windows utility error: {e}")
            sys.exit(1)

    # ── Database ─────────────────────────────────────────────────────
    db_path = config.get('database', {}).get('path', 'data/att.db')
    db      = DatabaseManager(db_path=db_path)

    # Push server config into DB so SyncEngine can read it
    server_cfg = config.get('server', {})
    url = server_cfg.get('url', '')
    if url and 'example.com' not in url:
        db.set_config('server_url', url)
    if server_cfg.get('api_key', ''):
        db.set_config('api_key', server_cfg['api_key'])
    if server_cfg.get('tenant_id', ''):
        db.set_config('tenant_id', server_cfg['tenant_id'])
    db.set_config('verify_ssl',   str(server_cfg.get('verify_ssl', True)).lower())
    db.set_config('batch_size',   str(config.get('sync', {}).get('batch_size', 100)))

    # ── Devices + services ───────────────────────────────────────────
    device_manager     = DeviceManager(db, config=config)
    attendance_service = AttendanceService(db, device_manager, config=config)
    batch_puller       = BatchAttendancePuller(
        db_manager       = db,
        devices          = {},          # filled after connect
        interval_seconds = int(config.get('sync', {}).get('batch_interval', 300)),
        clear_after_pull = config.get('sync', {}).get('clear_after_batch', False),
    )

    # ── Optional agent HTTP API ──────────────────────────────────────
    agent_api = None
    agent_api_cfg = config.get('agent_api', {})
    if agent_api_cfg.get('enabled', False):
        try:
            from core.agent_api import AgentAPI
            agent_api = AgentAPI(
                sync_engine    = attendance_service.sync_engine,
                device_manager = device_manager,
                db             = db,
                host           = agent_api_cfg.get('host', '127.0.0.1'),
                port           = int(agent_api_cfg.get('port', 5000)),
                api_token      = agent_api_cfg.get('token', ''),
            )
            agent_api.start()
        except Exception as e:
            logger.warning(f"AgentAPI could not start: {e}")

    try:
        device_manager.initialize_devices(config.get('devices', []))
        device_manager.start_live_capture()

        # Give BatchAttendancePuller the connected devices
        batch_puller.devices = device_manager.devices
        if device_manager.devices:
            batch_puller.start()

        sync_cfg = config.get('sync', {})
        attendance_service.start(sync_cfg)

        logger.info(f"All services started — press Ctrl+C to stop")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down...")
        attendance_service.stop()
        batch_puller.stop()
        if agent_api:
            agent_api.stop()
        device_manager.disconnect_all()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
