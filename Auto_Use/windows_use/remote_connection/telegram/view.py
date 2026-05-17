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

"""Flask Blueprint for the Windows Telegram surface.

Mirror of the macOS view.py, adapted so app.py's single
`from ...view import telegram_bp, start_bot` works on Windows. Routes:

  GET  /api/telegram/status       → {connected, bot_username?}
  POST /api/telegram/connect      → kicks off the guided walkthrough (Edge)
  POST /api/telegram/disconnect   → clears the persisted token

All token lookups read ONLY from api_key.txt. .env is intentionally not
consulted — the bot treats api_key.txt as its single source of truth.
"""
import json
import logging
import threading
import urllib.request
from pathlib import Path

from flask import Blueprint, jsonify

# Re-export start_bot so app.py's
#   from Auto_Use.windows_use.remote_connection.telegram.view import telegram_bp, start_bot
# works from a single import line, matching app.py:921.
from .service import start_bot  # noqa: F401

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram_windows", __name__)

# view.py → telegram → remote_connection → windows_use → Auto_Use → repo root
_API_KEY_FILE = (
    Path(__file__).resolve().parents[4] / "Auto_Use" / "api_key" / "api_key.txt"
)

_bot_username_cache: str | None = None


def _read_token() -> str | None:
    """Pull TELEGRAM_BOT_TOKEN out of api_key.txt. Returns None if missing or
    empty. Does NOT consult .env or env vars on purpose."""
    if not _API_KEY_FILE.exists():
        return None
    try:
        with open(_API_KEY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("TELEGRAM_BOT_TOKEN="):
                    val = stripped.partition("=")[2].strip()
                    return val or None
    except Exception:
        logger.warning("could not read %s", _API_KEY_FILE)
    return None


def _set_token(value: str) -> None:
    """Write/clear TELEGRAM_BOT_TOKEN= in api_key.txt, preserving every other
    line (incl. empty-value placeholders the AutoUse UI relies on)."""
    lines = []
    found = False
    if _API_KEY_FILE.exists():
        try:
            with open(_API_KEY_FILE, "r", encoding="utf-8") as f:
                for raw in f:
                    if raw.strip().startswith("TELEGRAM_BOT_TOKEN="):
                        lines.append(f"TELEGRAM_BOT_TOKEN={value}\n")
                        found = True
                    else:
                        lines.append(raw if raw.endswith("\n") else raw + "\n")
        except Exception:
            logger.warning("could not read %s while updating token", _API_KEY_FILE)
            return
    if not found:
        lines.append(f"TELEGRAM_BOT_TOKEN={value}\n")
    try:
        _API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_API_KEY_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        logger.warning("could not write %s", _API_KEY_FILE)


def _fetch_bot_username(token: str) -> str | None:
    """One-shot call to Telegram's getMe — used by /status so the panel can
    show '@your_bot' instead of just 'connected'."""
    try:
        resp = urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getMe", timeout=5
        )
        data = json.loads(resp.read())
        if data.get("ok"):
            return data["result"].get("username", "") or None
    except Exception:
        pass
    return None


# ── routes ──────────────────────────────────────────────────────────────────

@telegram_bp.route("/api/telegram/status", methods=["GET"])
def telegram_status():
    """Frontend uses this to decide which Remote Connection panel state to
    show. If a token is present in api_key.txt → 'connected', and the panel
    flips to the @bot_username + Disconnect view (Connect button is hidden).
    Cached so we don't hit Telegram's API on every page load."""
    global _bot_username_cache
    token = _read_token()
    if not token:
        _bot_username_cache = None
        return jsonify({"connected": False})
    if _bot_username_cache is None:
        _bot_username_cache = _fetch_bot_username(token) or ""
    return jsonify({
        "connected": True,
        "bot_username": _bot_username_cache,
    })


@telegram_bp.route("/api/telegram/connect", methods=["POST"])
def telegram_connect():
    """Kick off the guided walkthrough (Edge → web.telegram.org → user logs
    in manually, paced by the floating banner). Returns immediately; the real
    work runs on a daemon thread since it blocks on user clicks."""
    try:
        from Auto_Use.windows_use.remote_connection.telegram.setup import (
            run as run_telegram_setup,
        )
        threading.Thread(target=run_telegram_setup, daemon=True).start()
        return jsonify({"status": "started"})
    except Exception as e:
        logger.exception("telegram_connect failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@telegram_bp.route("/api/telegram/disconnect", methods=["POST"])
def telegram_disconnect():
    """Clear the persisted token + the cached @bot_username. The polling
    thread already running keeps polling until the next app restart (soft
    disconnect) — clean shutdown of the bot loop is a future enhancement."""
    global _bot_username_cache
    _set_token("")
    _bot_username_cache = None
    return jsonify({"status": "disconnected"})
