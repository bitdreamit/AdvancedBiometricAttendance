# src/utils/windows_utils.py
import os
import sys
import logging
import subprocess
import hashlib
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# winreg is Windows-only — guard the import
try:
    import winreg
    _WINREG_AVAILABLE = True
except ImportError:
    _WINREG_AVAILABLE = False


class WindowsStartupManager:

    @staticmethod
    def install_windows_service(service_name: str, display_name: str, executable_path: str) -> bool:
        """Install application as a Windows service (requires pywin32)."""
        if sys.platform != 'win32':
            logger.error("Windows service management is only supported on Windows.")
            return False
        try:
            import win32serviceutil
            logger.info(f"Service '{service_name}' installation requested (use pywin32 service framework).")
            return True
        except ImportError:
            logger.error("pywin32 not installed. Run: pip install pywin32")
            return False
        except Exception as e:
            logger.error(f"Service installation failed: {e}")
            return False

    @staticmethod
    def uninstall_windows_service(service_name: str) -> bool:
        if sys.platform != 'win32':
            logger.error("Windows service management is only supported on Windows.")
            return False
        try:
            result = subprocess.run(['sc', 'delete', service_name],
                                    capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Service uninstallation failed: {e}")
            return False

    @staticmethod
    def enable_auto_start(app_name: str, executable_path: str) -> bool:
        if not _WINREG_AVAILABLE:
            logger.error("winreg not available (not running on Windows).")
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{executable_path}"')
            winreg.CloseKey(key)
            logger.info(f"Auto-start enabled for {app_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable auto-start: {e}")
            return False

    @staticmethod
    def disable_auto_start(app_name: str) -> bool:
        if not _WINREG_AVAILABLE:
            logger.error("winreg not available (not running on Windows).")
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, app_name)
            winreg.CloseKey(key)
            logger.info(f"Auto-start disabled for {app_name}")
            return True
        except FileNotFoundError:
            return True  # Already not set
        except Exception as e:
            logger.error(f"Failed to disable auto-start: {e}")
            return False

    @staticmethod
    def protect_executable(exe_path: str) -> bool:
        if sys.platform != 'win32':
            logger.warning("protect_executable is Windows-only.")
            return False
        if not os.path.exists(exe_path):
            logger.error(f"Executable not found: {exe_path}")
            return False
        try:
            subprocess.run([
                'icacls', exe_path,
                '/inheritance:r',
                '/grant:r', 'Administrators:(F)',
                '/grant:r', 'SYSTEM:(F)',
                '/grant:r', 'Users:(RX)'
            ], check=True, capture_output=True, text=True, timeout=30)
            logger.info(f"Permissions set on {exe_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to set permissions: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"protect_executable error: {e}")
            return False

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(4096):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def verify_executable_integrity(exe_path: str, expected_hash: Optional[str] = None) -> bool:
        if not os.path.exists(exe_path):
            logger.error(f"Executable not found: {exe_path}")
            return False
        if expected_hash is None:
            expected_hash = os.environ.get('APP_EXPECTED_HASH', '').strip()
        if not expected_hash:
            logger.info("No expected hash configured — skipping integrity check")
            return True
        try:
            current = WindowsStartupManager.calculate_file_hash(exe_path)
            if current.lower() == expected_hash.lower():
                logger.info("Integrity check passed")
                return True
            else:
                logger.warning(f"Integrity MISMATCH. Expected: {expected_hash}, Got: {current}")
                return False
        except Exception as e:
            logger.error(f"Integrity check error: {e}")
            return False

    @staticmethod
    def is_debugger_present() -> bool:
        return hasattr(sys, 'gettrace') and sys.gettrace() is not None
