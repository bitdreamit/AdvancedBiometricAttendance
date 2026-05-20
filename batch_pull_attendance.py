# batch_pull_attendance.py
"""
Standalone batch attendance pull script.

Connects to all enabled devices in config, pulls ALL stored attendance
records, deduplicates, writes new ones to the local database, and
optionally syncs to the remote server.

Usage:
    python batch_pull_attendance.py                  # pull all devices from config
    python batch_pull_attendance.py --ip 192.168.1.201              # single device
    python batch_pull_attendance.py --hours 24       # last 24 hours only
    python batch_pull_attendance.py --clear          # clear device log after pull
    python batch_pull_attendance.py --sync           # also push to server after pull
    python batch_pull_attendance.py --loop 300       # repeat every 300 seconds
"""
import sys
import os
import json
import argparse
import time
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_console_logging(level="INFO"):
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(path="config/default_config.json"):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config not found: {path}")
        print("       Run install.bat first, then edit config/default_config.json")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}")
        sys.exit(1)


def build_devices_from_config(config):
    """Build ZKDevice objects for all enabled devices in config."""
    from src.biometric.zk_device import ZKDevice

    device_map = {}
    for d in config.get("devices", []):
        if not d.get("enabled", False):
            logging.info(f"Skipping disabled device {d.get('serial_number', d.get('ip'))}")
            continue
        serial = d.get("serial_number") or d["ip"]
        device_map[serial] = ZKDevice(
            ip            = d["ip"],
            port          = d.get("port", 4370),
            serial_number = serial,
            timeout       = d.get("timeout", 30),
        )
    return device_map


def connect_devices(device_map):
    """Attempt connection to all devices. Returns connected subset."""
    connected = {}
    for serial, device in device_map.items():
        logging.info(f"Connecting to {serial} ({device.ip}) …")
        if device.connect():
            logging.info(f"  [OK]  Connected to {serial}")
            connected[serial] = device
        else:
            logging.warning(f"  [!!]  Could not connect to {serial} ({device.ip})")
    return connected


def disconnect_all(device_map):
    for serial, device in device_map.items():
        try:
            device.disconnect()
        except Exception:
            pass


def do_server_sync(db, config):
    """Push pending records to server."""
    from src.core.attendance_service import AttendanceService
    from src.core.device_manager import DeviceManager

    dm  = DeviceManager(db)
    svc = AttendanceService(db, dm, config=config)
    logging.info("Syncing pending records to server …")
    svc.sync_attendance()
    logging.info("Server sync complete.")


def print_summary(result: dict):
    print()
    print("=" * 60)
    print("  BATCH PULL SUMMARY")
    print("=" * 60)
    total_pulled   = result.get("total_pulled", 0)
    total_new      = result.get("total_new",    0)
    total_skipped  = sum(d.get("skipped",  0) for d in result.get("devices", {}).values())
    total_errors   = result.get("errors", 0)

    print(f"  Total records on devices : {total_pulled}")
    print(f"  New records inserted     : {total_new}")
    print(f"  Duplicates skipped       : {total_skipped}")
    print(f"  Device errors            : {total_errors}")
    print()
    for serial, d in result.get("devices", {}).items():
        status = "ERROR: " + d["error"] if d.get("error") else "OK"
        print(f"  [{status:>6}]  {serial:25}  pulled={d.get('pulled',0):5}  new={d.get('inserted',0):5}  skip={d.get('skipped',0):5}")
    print("=" * 60)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Batch pull attendance records from ZKTeco devices"
    )
    parser.add_argument("--ip",     help="Pull from a single device IP (ignores config devices)")
    parser.add_argument("--port",   type=int, default=4370, help="Device port (default: 4370)")
    parser.add_argument("--serial", help="Serial number for single-device mode (optional)")
    parser.add_argument("--hours",  type=int, default=0,
                        help="Only import records from last N hours (0 = all)")
    parser.add_argument("--clear",  action="store_true",
                        help="Clear device attendance log after successful pull")
    parser.add_argument("--sync",   action="store_true",
                        help="Sync new records to server after pull")
    parser.add_argument("--loop",   type=int, default=0,
                        help="Repeat pull every N seconds (0 = run once)")
    parser.add_argument("--config", default="config/default_config.json",
                        help="Path to config file")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG","INFO","WARNING","ERROR"],
                        help="Log verbosity")
    args = parser.parse_args()

    setup_console_logging(args.log_level)

    print()
    print("=" * 60)
    print("  Advanced Biometric — Batch Attendance Pull")
    print("=" * 60)
    print()

    config = load_config(args.config)

    from src.core.database import DatabaseManager
    from src.core.batch_attendance import BatchAttendancePuller
    from src.biometric.zk_device import ZKDevice

    db_path = config.get("database", {}).get("path", "data/att.db")
    db = DatabaseManager(db_path=db_path)

    # Build device map
    if args.ip:
        serial = args.serial or f"MANUAL_{args.ip}"
        device_map = {serial: ZKDevice(ip=args.ip, port=args.port, serial_number=serial)}
        logging.info(f"Single device mode: {args.ip}:{args.port}")
    else:
        device_map = build_devices_from_config(config)
        if not device_map:
            print("  ERROR: No enabled devices in config.")
            print("         Edit config/default_config.json and set \"enabled\": true")
            sys.exit(1)
        logging.info(f"Loaded {len(device_map)} device(s) from config")

    if args.clear:
        print("  WARNING: --clear is enabled.")
        print("           Device attendance logs will be erased after each pull.")
        print("           Make sure your database is backed up.")
        print()

    def run_once():
        connected = connect_devices(device_map)
        if not connected:
            logging.error("No devices could be connected. Aborting.")
            return None

        puller = BatchAttendancePuller(
            db_manager       = db,
            devices          = connected,
            interval_seconds = args.loop or 300,
            clear_after_pull = args.clear,
            since_hours      = args.hours,
        )

        result = puller.pull_now()
        disconnect_all(connected)
        print_summary(result)

        if args.sync:
            do_server_sync(db, config)

        return result

    if args.loop > 0:
        logging.info(f"Running in loop mode — pulling every {args.loop}s. Press Ctrl+C to stop.")
        try:
            while True:
                run_once()
                print(f"  Next pull in {args.loop}s … (Ctrl+C to stop)")
                for _ in range(args.loop):
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Stopped by user.")
    else:
        result = run_once()
        sys.exit(0 if result and result.get("errors", 0) == 0 else 1)


if __name__ == "__main__":
    main()
