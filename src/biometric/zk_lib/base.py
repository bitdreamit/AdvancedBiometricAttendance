# -*- coding: utf-8 -*-
import sys
from datetime import datetime
from socket import AF_INET, SOCK_DGRAM, SOCK_STREAM, socket, timeout as sock_timeout
from struct import pack, unpack
import logging
from typing import List, Optional, Generator

from . import const
from .attendance import Attendance
from .exception import ZKErrorConnection, ZKErrorResponse, ZKNetworkError
from .user import User
from .finger import Finger

logger = logging.getLogger(__name__)


def make_commkey(key, session_id, ticks=50):
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


class ZK:
    """ZKTeco device low-level protocol driver (TCP + UDP)."""

    def __init__(self, ip, port=4370, timeout=60, password=0,
                 force_udp=False, ommit_ping=False, encoding='UTF-8'):
        self.ip          = ip
        self.port        = port
        self.address     = (ip, port)
        self.timeout     = timeout
        self.password    = password
        self.force_udp   = force_udp
        self.ommit_ping  = ommit_ping
        self.encoding    = encoding

        self.__session_id    = 0
        self.__reply_id      = const.USHRT_MAX - 1
        self.__sock          = None
        self.__is_connected  = False

    # ------------------------------------------------------------------ #
    # Connection                                                           #
    # ------------------------------------------------------------------ #

    def connect(self):
        if not self.ommit_ping:
            if not self._test_tcp_reachable():
                raise ZKNetworkError(f"Host {self.ip}:{self.port} is unreachable")

        self.__sock = (socket(AF_INET, SOCK_DGRAM)
                       if self.force_udp
                       else socket(AF_INET, SOCK_STREAM))
        self.__sock.settimeout(self.timeout)

        try:
            if not self.force_udp:
                self.__sock.connect(self.address)

            self.__session_id = 0
            self.__reply_id   = const.USHRT_MAX - 1

            resp = self._send_command(const.CMD_CONNECT)
            if resp.get('status'):
                self.__session_id  = resp.get('session_id', 0)
                self.__is_connected = True

                if self.password:
                    pr = self._send_command(
                        const.CMD_COMMITPWD,
                        make_commkey(self.password, self.__session_id)
                    )
                    if not pr.get('status'):
                        raise ZKErrorConnection("Password authentication failed")

                self._send_command(const.CMD_ENABLE_CLOCK)
                return self

            raise ZKErrorConnection("Device refused connection")

        except sock_timeout:
            raise ZKNetworkError(f"Connection to {self.ip}:{self.port} timed out")
        except (ZKNetworkError, ZKErrorConnection):
            raise
        except Exception as e:
            raise ZKErrorConnection(f"Connection error: {e}")

    def disconnect(self):
        try:
            if self.__is_connected and self.__sock:
                self._send_command(const.CMD_EXIT)
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

    def _test_tcp_reachable(self) -> bool:
        try:
            s = socket(AF_INET, SOCK_STREAM)
            s.settimeout(5)
            ok = s.connect_ex(self.address) == 0
            s.close()
            return ok
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Internal packet layer                                                #
    # ------------------------------------------------------------------ #

    def _send_command(self, command, data=b'', response_size=1024):
        if command == const.CMD_CONNECT:
            self.__session_id = 0
            self.__reply_id   = const.USHRT_MAX - 1

        self.__reply_id = (self.__reply_id + 1) % const.USHRT_MAX
        buf = self._build_packet(command, data)

        try:
            if self.force_udp:
                self.__sock.sendto(buf, self.address)
                raw, _ = self.__sock.recvfrom(response_size)
            else:
                self.__sock.send(buf)
                raw = self._recv_tcp(response_size)

            if len(raw) < 8:
                raise ZKErrorResponse("Response packet too short")

            res_code       = unpack('<H', raw[0:2])[0]
            res_session_id = unpack('<H', raw[4:6])[0]

            if command == const.CMD_CONNECT:
                self.__session_id = res_session_id

            return {
                'status':     res_code in (const.CMD_ACK_OK, const.CMD_ACK_UNAUTH),
                'code':       res_code,
                'session_id': res_session_id,
                'data':       raw[8:] if len(raw) > 8 else b''
            }

        except sock_timeout:
            raise ZKNetworkError(f"Command {command:#06x} timed out")
        except (ZKNetworkError, ZKErrorResponse):
            raise
        except Exception as e:
            raise ZKErrorResponse(f"Command {command:#06x} failed: {e}")

    def _recv_tcp(self, size=1024) -> bytes:
        """Read one complete ZK TCP response."""
        data = b''
        try:
            # First 4 bytes are the payload length (big-endian)
            header = b''
            while len(header) < 4:
                chunk = self.__sock.recv(4 - len(header))
                if not chunk:
                    break
                header += chunk
            if len(header) < 4:
                return data
            payload_len = unpack('>I', header)[0]
            while len(data) < payload_len:
                chunk = self.__sock.recv(payload_len - len(data))
                if not chunk:
                    break
                data += chunk
        except sock_timeout:
            pass
        return data

    def _build_packet(self, command, data=b'') -> bytes:
        if isinstance(data, str):
            data = data.encode(self.encoding)
        elif not isinstance(data, (bytes, bytearray)):
            data = bytes(data)

        # Build header with zero checksum first
        header = pack('<HHHH', command, 0, self.__session_id, self.__reply_id)
        buf    = header + data

        # XOR checksum over 16-bit words
        chksum = 0
        for i in range(0, len(buf) - 1, 2):
            chksum ^= unpack('<H', buf[i:i+2])[0]

        payload = pack('<HHHH', command, chksum, self.__session_id, self.__reply_id) + data

        # TCP: prefix with 4-byte big-endian length; UDP: raw
        return pack('>I', len(payload)) + payload if not self.force_udp else payload

    # ------------------------------------------------------------------ #
    # Public device API                                                    #
    # ------------------------------------------------------------------ #

    def get_time(self) -> datetime:
        resp = self._send_command(const.CMD_GET_TIME)
        if resp.get('status') and len(resp.get('data', b'')) >= 4:
            return self._decode_time(unpack('<I', resp['data'][:4])[0])
        return datetime.now()

    def set_time(self, timestamp: datetime = None) -> bool:
        if timestamp is None:
            timestamp = datetime.now()
        t = ((timestamp.year  - 2000) * 12 * 31 * 24 * 60 * 60 +
             (timestamp.month - 1)    * 31 * 24 * 60 * 60 +
             (timestamp.day   - 1)    * 24 * 60 * 60 +
              timestamp.hour          * 60 * 60 +
              timestamp.minute        * 60 +
              timestamp.second)
        return self._send_command(const.CMD_SET_TIME, pack('<I', t)).get('status', False)

    def get_users(self) -> List[User]:
        users = []
        resp  = self._send_command(const.CMD_DB_RRQ, const.FC_PC_USERS)
        if not resp.get('status'):
            return users
        data = resp.get('data', b'')
        RSZ  = 28
        for i in range(0, len(data) - RSZ + 1, RSZ):
            try:
                uid, priv, pwd_b, name_b, card, grp, tz, uid2 = unpack(
                    '<HB5s24sIHHI', data[i:i+RSZ]
                )
                name = name_b.rstrip(b'\x00').decode(self.encoding, errors='ignore')
                pwd  = pwd_b.rstrip(b'\x00').decode('ascii', errors='ignore')
                users.append(User(uid, name, priv, pwd, grp, uid2, tz))
            except Exception as e:
                logger.debug(f"User parse error at {i}: {e}")
        return users

    def get_attendance(self) -> List[Attendance]:
        """Pull all stored attendance records from device memory."""
        records = []
        resp    = self._send_command(const.CMD_ATTLOG_RRQ)
        if not resp.get('status'):
            return records
        data = resp.get('data', b'')
        # ZK attendance record is 40 bytes; first 24 = user_id string
        RSZ = 40
        for i in range(0, len(data) - 29, RSZ):
            try:
                uid_raw = data[i:i+24].rstrip(b'\x00').decode('ascii', errors='ignore')
                ts_raw  = unpack('<I', data[i+24:i+28])[0]
                status  = data[i+28] if len(data) > i+28 else 0
                punch   = data[i+29] if len(data) > i+29 else 0
                records.append(Attendance(uid_raw, self._decode_time(ts_raw), status, punch))
            except Exception as e:
                logger.debug(f"Attendance parse error at {i}: {e}")
        return records

    def live_capture(self, event_timeout: int = 10) -> Generator[Optional[Attendance], None, None]:
        """
        Stream live attendance events from the device.

        Yields:
            Attendance object when a punch is detected.
            None on timeout (heartbeat tick — caller can check is_running).
            Raises StopIteration / returns when disconnected.
        """
        if not self.__sock or not self.__is_connected:
            return

        saved_timeout = self.__sock.gettimeout()
        self.__sock.settimeout(event_timeout)

        try:
            # Register for attendance log events
            self._send_command(const.CMD_REG_EVENT, pack('<I', const.EF_ATTLOG))
            logger.debug(f"Live capture started on {self.ip}")

            while self.__is_connected:
                try:
                    # Read raw event packet
                    if self.force_udp:
                        raw, _ = self.__sock.recvfrom(4096)
                    else:
                        raw = self._recv_tcp(4096)

                    if not raw or len(raw) < 8:
                        yield None
                        continue

                    # ZK event header: cmd(2) chk(2) session(2) reply(2) then payload
                    evt_code = unpack('<H', raw[0:2])[0]

                    # EF_ATTLOG event carries an extra 8-byte sub-header
                    if evt_code == const.EF_ATTLOG and len(raw) >= 32:
                        payload = raw[8:]         # strip 8-byte ZK header
                        uid_raw = payload[:24].rstrip(b'\x00').decode('ascii', errors='ignore')
                        if len(payload) >= 28:
                            ts_raw = unpack('<I', payload[24:28])[0]
                            status = payload[28] if len(payload) > 28 else 0
                            punch  = payload[29] if len(payload) > 29 else 0
                            dt     = self._decode_time(ts_raw)
                            att    = Attendance(uid_raw, dt, status, punch)
                            logger.info(f"[LIVE] {self.ip} → user={uid_raw} time={dt} status={status} punch={punch}")
                            yield att
                        continue

                    yield None   # heartbeat / other event

                except sock_timeout:
                    yield None   # normal — no punch in this window
                except Exception as e:
                    logger.error(f"Live capture recv error on {self.ip}: {e}")
                    self.__is_connected = False
                    break

        finally:
            try:
                self._send_command(const.CMD_CANCELCAPTURE)
            except Exception:
                pass
            try:
                if self.__sock:
                    self.__sock.settimeout(saved_timeout)
            except Exception:
                pass
            logger.debug(f"Live capture stopped on {self.ip}")

    def clear_attendance(self) -> bool:
        return self._send_command(const.CMD_CLEAR_ATTLOG).get('status', False)

    def enable_device(self) -> bool:
        return self._send_command(const.CMD_ENABLE_CLOCK).get('status', False)

    def disable_device(self) -> bool:
        return self._send_command(const.CMD_STARTVERIFY).get('status', False)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _decode_time(self, t: int) -> datetime:
        try:
            second = t % 60;  t //= 60
            minute = t % 60;  t //= 60
            hour   = t % 24;  t //= 24
            day    = t % 31 + 1;  t //= 31
            month  = t % 12 + 1;  t //= 12
            year   = t + 2000
            return datetime(year, month, day, hour, minute, second)
        except Exception:
            return datetime.now()
