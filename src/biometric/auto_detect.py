# src/biometric/auto_detect.py
"""
Auto-detects ZKTeco biometric devices on the local network.
Scans the current subnet on port 4370 concurrently and returns
a list of discovered devices with their IP, serial number and info.
"""
import socket
import ipaddress
import threading
import logging
import time
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

ZK_DEFAULT_PORT = 4370
DEFAULT_TIMEOUT  = 1.0   # seconds per host probe
DEFAULT_WORKERS  = 128   # parallel probes


def _get_local_subnet() -> List[str]:
    """Return all host IPs on the machine's primary subnet (e.g. 192.168.1.0/24)."""
    subnets = []
    try:
        # Connect to a public address to discover the primary interface IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Assume /24 subnet
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        subnets = [str(h) for h in network.hosts()]
    except Exception as e:
        logger.warning(f"Could not determine local subnet: {e}")
    return subnets


def _probe_host(ip: str, port: int = ZK_DEFAULT_PORT,
                timeout: float = DEFAULT_TIMEOUT) -> Optional[str]:
    """Return ip if port 4370 is open, else None."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return ip if result == 0 else None
    except Exception:
        return None


def _get_device_info(ip: str, port: int = ZK_DEFAULT_PORT) -> Optional[Dict]:
    """
    Try to connect to the ZKTeco device and read its serial number and time.
    Returns a dict or None if unreachable.
    """
    try:
        # Import here to avoid circular imports
        from src.biometric.zk_device import ZKDevice
    except ImportError:
        from biometric.zk_device import ZKDevice

    device = ZKDevice(ip=ip, port=port, serial_number=f"SCAN_{ip}", timeout=5)
    try:
        if device.connect():
            info = device.get_device_info()
            users = device.get_users()
            device.disconnect()
            return {
                "ip":            ip,
                "port":          port,
                "serial_number": info.get("serial_number", f"UNKNOWN_{ip}") if info else f"UNKNOWN_{ip}",
                "device_name":   info.get("device_name",   f"ZK Device {ip}") if info else f"ZK Device {ip}",
                "device_time":   info.get("device_time",   "Unknown") if info else "Unknown",
                "user_count":    len(users),
                "reachable":     True,
            }
    except Exception as e:
        logger.debug(f"Could not get info from {ip}: {e}")
    finally:
        try:
            device.disconnect()
        except Exception:
            pass
    return None


def scan_subnet(
    subnet: str = None,
    port: int = ZK_DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    workers: int = DEFAULT_WORKERS,
    progress_callback=None,
) -> List[Dict]:
    """
    Scan a subnet for ZKTeco devices.

    Args:
        subnet:            CIDR notation e.g. '192.168.1.0/24'. Auto-detected if None.
        port:              Port to probe (default 4370).
        timeout:           Per-host probe timeout in seconds.
        workers:           Max parallel threads.
        progress_callback: Optional callable(scanned, total) called after each probe.

    Returns:
        List of dicts for each discovered device.
    """
    if subnet:
        try:
            hosts = [str(h) for h in ipaddress.IPv4Network(subnet, strict=False).hosts()]
        except ValueError as e:
            logger.error(f"Invalid subnet '{subnet}': {e}")
            return []
    else:
        hosts = _get_local_subnet()
        if not hosts:
            logger.error("Could not determine local subnet. Pass subnet= explicitly.")
            return []

    total = len(hosts)
    logger.info(f"Scanning {total} hosts on port {port} with {workers} workers …")

    reachable = []
    scanned   = 0
    lock      = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_probe_host, ip, port, timeout): ip for ip in hosts}
        for future in as_completed(futures):
            result = future.result()
            with lock:
                scanned += 1
                if progress_callback:
                    try:
                        progress_callback(scanned, total)
                    except Exception:
                        pass
            if result:
                reachable.append(result)

    logger.info(f"Scan complete. Found {len(reachable)} device(s) with open port {port}.")

    # Now fetch detailed info from each reachable host
    devices = []
    for ip in reachable:
        logger.info(f"Getting device info from {ip} …")
        info = _get_device_info(ip, port)
        if info:
            devices.append(info)
            logger.info(f"  → {ip}  serial={info['serial_number']}  users={info['user_count']}")
        else:
            # Port was open but could not speak ZK protocol — still report it
            devices.append({
                "ip":            ip,
                "port":          port,
                "serial_number": f"UNKNOWN_{ip}",
                "device_name":   f"ZK Device {ip}",
                "device_time":   "Unknown",
                "user_count":    0,
                "reachable":     True,
            })

    return devices
