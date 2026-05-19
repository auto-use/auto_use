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

"""Telegram remote-connection setup driver (Windows, guided mode).

Opens Microsoft Edge, navigates to web.telegram.org, then lets the user log
in manually. Progress is paced by a small always-on-top banner that streams
status text and has a Next button. The script blocks on user clicks via
banner.wait_for_next() — the user does the actual login (phone, country,
OTP) themselves; we just get them to the right page.
"""
import logging
import os
import threading
import time

from Auto_Use.windows_use.controller.tool.open_app import open_on_windows
from Auto_Use.windows_use.tree.element import UIElementScanner, ELEMENT_CONFIG
from Auto_Use.windows_use.controller.service import ControllerService
from Auto_Use.windows_use.controller.key_combo.service import KeyComboService
from Auto_Use.windows_use.remote_connection.telegram.banner import StatusBanner
from Auto_Use.windows_use.remote_connection.telegram.service import (
    _API_KEY_FILE, _set_key_in_file,
)

logger = logging.getLogger(__name__)

TELEGRAM_WEB_URL = "web.telegram.org"
STEP_DELAY_SEC = 2

# Singleton guard — /api/telegram/connect spawns a fresh daemon thread on
# every POST, so a rapid double-click or polling-induced re-fire would
# otherwise launch parallel banner wizards. We let the redundant calls
# return immediately while the first one runs to completion.
_SETUP_LOCK = threading.Lock()
_SETUP_ACTIVE = False

# Edge candidates tried in order — `open_on_windows` does fuzzy matching, but
# different Windows installs surface Edge under slightly different Start-Menu
# entries (PWA shortcut vs. "Microsoft Edge.lnk" vs. plain `msedge.exe` on
# PATH). Try the cleanest one first; fall back to broader strings.
EDGE_NAME_CANDIDATES = ("msedge", "Microsoft Edge", "edge")


def _find_address_bar(mapping: dict) -> str | None:
    """Return the index of Edge's address bar, or None if not found.

    On Edge the address bar surfaces in the UIA tree as
    `name="Address and search bar", type="Edit"` — confirmed from a live
    scan saved at debug/element/ui_elements_1778913911.txt:8.
    """
    for idx, info in mapping.items():
        if info.get("name") == "Address and search bar" and info.get("type") == "Edit":
            return idx
    return None


def _launch_edge() -> bool:
    """Try the Edge name variants in order; return True on the first success."""
    for name in EDGE_NAME_CANDIDATES:
        try:
            if open_on_windows(name):
                return True
        except Exception:
            logger.warning("open_on_windows(%r) raised", name, exc_info=True)
    return False


def _open_telegram_in_edge(banner) -> bool:
    """Launch Edge and navigate it to web.telegram.org.

    Streams sub-step status to the banner so the user can see what's happening
    while Edge takes focus. Returns False on any failure.
    """
    banner.update("Please wait — confirming Edge is open…")
    if not _launch_edge():
        logger.error("setup.py: failed to launch Microsoft Edge")
        return False
    # open_on_windows already sleeps a moment after launching, but the
    # address bar isn't reliably populated in the UIA tree immediately —
    # give Edge another beat to settle before we scan.
    time.sleep(1)

    scanner = UIElementScanner(ELEMENT_CONFIG)
    scanner.scan_elements()
    mapping = scanner.get_elements_mapping()
    time.sleep(STEP_DELAY_SEC)

    address_bar_index = _find_address_bar(mapping)
    if address_bar_index is None:
        logger.error("setup.py: Edge address bar not found in scan")
        return False

    banner.update("Edge detected. Writing the URL for you, please wait…")

    controller = ControllerService()
    controller.set_elements(mapping, scanner.application_name)
    key_combo = KeyComboService()

    controller.click(address_bar_index)
    time.sleep(STEP_DELAY_SEC)

    controller.canvas_input(TELEGRAM_WEB_URL)
    time.sleep(STEP_DELAY_SEC)

    key_combo.send("return")
    return True


def run(country_code: str = "", phone: str = "") -> bool:
    """Guided Telegram-Web pairing.

    Shows a banner, waits for the user to click Next, opens Telegram Web,
    waits for the user to log in manually + click Next, then closes.

    country_code and phone are accepted but ignored — kept only so the
    pre-existing /api/telegram/connect callsite signature still works.

    Idempotent under concurrent calls: if a wizard is already running,
    redundant invocations return False immediately so we don't end up
    with N parallel banners in the taskbar.
    """
    global _SETUP_ACTIVE
    with _SETUP_LOCK:
        if _SETUP_ACTIVE:
            logger.info(
                "setup.run: wizard already running — ignoring duplicate Connect"
            )
            return False
        _SETUP_ACTIVE = True

    banner = StatusBanner()
    banner.show()
    try:
        banner.update("Let's get you set up with Telegram. Please click Next.")
        if not banner.wait_for_next():
            return False

        if not _open_telegram_in_edge(banner):
            banner.update("Failed to open Telegram. Close this banner and try again.")
            banner.wait_for_next(timeout=15)
            return False

        banner.update("Please log in to Telegram, then click Next")
        if not banner.wait_for_next():
            return False

        banner.update(
            "Now search for @BotFather in Telegram and open the chat. "
            "Click Next when you're there."
        )
        if not banner.wait_for_next():
            return False

        banner.update("How do you want to set up the bot?")
        choice = banner.wait_for_choice("Fresh setup", "Token already generated")

        if choice == "left":
            banner.update(
                "In @BotFather, send these one at a time:  /newbot  →  AutoUse  →  "
                "a unique bot name. BotFather will reply with your token. "
                "Click Next when you have it."
            )
            if not banner.wait_for_next():
                return False

        banner.update("Paste your BotFather token below and click Save.")
        token = banner.wait_for_input(save_label="Save")
        if not token:
            return False  # banner never appeared or user closed it

        _set_key_in_file(_API_KEY_FILE, "TELEGRAM_BOT_TOKEN", token.strip())

        banner.update("Saved. Restarting AutoUse to start the bot…")
        # Give the message time to stream out + a beat for the user to read
        # it, then hard-exit the whole process. The user's next `python
        # app.py` boot picks up the fresh TELEGRAM_BOT_TOKEN and the bot
        # comes online with the saved owner chat. os._exit skips atexit /
        # finally cleanup, which is what we want — the tk loop will be torn
        # down as the process dies.
        time.sleep(3)
        banner.close()
        os._exit(0)
    finally:
        banner.close()
        with _SETUP_LOCK:
            _SETUP_ACTIVE = False
