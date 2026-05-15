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

"""Telegram remote-connection setup driver (macOS, guided mode).

Opens Safari, navigates to web.telegram.org, then lets the user log in
manually. Progress is paced by a small always-on-top banner that streams
status text and has a Next button. The script blocks on user clicks via
banner.wait_for_next() — the user does the actual login (phone, country,
OTP) themselves; we just get them to the right page.
"""
import logging
import os
import time

from Auto_Use.macOS_use.controller.tool.open_app import open_app
from Auto_Use.macOS_use.tree.element import UIElementScanner, ELEMENT_CONFIG
from Auto_Use.macOS_use.controller.service import ControllerService
from Auto_Use.macOS_use.controller.key_combo.service import KeyComboService
from Auto_Use.macOS_use.remote_connection.telegram.banner import StatusBanner
from Auto_Use.macOS_use.remote_connection.telegram.service import (
    _API_KEY_FILE, _set_key_in_file,
)

logger = logging.getLogger(__name__)

TELEGRAM_WEB_URL = "web.telegram.org"
STEP_DELAY_SEC = 2


def _find_address_bar(mapping: dict) -> str | None:
    """Return the index of Safari's smart-search field, or None if not found."""
    for idx, info in mapping.items():
        if info.get("name") == "smart search field" and info.get("type") == "TextField":
            return idx
    return None


def _open_telegram_in_safari(banner) -> bool:
    """Launch Safari and navigate it to web.telegram.org.

    Streams sub-step status to the banner so the user can see what's happening
    while Safari takes focus. Returns False on any failure.
    """
    banner.update("Please wait — confirming Safari is open…")
    if not open_app("Safari"):
        logger.error("setup.py: failed to launch Safari")
        return False
    # open_app itself sleeps ~1 s after launching and then runs an AppleScript
    # window-move, so the address bar isn't reliably there yet. One more
    # second is enough for the smart-search field to settle before we scan.
    time.sleep(1)

    scanner = UIElementScanner(ELEMENT_CONFIG)
    scanner.scan_elements()
    mapping = scanner.get_elements_mapping()
    time.sleep(STEP_DELAY_SEC)

    address_bar_index = _find_address_bar(mapping)
    if address_bar_index is None:
        logger.error("setup.py: Safari address bar not found in scan")
        return False

    banner.update("Safari detected. Writing the URL for you, please wait…")

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
    """
    banner = StatusBanner()
    banner.show()
    try:
        banner.update("Let's get you set up with Telegram. Please click Next.")
        banner.wait_for_next()

        if not _open_telegram_in_safari(banner):
            banner.update("Failed to open Telegram. Close this banner and try again.")
            banner.wait_for_next(timeout=15)
            return False

        banner.update("Please log in to Telegram, then click Next")
        banner.wait_for_next()

        banner.update(
            "Now search for @BotFather in Telegram and open the chat. "
            "Click Next when you're there."
        )
        banner.wait_for_next()

        banner.update("How do you want to set up the bot?")
        choice = banner.wait_for_choice("Fresh setup", "Token already generated")

        if choice == "left":
            banner.update(
                "In @BotFather, send these one at a time:  /newbot  →  AutoUse  →  "
                "a unique bot name. BotFather will reply with your token. "
                "Click Next when you have it."
            )
            banner.wait_for_next()

        banner.update("Paste your BotFather token below and click Save.")
        token = banner.wait_for_input(save_label="Save")
        if not token:
            return False  # Cocoa-unavailable fallback; banner never appeared

        _set_key_in_file(_API_KEY_FILE, "TELEGRAM_BOT_TOKEN", token.strip())

        banner.update("Saved. Restarting AutoUse to start the bot…")
        # Give the message time to stream out + a beat for the user to read
        # it, then hard-exit the whole process. The user's next `python
        # app.py` boot picks up the fresh TELEGRAM_BOT_TOKEN and the bot
        # comes online with the saved owner chat. os._exit skips atexit /
        # finally cleanup, which is what we want — Cocoa will tear down
        # the banner + windows as the process dies.
        time.sleep(3)
        banner.close()
        os._exit(0)
    finally:
        banner.close()
