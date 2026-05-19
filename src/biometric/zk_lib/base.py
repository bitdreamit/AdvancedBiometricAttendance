# -*- coding: utf-8 -*-
import sys
from datetime import datetime
from socket import AF_INET, SOCK_DGRAM, SOCK_STREAM, socket, timeout
from struct import pack, unpack
import codecs
import logging
from typing import List, Optional, Generator

from . import const
from .attendance import Attendance
from .exception import ZKErrorConnection, ZKErrorResponse, ZKNetworkError
from .user import User
from .finger import Finger

logger = logging.getLogger(__name__)


def safe_cast(val, to_type, default=None):
    try:
        return to_type(val)
    except (ValueError, TypeError):
        return default


def make_commkey(key, session_id, ticks=50):
    """
    Take a password and session_id and scramble them to send to the machine.
    Copied from commpro.c - MakeKey
    """
    key = int(key)
    session_id = int(session_id)
    k = 0
    for i in range(32):
        if key & (1 << i):
            k = (k << 1) | 1
        else:
            k = k << 1
    k += session_id
    k = pack(b'I', k)
    k = unpack(b'BBBB', k)
    k = pack(b'BBBB', k[0] ^ ord('Z'), k[1] ^ ord('K'), k[2] ^ ord('S'), k[3] ^ ord('O'))
    k = unpack(b'HH', k)
    k = pack(b'HH', k[1], k[0])
    B = 255 & ticks
    k = unpack(b'BBBB', k)
    k = pack(b'BBBB', k[0] ^ B, k[1] ^ B, B, k[3] ^ B)
    return k


class ZK_helper(object):
    def __init__(self, ip, port=4370):
        self.address = (ip, port)
        self.ip = ip
        self.port = port

    def test_ping(self):
        import subprocess
        import platform
        ping_str = '-n 1' if platform.system().lower() == 'windows' else '-c 1 -W 5'
        args = 'ping ' + ping_str + ' ' + self.ip
        need_sh = False if platform.system().lower() == 'windows' else True
        try:
            return subprocess.call(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=need_sh) == 0
        except Exception:
            return False

    def test_tcp(self):
        self.client = socket(AF_INET, SOCK_STREAM)
        self.client.settimeout(10)
        res = self.client.connect_ex(self.address)
        self.client.close()
        return res

    def test_udp(self):
        self.client = socket(AF_INET, SOCK_DGRAM)
        self.client.settimeout(10)
        return True


