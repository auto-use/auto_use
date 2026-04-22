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

import logging
import time
import keyboard
from interception import Interception, KeyStroke

# Configure logger
logger = logging.getLogger(__name__)

# Interception driver constants for UAC handling
KEY_DOWN = 0
KEY_UP = 1
SCAN_ALT = 0x38
SCAN_Y = 0x15
SCAN_N = 0x31
SCAN_CTRL = 0x1D

class KeyComboService:
    """Service for sending keyboard shortcuts using the keyboard library.
    UAC shortcuts (alt+y, alt+n) are routed through Interception kernel driver
    to bypass the secure desktop where normal input is blocked."""
    
    def __init__(self, stop_event=None):
        self.stop_event = stop_event
    
    def _uac_accept(self) -> dict:
        """Accept UAC prompt by sending Alt+Y via Interception kernel driver"""
        try:
            if self.stop_event and self.stop_event.is_set():
                return {"status": "stopped", "action": "shortcut_combo", "shortcut": "alt+y", "message": "Stopped by user"}
            
            logger.info("UAC - sending Alt+Y via Interception driver")
            
            ctx = Interception()
            if not ctx.valid:
                return {
                    "status": "error",
                    "action": "shortcut_combo",
                    "shortcut": "alt+y",
                    "message": "Interception driver not installed"
                }
            
            kb = ctx.keyboard
            
            try:
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_DOWN))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_Y, flags=KEY_DOWN))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_Y, flags=KEY_UP))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
                time.sleep(0.05)
            finally:
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
                ctx.send(kb, KeyStroke(code=SCAN_Y, flags=KEY_UP))
                ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_UP))
                time.sleep(0.1)
                del ctx
            
            logger.info("UAC accepted via Interception driver")
            return {"status": "success", "action": "shortcut_combo", "shortcut": "alt+y", "message": "UAC prompt accepted via Interception driver"}
            
        except Exception as e:
            logger.error(f"Error in UAC accept: {str(e)}")
            return {"status": "error", "action": "shortcut_combo", "shortcut": "alt+y", "message": str(e)}
    
    def _uac_decline(self) -> dict:
        """Decline UAC prompt by sending Alt+N via Interception kernel driver"""
        try:
            if self.stop_event and self.stop_event.is_set():
                return {"status": "stopped", "action": "shortcut_combo", "shortcut": "alt+n", "message": "Stopped by user"}
            
            logger.info("UAC - sending Alt+N via Interception driver")
            
            ctx = Interception()
            if not ctx.valid:
                return {
                    "status": "error",
                    "action": "shortcut_combo",
                    "shortcut": "alt+n",
                    "message": "Interception driver not installed"
                }
            
            kb = ctx.keyboard
            
            try:
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_DOWN))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_N, flags=KEY_DOWN))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_N, flags=KEY_UP))
                time.sleep(0.05)
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
                time.sleep(0.05)
            finally:
                ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
                ctx.send(kb, KeyStroke(code=SCAN_N, flags=KEY_UP))
                ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_UP))
                time.sleep(0.1)
                del ctx
            
            logger.info("UAC declined via Interception driver")
            return {"status": "success", "action": "shortcut_combo", "shortcut": "alt+n", "message": "UAC prompt declined via Interception driver"}
            
        except Exception as e:
            logger.error(f"Error in UAC decline: {str(e)}")
            return {"status": "error", "action": "shortcut_combo", "shortcut": "alt+n", "message": str(e)}
    
    def send(self, shortcut: str) -> dict:
        """
        Send a keyboard shortcut.
        
        UAC shortcuts (alt+y, alt+n) route to Interception kernel driver.
        All others use the keyboard library.
        
        Args:
            shortcut (str): Keyboard shortcut (e.g., "ctrl+c", "f2", "ctrl+shift+s")
                           Max 3 keys combined
        
        Returns:
            dict: Result of shortcut execution
        """
        try:
            # Check for UAC shortcuts — route to kernel driver
            normalized = shortcut.lower().replace(" ", "")
            if normalized == "alt+y":
                return self._uac_accept()
            if normalized == "alt+n":
                return self._uac_decline()
            
            # Normal shortcuts — keyboard library
            keys = normalized.split("+")
            if len(keys) > 3:
                return {
                    "status": "error",
                    "action": "shortcut_combo",
                    "shortcut": shortcut,
                    "message": f"Maximum 3 keys allowed, got {len(keys)}"
                }
            
            keyboard.send(shortcut)
            
            logger.info(f"Sent shortcut: {shortcut}")
            
            return {
                "status": "success",
                "action": "shortcut_combo",
                "shortcut": shortcut
            }
            
        except Exception as e:
            logger.error(f"Error sending shortcut {shortcut}: {str(e)}")
            return {
                "status": "error",
                "action": "shortcut_combo",
                "shortcut": shortcut,
                "message": str(e)
            }