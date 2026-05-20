# auto_detect_devices.py
"""
Standalone device auto-discovery script.

Usage:
    python auto_detect_devices.py                    # scan local /24 subnet
    python auto_detect_devices.py 192.168.10.0/24   # scan specific subnet
    python auto_detect_devices.py --save             # scan + save found devices to config
    python auto_detect_devices.py --timeout 2        # slower but more thorough

What it does:
    1. Scans every host on your subnet for open TCP port 4370
    2. Connects to each responding host and reads serial number, time, user count
    3. Prints a summary table
    4. Optionally updates config/default_config.json with found devices
"""
import sys
import os
import json
import argparse
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def print_banner():
    print()
    print("=" * 60)
    print("   Advanced Biometric — Device Auto-Discovery")
    print("=" * 60)
    print()


def progress_bar(scanned: int, total: int):
    pct   = int(scanned / total * 40)
    bar   = "█" * pct + "░" * (40 - pct)
    print(f"\r  [{bar}]  {scanned}/{total}", end="", flush=True)


def save_to_config(devices, config_path="config/default_config.json"):
    """Merge found devices into the config file."""
    path = Path(config_path)
    if path.exists():
        with open(path, "r") as f:
            config = json.load(f)
    else:
        config = {}

    existing_ips = {d.get("ip") for d in config.get("devices", [])}

    new_entries = []
    for dev in devices:
        if dev["ip"] in existing_ips:
            print(f"  [SKIP] {dev['ip']} already in config")
            continue
        entry = {
            "ip":            dev["ip"],
            "port":          dev.get("port", 4370),
            "serial_number": dev["serial_number"],
            "name":          dev.get("device_name", f"ZK Device {dev['ip']}"),
            "enabled":       True,
            "timeout":       30,
            "sync_time":     True,
        }
        new_entries.append(entry)
        print(f"  [ADD]  {dev['ip']}  serial={dev['serial_number']}")

    if not new_entries:
        print("  No new devices to add.")
        return

    config.setdefault("devices", []).extend(new_entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n  Config updated: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Auto-detect ZKTeco biometric devices on the network"
    )
    parser.add_argument(
        "subnet",
        nargs="?",
        default=None,
        help="Subnet to scan in CIDR notation, e.g. 192.168.1.0/24 (auto-detected if omitted)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=4370,
        help="Port to scan (default: 4370)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Probe timeout per host in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=128,
        help="Parallel scan threads (default: 128)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save discovered devices to config/default_config.json",
    )
    parser.add_argument(
        "--config",
        default="config/default_config.json",
        help="Config file path (used with --save)",
    )
    args = parser.parse_args()

    print_banner()

    try:
        from src.biometric.auto_detect import scan_subnet
    except ImportError:
        print("ERROR: Could not import auto_detect module.")
        print("       Make sure you run this from the project root directory.")
        sys.exit(1)

    # Show what we're scanning
    if args.subnet:
        print(f"  Subnet   : {args.subnet}")
    else:
        import socket, ipaddress
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            auto_subnet = str(ipaddress.IPv4Network(f"{local_ip}/24", strict=False))
            print(f"  Subnet   : {auto_subnet}  (auto-detected from {local_ip})")
        except Exception:
            print("  Subnet   : auto-detecting …")

    print(f"  Port     : {args.port}")
    print(f"  Timeout  : {args.timeout}s per host")
    print(f"  Workers  : {args.workers} parallel threads")
    print()
    print("  Scanning … (this usually takes 5-15 seconds)")
    print()

    start = time.time()

    devices = scan_subnet(
        subnet           = args.subnet,
        port             = args.port,
        timeout          = args.timeout,
        workers          = args.workers,
        progress_callback= progress_bar,
    )

    elapsed = time.time() - start
    print(f"\r  Scan complete in {elapsed:.1f}s                        ")
    print()

    # ── Results ───────────────────────────────────────────────────────
    if not devices:
        print("  No ZKTeco devices found on this subnet.")
        print()
        print("  Troubleshooting:")
        print("    • Make sure the device is powered on")
        print("    • Make sure the device is on the same network as this PC")
        print("    • Try specifying the subnet: python auto_detect_devices.py 192.168.X.0/24")
        print("    • Try a longer timeout:       python auto_detect_devices.py --timeout 3")
        print()
        sys.exit(1)

    print(f"  Found {len(devices)} device(s):")
    print()
    print(f"  {'#':>3}  {'IP Address':>16}  {'Serial Number':>20}  {'Users':>6}  {'Device Time'}")
    print("  " + "-" * 75)
    for i, dev in enumerate(devices, 1):
        print(
            f"  {i:>3}  {dev['ip']:>16}  {dev['serial_number']:>20}  "
            f"{dev['user_count']:>6}  {dev['device_time']}"
        )
    print()

    # ── Save to config ────────────────────────────────────────────────
    if args.save:
        print("  Saving to config …")
        save_to_config(devices, args.config)
        print()
        print("  Done! Run health_check.bat then scripts\\run_app.bat to start.")
    else:
        print("  Tip: run with --save to add these devices to your config automatically.")
        print(f"  Example: python auto_detect_devices.py {args.subnet or ''} --save")

    print()
    return devices


if __name__ == "__main__":
    main()
