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

# Auto_Use/macOS_use/controller/key_combo/service.py
# macOS version — keyboard shortcuts via pynput (Quartz CGEvent under the hood)
# pynput resolves keycodes from the system keyboard layout — no hardcoded table.

import logging
import time
from pynput.keyboard import Controller, Key, KeyCode

logger = logging.getLogger(__name__)

_keyboard = None

def _get_keyboard():
    global _keyboard
    if _keyboard is None:
        _keyboard = Controller()
    return _keyboard

# Name → pynput Key for modifiers and special keys
_SPECIAL_KEYS = {
    "cmd":       Key.cmd, "command": Key.cmd,
    "shift":     Key.shift,
    "option":    Key.alt, "opt": Key.alt,
    "control":   Key.ctrl,
    "return":    Key.enter, "enter": Key.enter,
    "tab":       Key.tab,
    "space":     Key.space,
    "backspace": Key.backspace, "delete": Key.delete,
    "escape":    Key.esc, "esc": Key.esc,
    "up":        Key.up, "down": Key.down,
    "left":      Key.left, "right": Key.right,
    "home":      Key.home, "end":  Key.end,
    "pageup":    Key.page_up, "pagedown": Key.page_down,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}

# Keys that count as modifiers (held down around the final key)
_MODIFIER_NAMES = {"cmd", "command", "shift", "option", "opt", "control"}


def _resolve_key(name: str):
    """Resolve a key name to a pynput Key or KeyCode."""
    if name in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[name]
    if len(name) == 1:
        return KeyCode.from_char(name)
    return None


class KeyComboService:
    """Service for sending keyboard shortcuts via pynput."""

    def __init__(self, stop_event=None):
        self.stop_event = stop_event

    def send(self, shortcut: str) -> dict:
        """
        Send a keyboard shortcut.

        Args:
            shortcut: Keyboard shortcut (e.g., "cmd+c", "f2", "command+shift+s")
                      Max 3 keys combined with "+".

        Returns:
            dict: Result of shortcut execution.
        """
        try:
            if self.stop_event and self.stop_event.is_set():
                return {"status": "stopped", "action": "shortcut_combo",
                        "shortcut": shortcut, "message": "Stopped by user"}

            normalized = shortcut.lower().replace(" ", "")
            parts = normalized.split("+")

            if len(parts) > 3:
                return {
                    "status": "error", "action": "shortcut_combo",
                    "shortcut": shortcut,
                    "message": f"Maximum 3 keys allowed, got {len(parts)}"
                }

            # Split modifiers from final key
            modifiers = []
            final = None
            for p in parts:
                if p in _MODIFIER_NAMES:
                    resolved = _resolve_key(p)
                    if resolved:
                        modifiers.append(resolved)
                else:
                    final = _resolve_key(p)
                    if final is None:
                        return {
                            "status": "error", "action": "shortcut_combo",
                            "shortcut": shortcut,
                            "message": f"Unknown key: '{p}'"
                        }

            # Solo key (e.g. just "escape", "f5")
            if final is None and not modifiers:
                return {
                    "status": "error", "action": "shortcut_combo",
                    "shortcut": shortcut, "message": "No key found in combo"
                }

            if final is None:
                # Single modifier sent alone — treat last as the key
                final = modifiers.pop()

            # Press modifiers down, tap final key, release modifiers
            kb = _get_keyboard()
            for m in modifiers:
                kb.press(m)
                time.sleep(0.02)

            kb.press(final)
            time.sleep(0.05)
            kb.release(final)

            for m in reversed(modifiers):
                kb.release(m)
                time.sleep(0.02)

            logger.info(f"Sent shortcut: {shortcut}")

            return {
                "status": "success", "action": "shortcut_combo",
                "shortcut": shortcut
            }

        except Exception as e:
            logger.error(f"Error sending shortcut {shortcut}: {str(e)}")
            return {
                "status": "error", "action": "shortcut_combo",
                "shortcut": shortcut, "message": str(e)
            }