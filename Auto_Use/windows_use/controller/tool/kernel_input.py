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

import time
import logging
import ctypes
from interception import Interception, KeyStroke

logger = logging.getLogger(__name__)

# Interception key flags
KEY_DOWN = 0
KEY_UP = 1

# Modifier scan codes
SCAN_LSHIFT = 0x2A
SCAN_CTRL = 0x1D
SCAN_ALT = 0x38

# Windows API
user32 = ctypes.windll.user32
MAPVK_VK_TO_VSC = 0


def _char_to_scancode(char: str) -> tuple:
    """
    Resolve a character to (scancode, needs_shift, needs_ctrl, needs_alt)
    using the current keyboard layout via Windows API.
    """
    hkl = user32.GetKeyboardLayout(0)
    
    result = user32.VkKeyScanExW(ord(char), hkl)
    
    if result == -1 or result == 0xFFFF:
        logger.warning(f"Character '{char}' not mappable on current keyboard layout")
        return None
    
    vk = result & 0xFF
    shift_state = (result >> 8) & 0xFF
    
    needs_shift = bool(shift_state & 0x01)
    needs_ctrl = bool(shift_state & 0x02)
    needs_alt = bool(shift_state & 0x04)
    
    scancode = user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, hkl)
    
    if scancode == 0:
        logger.warning(f"VK 0x{vk:02X} for '{char}' has no scancode mapping")
        return None
    
    return (scancode, needs_shift, needs_ctrl, needs_alt)


def release_all_inputs():
    """Emergency release all keyboard modifiers and mouse buttons via Interception driver."""
    try:
        ctx = Interception()
        if not ctx.valid:
            return
        
        kb = ctx.keyboard
        mouse = ctx.mouse
        
        # Release all keyboard modifiers
        ctx.send(kb, KeyStroke(code=SCAN_LSHIFT, flags=KEY_UP))
        ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_UP))
        ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
        
        # Release mouse buttons
        from interception import MouseStroke
        ctx.send(mouse, MouseStroke(0, 0x002, 0, 0, 0))  # LEFT_BUTTON_UP
        ctx.send(mouse, MouseStroke(0, 0x008, 0, 0, 0))  # RIGHT_BUTTON_UP
        
        time.sleep(0.05)
        del ctx
        
        logger.info("Emergency release: all inputs released via Interception")
    except Exception as e:
        logger.error(f"Emergency release failed: {e}")


def canvas_input(text: str, interval: float = 0.04, post_wait: float = 0.22, stop_event=None) -> dict:
    """
    Type text into the currently focused location using Interception kernel driver.
    
    Args:
        text: The text to type
        interval: Delay between characters in seconds (default 40ms)
        post_wait: Safety pause after typing completes (default 220ms)
    """
    try:
        ctx = Interception()
        if not ctx.valid:
            logger.error("Interception driver not installed!")
            return {
                "status": "error",
                "action": "canvas_input",
                "message": "Interception driver not installed"
            }
        
        kb = ctx.keyboard
        
        try:
            for char in text:
                # Check stop between each character
                if stop_event and stop_event.is_set():
                    logger.info("canvas_input interrupted by stop_event mid-typing")
                    break
                
                mapping = _char_to_scancode(char)
                
                if mapping is None:
                    logger.warning(f"Skipping unmappable character: '{char}'")
                    continue
                
                scancode, needs_shift, needs_ctrl, needs_alt = mapping
                
                # Per-character try/finally to prevent stuck modifiers
                try:
                    if needs_ctrl:
                        ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_DOWN))
                        time.sleep(0.005)
                    if needs_alt:
                        ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_DOWN))
                        time.sleep(0.005)
                    if needs_shift:
                        ctx.send(kb, KeyStroke(code=SCAN_LSHIFT, flags=KEY_DOWN))
                        time.sleep(0.005)
                    
                    ctx.send(kb, KeyStroke(code=scancode, flags=KEY_DOWN))
                    time.sleep(0.01)
                    ctx.send(kb, KeyStroke(code=scancode, flags=KEY_UP))
                    
                finally:
                    if needs_shift:
                        ctx.send(kb, KeyStroke(code=SCAN_LSHIFT, flags=KEY_UP))
                    if needs_alt:
                        ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
                    if needs_ctrl:
                        ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_UP))
                
                time.sleep(interval)
            
        finally:
            # Blanket safety cleanup - release all modifiers unconditionally
            ctx.send(kb, KeyStroke(code=SCAN_LSHIFT, flags=KEY_UP))
            ctx.send(kb, KeyStroke(code=SCAN_CTRL, flags=KEY_UP))
            ctx.send(kb, KeyStroke(code=SCAN_ALT, flags=KEY_UP))
            time.sleep(0.05)
            del ctx
        
        time.sleep(post_wait)
        
        # If stopped mid-typing, return stopped status
        if stop_event and stop_event.is_set():
            logger.info("Canvas input (Interception): stopped by user mid-typing")
            return {
                "status": "stopped",
                "action": "canvas_input",
                "message": "Stopped by user"
            }
        
        logger.info(f"Canvas input (Interception): typed '{text}' ({len(text)} chars)")
        
        return {
            "status": "success",
            "action": "canvas_input",
            "text": text,
            "message": "verify yourself using visual"
        }
        
    except Exception as e:
        logger.error(f"Error in canvas input (Interception): {str(e)}")
        return {
            "status": "error",
            "action": "canvas_input",
            "message": str(e)
        }
