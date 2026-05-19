# src/utils/config_manager.py
import json
import configparser
import os
import logging
from pathlib import Path
from typing import Dict, Any
import hashlib

logger = logging.getLogger(__name__)

PLACEHOLDER_VALUES = {'your_api_key_here', 'DEVICE_SERIAL_NUMBER', 'enter your Website URL'}


class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self, filename: str = "default_config.json") -> Dict[str, Any]:
        """Load config from a JSON or INI file. Creates default if not found."""
        # Allow absolute paths too
        config_path = Path(filename) if Path(filename).is_absolute() else self.config_dir / filename

        if not config_path.exists():
            # Try just the filename in config_dir
            alt = self.config_dir / Path(filename).name
            if alt.exists():
                config_path = alt
            else:
                logger.warning(f"Config not found at {config_path}, creating default")
                return self._create_and_save_default(config_path)

        try:
            if config_path.suffix == '.json':
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self._warn_placeholders(config)
                return config
            elif config_path.suffix in ('.ini', '.cfg'):
                return self._load_ini(config_path)
            else:
                logger.error(f"Unsupported config format: {config_path.suffix}")
                return self._get_default_config()
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {config_path}: {e}")
            return self._get_default_config()
        except Exception as e:
            logger.error(f"Failed to load config {config_path}: {e}")
            return self._get_default_config()

    def _load_ini(self, path: Path) -> Dict[str, Any]:
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding='utf-8')
        return {section: dict(cfg.items(section)) for section in cfg.sections()}

    def save_config(self, config: Dict[str, Any], filename: str = "default_config.json") -> bool:
        path = self.config_dir / filename
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            logger.info(f"Config saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def _create_and_save_default(self, path: Path) -> Dict[str, Any]:
        cfg = self._get_default_config()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
            logger.info(f"Created default config at {path}")
        except Exception as e:
            logger.error(f"Could not write default config: {e}")
        return cfg

    def _warn_placeholders(self, config: Dict, _path: str = '') -> None:
        """Log warnings for any placeholder values still in the config."""
        for key, value in config.items():
            full_key = f"{_path}.{key}" if _path else key
            if isinstance(value, dict):
                self._warn_placeholders(value, full_key)
            elif isinstance(value, str) and value in PLACEHOLDER_VALUES:
                logger.warning(f"Placeholder value detected in config: {full_key} = '{value}'. "
                               f"Please update config/default_config.json")

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "database": {
                "path": "data/att.db",
                "auto_create": True,
                "encryption": False
            },
            "logging": {
                "level": "INFO",
                "file": "logs/app.log",
                "max_size_mb": 10,
                "backup_count": 5
            },
            "sync": {
                "interval_seconds": 300,
                "retry_attempts": 3,
                "retry_delay_seconds": 60,
                "batch_size": 100
            },
            "devices": [],
            "server": {
                "url": "",
                "api_key": "",
                "sync_enabled": False,
                "verify_ssl": True,
                "timeout": 30
            },
            "security": {
                "encryption_enabled": False,
                "integrity_check": False
            },
            "application": {
                "auto_start": False,
                "minimize_to_tray": True,
                "language": "en"
            }
        }

    def validate_config(self, config: Dict[str, Any]) -> bool:
        required = ['database', 'logging', 'server']
        for section in required:
            if section not in config:
                logger.warning(f"Missing config section: {section}")
                return False
        if not config.get('database', {}).get('path'):
            logger.error("database.path is required")
            return False
        return True

    def get_config_hash(self, config: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def get_config(config_file: str = "default_config.json") -> Dict[str, Any]:
    return ConfigManager().load_config(config_file)
