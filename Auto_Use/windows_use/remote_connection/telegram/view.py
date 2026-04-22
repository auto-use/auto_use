# Copyright 2026 Autouse AI — https://github.com/auto-use/Auto-Use
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# If you build on this project, please keep this header and credit
# Autouse AI (https://github.com/auto-use/Auto-Use) in forks and derivative works.
# A small attribution goes a long way toward a healthy open-source
# community — thank you for contributing.

import threading
import logging
import socket
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

telegram_bp = Blueprint('telegram', __name__)

_bot_instance = None
_bot_thread = None
_bot_username_cache = None

# view.py -> telegram -> remote_connection -> windows_use -> Auto_Use / api_key / api_key.txt
API_KEY_FILE = Path(__file__).parent.parent.parent.parent / "api_key" / "api_key.txt"
PAIR_HTML = Path(__file__).parent / "pair.html"


def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _read_telegram_token():
    if API_KEY_FILE.exists():
        try:
            with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('TELEGRAM_BOT_TOKEN='):
                        _, _, value = line.partition('=')
                        return value.strip() or None
        except Exception:
            pass
    return None


def _save_telegram_token(token):
    API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False
    if API_KEY_FILE.exists():
        with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('TELEGRAM_BOT_TOKEN='):
                    lines.append(f'TELEGRAM_BOT_TOKEN={token}\n')
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f'TELEGRAM_BOT_TOKEN={token}\n')
    with open(API_KEY_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def _fetch_bot_username(token):
    try:
        import urllib.request, json
        resp = urllib.request.urlopen(f'https://api.telegram.org/bot{token}/getMe', timeout=5)
        data = json.loads(resp.read())
        if data.get('ok'):
            return data['result'].get('username', '')
    except Exception:
        pass
    return None


def start_bot():
    global _bot_instance, _bot_thread, _bot_username_cache
    if _bot_thread and _bot_thread.is_alive():
        return
    token = _read_telegram_token()
    if not token:
        return
    _bot_username_cache = _fetch_bot_username(token)
    from .service import TelegramAgentBot
    _bot_instance = TelegramAgentBot(token)
    _bot_thread = threading.Thread(target=_bot_instance.run, daemon=True)
    _bot_thread.start()
    logger.info("Telegram bot started (@%s)", _bot_username_cache)


def stop_bot():
    global _bot_instance, _bot_thread, _bot_username_cache
    if _bot_instance:
        _bot_instance.stop()
    _bot_instance = None
    _bot_thread = None
    _bot_username_cache = None


@telegram_bp.route('/pair')
def pair_page():
    return send_file(PAIR_HTML)


@telegram_bp.route('/api/telegram/save-token', methods=['POST'])
def save_token():
    data = request.get_json()
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'No token provided'}), 400

    username = _fetch_bot_username(token)
    if not username:
        return jsonify({'error': 'Invalid token — check and try again'}), 400

    _save_telegram_token(token)
    stop_bot()
    start_bot()
    return jsonify({'status': 'connected', 'bot_username': username})


@telegram_bp.route('/api/telegram/status')
def telegram_status():
    token = _read_telegram_token()
    if not token:
        return jsonify({'connected': False, 'local_ip': _get_local_ip()})
    return jsonify({
        'connected': True,
        'bot_username': _bot_username_cache,
        'running': _bot_thread is not None and _bot_thread.is_alive(),
        'local_ip': _get_local_ip()
    })


@telegram_bp.route('/api/telegram/disconnect', methods=['POST'])
def disconnect():
    stop_bot()
    _save_telegram_token('')
    return jsonify({'status': 'disconnected'})