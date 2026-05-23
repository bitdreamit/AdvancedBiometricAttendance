# src/core/agent_api.py
"""
Lightweight HTTP status API for the offline agent.

Runs alongside the main application on localhost:5000 (configurable).
Allows the Laravel server to:
  GET  /status          — agent health, device connections, queue depth
  POST /sync-now        — trigger an immediate sync cycle
  GET  /commands        — poll for pending commands from Laravel (enroll, clear-log)

Start with:
    from src.core.agent_api import AgentAPI
    api = AgentAPI(sync_engine, device_manager, db)
    api.start()          # non-blocking, background thread

Disabled by default — enable in config:
    "agent_api": { "enabled": true, "port": 5000, "host": "127.0.0.1" }

Security: bind to 127.0.0.1 (localhost only) by default.
For remote access, bind to 0.0.0.0 and protect with a reverse proxy + TLS.
"""
import json
import logging
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

logger = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    """Minimal HTTP request handler — no framework dependency."""

    api = None  # set by AgentAPI.start()

    def log_message(self, fmt, *args):
        logger.debug(f"AgentAPI: {fmt % args}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self) -> bool:
        token = self.api.api_token
        if not token:
            return True  # no auth configured — localhost only, OK
        auth = self.headers.get('Authorization', '')
        return auth == f'Bearer {token}'

    def do_GET(self):
        if not self._auth_ok():
            self._send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/status':
            self._send_json(self.api.get_status())

        elif self.path == '/commands':
            # Poll Laravel for pending commands
            cmds = self.api.poll_commands()
            self._send_json({'commands': cmds})

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        if not self._auth_ok():
            self._send_json({'error': 'Unauthorized'}, 401)
            return

        if self.path == '/sync-now':
            logger.info("AgentAPI: sync-now triggered remotely")
            result = self.api.sync_engine.sync_now()
            self._send_json({'status': 'ok', 'result': result})

        else:
            self._send_json({'error': 'Not found'}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.end_headers()


class AgentAPI:
    """
    Embeds a tiny HTTP server into the agent process.
    Runs in a daemon thread — stops when the main process exits.
    """

    def __init__(self, sync_engine, device_manager, db,
                 host: str = '127.0.0.1', port: int = 5000,
                 api_token: str = None):
        self.sync_engine    = sync_engine
        self.device_manager = device_manager
        self.db             = db
        self.host           = host
        self.port           = port
        self.api_token      = api_token
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        _Handler.api = self

        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name='AgentAPI'
        )
        self._thread.start()
        logger.info(f"AgentAPI listening on http://{self.host}:{self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()
            logger.info("AgentAPI stopped")

    def get_status(self) -> dict:
        """Return full agent status snapshot."""
        stats   = self.db.get_attendance_stats(self.sync_engine.tenant_id)
        devices = []
        for sn, dev in self.device_manager.devices.items():
            devices.append({
                'serial_number': sn,
                'ip':            dev.ip,
                'connected':     dev.is_connected(),
            })
        return {
            'agent_version': '2.2',
            'timestamp':     datetime.now().isoformat(),
            'tenant_id':     self.sync_engine.tenant_id,
            'devices':       devices,
            'queue': {
                'pending':   stats.get('pending',   0),
                'synced':    stats.get('synced',    0),
                'error':     stats.get('error',     0),
                'duplicate': stats.get('duplicate', 0),
            },
            'server_url':    self.sync_engine.server_url or 'not configured',
        }

    def poll_commands(self) -> list:
        """
        Ask Laravel for any pending commands (enroll user, clear log, etc.).
        Laravel endpoint: GET {server_url}/api/biometric/agent-commands
        Response: { "commands": [{"type": "enroll_user", "data": {...}}, ...] }
        """
        if not self.sync_engine._server_configured():
            return []
        try:
            resp = self.sync_engine._get(
                self.sync_engine._url('agent-commands')
            )
            if resp:
                cmds = resp.json().get('commands', [])
                if cmds:
                    self._execute_commands(cmds)
                return cmds
        except Exception as e:
            logger.debug(f"poll_commands error: {e}")
        return []

    def _execute_commands(self, commands: list):
        """Execute commands received from Laravel."""
        for cmd in commands:
            cmd_type = cmd.get('type')
            data     = cmd.get('data', {})

            if cmd_type == 'sync_now':
                logger.info("Command: sync_now")
                self.sync_engine.sync_now()

            elif cmd_type == 'clear_device_log':
                sn = data.get('device_sn')
                if sn and sn in self.device_manager.devices:
                    dev = self.device_manager.devices[sn]
                    if dev.is_connected():
                        ok = dev.clear_attendance_log()
                        logger.info(f"Command: clear_device_log {sn} → {'OK' if ok else 'FAILED'}")

            elif cmd_type == 'enroll_user':
                # Push a user record to a specific device
                sn  = data.get('device_sn')
                emp = data.get('employee')
                if sn and emp and sn in self.device_manager.devices:
                    dev = self.device_manager.devices[sn]
                    if dev.is_connected():
                        self.sync_engine._push_user_to_device(dev, emp)
                        logger.info(f"Command: enroll_user {emp.get('employee_code')} on {sn}")

            else:
                logger.warning(f"Unknown command type: {cmd_type}")
