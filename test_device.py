# test_device.py
"""
Device connection test script.
Usage:
    python test_device.py                        # uses env var or prompts
    python test_device.py 192.168.1.201          # pass IP as argument
    DEVICE_IP=192.168.1.201 python test_device.py
"""
import sys
import os

# One correct path insert — repo root on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.biometric.zk_device import ZKDevice


def test_device_connection(ip: str = None, port: int = 4370,
                           serial: str = "TEST_DEVICE", timeout: int = 10) -> bool:
    """Test connection to a ZKTeco biometric device."""
    print("=" * 50)
    print("ZKTeco Device Connection Test")
    print("=" * 50)

    if not ip:
        ip = os.environ.get('DEVICE_IP', '').strip()
    if not ip:
        ip = input("Enter device IP address [192.168.1.201]: ").strip() or "192.168.1.201"

    print(f"\nTarget : {ip}:{port}  serial={serial}  timeout={timeout}s")
    print("Connecting...")

    device = ZKDevice(ip=ip, port=port, serial_number=serial, timeout=timeout)

    if not device.connect():
        print(f"FAIL  Could not connect to {ip}:{port}")
        print("      Check: device is powered on, IP is reachable, port 4370 is open")
        return False

    print("PASS  Connected successfully")

    info = device.get_device_info()
    if info:
        print(f"\nDevice info:")
        for k, v in info.items():
            print(f"  {k:20}: {v}")
    else:
        print("WARN  Could not retrieve device info (connection is still OK)")

    users = device.get_users()
    print(f"\nEnrolled users : {len(users)}")

    records = device.get_live_attendance()
    print(f"Attendance logs: {len(records)}")

    device.disconnect()
    print("\nDisconnected cleanly.")
    return True


if __name__ == "__main__":
    ip_arg = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_device_connection(ip=ip_arg)
    sys.exit(0 if success else 1)
