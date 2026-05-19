# src/main.py
import time
import sys
import os
import logging
import argparse
from pathlib import Path

# Fix: single, correct sys.path setup - add src dir so core/utils imports work
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Also add project root for top-level imports
ROOT_DIR = os.path.dirname(SRC_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.database import DatabaseManager
from core.device_manager import DeviceManager
from core.attendance_service import AttendanceService
from utils.logger import setup_logging
from utils.config_manager import ConfigManager

APP_NAME = "Advanced Biometric Application"
APP_VERSION = "2.0"

# Fix: only import winreg/windows_utils when actually on Windows
IS_WINDOWS = sys.platform == 'win32'


def check_license():
    """Non-interactive license check"""
    try:
        from utils.license_manager import LicenseManager
        license_manager = LicenseManager()
        is_valid, message = license_manager.validate_license()

        if not is_valid:
            if not license_manager.license_data:
                license_key = license_manager.generate_license("Trial User", 1, 30)
                print(f"Auto-generated trial license: {license_key}")
                return True
            else:
                print(f"License Error: {message}")
                return True  # Continue for demo purposes

        return True
    except Exception as e:
        print(f"License check skipped: {e}")
        return True


def validate_config(config: dict) -> bool:
    """Fix: Startup config validation - detect placeholder values and warn clearly."""
    warnings = []
    devices = config.get("devices", [])
    for d in devices:
        if d.get("serial_number", "").upper() in ("DEVICE_SERIAL_NUMBER", "", "YOUR_SERIAL"):
            warnings.append(
                f"  - Device '{d.get('name', d['ip'])}' has placeholder serial_number. "
                "Update config/default_config.json before connecting."
            )
        if d.get("ip", "").startswith("192.168.1.201"):
            warnings.append(
                f"  - Device IP is still the example value '192.168.1.201'. "
                "Set your actual device IP in config/default_config.json."
            )

    server = config.get("server", {})
    if server.get("api_key", "") in ("your_api_key_here", "", "YOUR_API_KEY"):
        warnings.append("  - Server api_key is not configured. Server sync will be disabled.")
    if "your-academy.example.com" in server.get("url", ""):
        warnings.append("  - Server URL is still the example value. Server sync will be disabled.")

    if warnings:
        print("\n[CONFIG WARNING] The following settings use placeholder values:")
        for w in warnings:
            print(w)
        print("  Edit config/default_config.json to configure your installation.\n")
    return True  # Warn but don't block startup


def main():
    if not check_license():
        sys.exit(1)

    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument('--minimized', action='store_true')
    parser.add_argument('--install-service', action='store_true')
    parser.add_argument('--uninstall-service', action='store_true')
    parser.add_argument('--enable-autostart', action='store_true')
    parser.add_argument('--disable-autostart', action='store_true')
    parser.add_argument('--config', default='config/default_config.json',
                        help='Path to configuration file')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (disables anti-debugger check)')
    args = parser.parse_args()

    # Fix: pass --debug flag to environment so custom_runtime.py skips debugger check
    if args.debug:
        os.environ['DEV_MODE'] = '1'

    # Setup logging
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    setup_logging(str(log_dir / "app.log"))

    logger = logging.getLogger(__name__)
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")

    # Load configuration
    config_manager = ConfigManager()
    config = config_manager.load_config(os.path.basename(args.config))

    # Fix: validate config and warn about placeholders at startup
    validate_config(config)

    # Handle Windows-specific service/autostart commands
    if IS_WINDOWS:
        from utils.windows_utils import WindowsStartupManager
        if args.install_service:
            app_path = sys.executable if getattr(sys, 'frozen', False) else __file__
            success = WindowsStartupManager.install_windows_service(
                "AdvancedBiometric", APP_NAME, app_path
            )
            sys.exit(0 if success else 1)

        if args.uninstall_service:
            success = WindowsStartupManager.uninstall_windows_service("AdvancedBiometric")
            sys.exit(0 if success else 1)

        if args.enable_autostart:
            app_path = sys.executable if getattr(sys, 'frozen', False) else __file__
            success = WindowsStartupManager.enable_auto_start("AdvancedBiometric", app_path)
            sys.exit(0 if success else 1)

        if args.disable_autostart:
            success = WindowsStartupManager.disable_auto_start("AdvancedBiometric")
            sys.exit(0 if success else 1)
    elif any([args.install_service, args.uninstall_service,
              args.enable_autostart, args.disable_autostart]):
        print("Windows service/autostart commands are only supported on Windows.")
        sys.exit(1)

    # Initialize database
    db_path = config.get("database", {}).get("path", "data/att.db")
    db_manager = DatabaseManager(db_path=db_path, config=config.get("database", {}))

    # Initialize services with config
    device_manager = DeviceManager(db_manager, config=config)
    attendance_service = AttendanceService(db_manager, device_manager, config=config)

    try:
        devices_config = config.get("devices", [])
        # Only connect to enabled devices
        enabled_devices = [d for d in devices_config if d.get("enabled", True)]
        if not enabled_devices:
            logger.warning("No enabled devices found in configuration. Running in offline mode.")
        else:
            device_manager.initialize_devices(enabled_devices)

        device_manager.start_live_capture()
        attendance_service.start()

        logger.info("All services started successfully")
        print(f"{APP_NAME} v{APP_VERSION} is running. Press Ctrl+C to stop.")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        print("\nShutting down...")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
    finally:
        device_manager.stop_live_capture()
        device_manager.disconnect_all()
        attendance_service.stop()
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