class ZK(object):
    """ZK main class - handles ZKTeco device communication"""

    def __init__(self, ip, port=4370, timeout=60, password=0, force_udp=False,
                 ommit_ping=False, verbose=False, encoding='UTF-8'):
        self.address = (ip, port)
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.password = password
        self.force_udp = force_udp
        self.ommit_ping = ommit_ping
        self.verbose = verbose
        self.encoding = encoding
        self.helper = ZK_helper(ip, port)

        self.__session_id = 0
        self.__reply_id = const.USHRT_MAX - 1
        self.__sock = None
        self.__is_connected = False
        self.__data_recv = None
        self.__data = None

    def connect(self):
        """Connect to the device"""
        if not self.ommit_ping:
            if not self.helper.test_ping():
                raise ZKNetworkError(f"Host {self.ip} is unreachable")

        if self.force_udp:
            self.__sock = socket(AF_INET, SOCK_DGRAM)
        else:
            self.__sock = socket(AF_INET, SOCK_STREAM)

        self.__sock.settimeout(self.timeout)

        try:
            if not self.force_udp:
                self.__sock.connect(self.address)

            self.__session_id = 0
            self.__reply_id = const.USHRT_MAX - 1

            cmd_response = self.__send_command(const.CMD_CONNECT)
            if cmd_response.get('status'):
                self.__session_id = cmd_response.get('session_id', 0)
                self.__is_connected = True

                if self.password:
                    pwd_response = self.__send_command(
                        const.CMD_COMMITPWD,
                        make_commkey(self.password, self.__session_id)
                    )
                    if not pwd_response.get('status'):
                        raise ZKErrorConnection("Password authentication failed")

                self.__send_command(const.CMD_ENABLE_CLOCK)
                return self

            raise ZKErrorConnection("Device refused connection")

        except timeout:
            raise ZKNetworkError(f"Connection to {self.ip}:{self.port} timed out")
        except ZKNetworkError:
            raise
        except ZKErrorConnection:
            raise
        except Exception as e:
            raise ZKErrorConnection(f"Connection error: {e}")

    def disconnect(self):
        """Disconnect from device"""
        try:
            if self.__is_connected:
                self.__send_command(const.CMD_EXIT)
        except Exception:
            pass
        finally:
            self.__is_connected = False
            if self.__sock:
                try:
                    self.__sock.close()
                except Exception:
                    pass
                self.__sock = None

    def __send_command(self, command, data=b'', response_size=1024):
        """Send command to device and receive response"""
        if command == const.CMD_CONNECT:
            self.__session_id = 0
            self.__reply_id = const.USHRT_MAX - 1

        self.__reply_id = (self.__reply_id + 1) % const.USHRT_MAX

        buf = self.__create_header(command, data)

        try:
            if self.force_udp:
                self.__sock.sendto(buf, self.address)
                self.__data_recv, _ = self.__sock.recvfrom(response_size)
            else:
                self.__sock.send(buf)
                self.__data_recv = self.__receive_response(response_size)

            if len(self.__data_recv) < 8:
                raise ZKErrorResponse("Response too short")

            # Parse response header
            res_code, _, _, res_session_id, res_reply_id = unpack('<HHHHI', self.__data_recv[:12]) if len(self.__data_recv) >= 12 else (0, 0, 0, 0, 0)

            if len(self.__data_recv) >= 8:
                res_code = unpack('<H', self.__data_recv[0:2])[0]
                res_session_id = unpack('<H', self.__data_recv[4:6])[0]

                if command == const.CMD_CONNECT:
                    self.__session_id = res_session_id

                return {
                    'status': res_code in (const.CMD_ACK_OK, const.CMD_ACK_UNAUTH),
                    'code': res_code,
                    'session_id': res_session_id,
                    'data': self.__data_recv[8:] if len(self.__data_recv) > 8 else b''
                }

        except timeout:
            raise ZKNetworkError(f"Command {command} timed out")
        except Exception as e:
            if 'timed out' in str(e).lower():
                raise ZKNetworkError(f"Command {command} timed out")
            raise ZKErrorResponse(f"Command {command} failed: {e}")

        return {'status': False, 'code': 0, 'data': b''}

    def __receive_response(self, size=1024):
        """Receive response from TCP connection"""
        data = b''
        while True:
            try:
                chunk = self.__sock.recv(size)
                if not chunk:
                    break
                data += chunk
                if len(data) >= 8:
                    break
            except timeout:
                break
        return data

    def __create_header(self, command, data=b''):
        """Create command header packet"""
        if isinstance(data, str):
            data = data.encode(self.encoding)
        elif not isinstance(data, bytes):
            data = bytes(data)

        chksum = 0
        session_id = self.__session_id
        reply_id = self.__reply_id

        header = pack('<HHHH', command, chksum, session_id, reply_id)
        buf = header + data

        # Recalculate checksum
        chksum = 0
        for i in range(0, len(buf) - 1, 2):
            word = unpack('<H', buf[i:i+2])[0]
            chksum ^= word

        buf = pack('<HHHH', command, chksum, session_id, reply_id) + data
        return pack('>I', len(buf)) + buf if not self.force_udp else buf

    def get_time(self):
        """Get device time"""
        cmd_response = self.__send_command(const.CMD_GET_TIME)
        if cmd_response.get('status') and cmd_response.get('data'):
            try:
                time_data = unpack('<I', cmd_response['data'][:4])[0]
                # ZK time encoding: seconds since 2000-01-01
                second = time_data % 60
                time_data //= 60
                minute = time_data % 60
                time_data //= 60
                hour = time_data % 24
                time_data //= 24
                day = time_data % 31 + 1
                time_data //= 31
                month = time_data % 12 + 1
                time_data //= 12
                year = time_data + 2000
                return datetime(year, month, day, hour, minute, second)
            except Exception as e:
                logger.error(f"Error parsing device time: {e}")
        return datetime.now()

    def set_time(self, timestamp=None):
        """Set device time"""
        if timestamp is None:
            timestamp = datetime.now()
        try:
            t = (timestamp.year - 2000) * 12 * 31 * 24 * 60 * 60 + \
                (timestamp.month - 1) * 31 * 24 * 60 * 60 + \
                (timestamp.day - 1) * 24 * 60 * 60 + \
                timestamp.hour * 60 * 60 + \
                timestamp.minute * 60 + \
                timestamp.second
            cmd_response = self.__send_command(const.CMD_SET_TIME, pack('<I', t))
            return cmd_response.get('status', False)
        except Exception as e:
            logger.error(f"Error setting device time: {e}")
            return False

    def get_users(self):
        """Get all users from device"""
        users = []
        cmd_response = self.__send_command(const.CMD_DB_RRQ, const.FC_PC_USERS)
        if not cmd_response.get('status'):
            return users

        data = cmd_response.get('data', b'')
        if not data:
            return users

        record_size = 28
        for i in range(0, len(data) - record_size + 1, record_size):
            try:
                uid, privilege, password, name, card, group_id, timezone, user_id = unpack(
                    '<HB5s24sIHHI', data[i:i+record_size]
                )
                name = name.rstrip(b'\x00').decode(self.encoding, errors='ignore')
                password = password.rstrip(b'\x00').decode('ascii', errors='ignore')
                users.append(User(uid, name, privilege, password, group_id, user_id))
            except Exception as e:
                logger.debug(f"Error parsing user record at offset {i}: {e}")
        return users

    def get_attendance(self):
        """Get all attendance records from device"""
        records = []
        cmd_response = self.__send_command(const.CMD_ATTLOG_RRQ)
        if not cmd_response.get('status'):
            return records

        data = cmd_response.get('data', b'')
        if not data:
            return records

        record_size = 40
        for i in range(0, len(data) - record_size + 1, record_size):
            try:
                user_id_raw, timestamp_raw, status, punch = unpack(
                    '<24sIBB', data[i:i+30]
                )
                user_id = user_id_raw.rstrip(b'\x00').decode('ascii', errors='ignore')
                dt = self._decode_time(timestamp_raw)
                records.append(Attendance(user_id, dt, status, punch))
            except Exception as e:
                logger.debug(f"Error parsing attendance record at offset {i}: {e}")
        return records

    def live_capture(self, new_timeout=10):
        """Live capture attendance events"""
        was_timeout = self.__sock.gettimeout() if self.__sock else new_timeout
        try:
            if self.__sock:
                self.__sock.settimeout(new_timeout)
            self.__send_command(const.CMD_REG_EVENT, pack('<I', const.EF_ATTLOG))

            while self.__is_connected:
                try:
                    if self.force_udp:
                        data_recv, _ = self.__sock.recvfrom(1032)
                    else:
                        data_recv = self.__receive_response(1032)

                    if len(data_recv) >= 16:
                        event_code = unpack('<H', data_recv[8:10])[0]
                        if event_code == const.EF_ATTLOG and len(data_recv) >= 32:
                            try:
                                event_data = data_recv[16:]
                                user_id_raw = event_data[:24].rstrip(b'\x00').decode('ascii', errors='ignore')
                                timestamp_raw = unpack('<I', event_data[24:28])[0]
                                status = event_data[28] if len(event_data) > 28 else 0
                                punch = event_data[29] if len(event_data) > 29 else 0
                                dt = self._decode_time(timestamp_raw)
                                yield Attendance(user_id_raw, dt, status, punch)
                            except Exception as e:
                                logger.debug(f"Error parsing live event: {e}")

                except timeout:
                    yield None  # Yield None to allow caller to check is_running
                except Exception as e:
                    logger.error(f"Live capture error: {e}")
                    break

        finally:
            try:
                self.__send_command(const.CMD_CANCELCAPTURE)
                if self.__sock:
                    self.__sock.settimeout(was_timeout)
            except Exception:
                pass

    def clear_attendance(self):
        """Clear all attendance records from device"""
        cmd_response = self.__send_command(const.CMD_CLEAR_ATTLOG)
        return cmd_response.get('status', False)

    def _decode_time(self, t):
        """Decode ZK time integer to datetime"""
        try:
            second = t % 60
            t //= 60
            minute = t % 60
            t //= 60
            hour = t % 24
            t //= 24
            day = t % 31 + 1
            t //= 31
            month = t % 12 + 1
            t //= 12
            year = t + 2000
            return datetime(year, month, day, hour, minute, second)
        except Exception:
            return datetime.now()

    def enable_device(self):
        """Enable device"""
        return self.__send_command(const.CMD_ENABLE_CLOCK).get('status', False)

    def disable_device(self):
        """Disable device"""
        return self.__send_command(const.CMD_STARTVERIFY).get('status', False)
