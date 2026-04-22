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
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pywinauto")
import win32api
import win32con
import pyautogui
from interception import Interception, MouseStroke
from PIL import ImageGrab
import numpy as np
from .tool.kernel_input import release_all_inputs as kernel_release

# Interception mouse constants for UIPI-protected windows
# Note: Interception driver uses different constants than win32api
INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN = 0x001
INTERCEPTION_MOUSE_LEFT_BUTTON_UP = 0x002
INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN = 0x004
INTERCEPTION_MOUSE_RIGHT_BUTTON_UP = 0x008
INTERCEPTION_MOUSE_MOVE_RELATIVE = 0x000
INTERCEPTION_MOUSE_MOVE_ABSOLUTE = 0x001
INTERCEPTION_MOUSE_VIRTUAL_DESKTOP = 0x002

# Apps where pyautogui is blocked (UIPI-protected) — routed to kernel canvas_input
KERNEL_INPUT_APPS = ["Windows Security"]

# Configure pyautogui for instant movement
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

# Configure logger
logger = logging.getLogger(__name__)

# Legacy apps that need slow character-by-character typing
SLOW_TYPING_APPS = [
    "notepad",
    "cmd",
    "powershell",
    "command prompt",
    # Add more legacy apps as discovered
]

class ControllerService:
    def __init__(self, stop_event=None):
        """Initialize the Controller Service"""
        self.elements_mapping = {}  # Will store {index: element_info}
        self.application_name = ""  # Current application name for typing mode detection
        self.stop_event = stop_event
    
    def release_all_inputs(self):
        """Emergency release all hardware inputs (keyboard + mouse) via both Interception and pyautogui."""
        kernel_release()
        try:
            for key in ['shift', 'ctrl', 'alt', 'shiftleft', 'shiftright', 'ctrlleft', 'ctrlright', 'altleft', 'altright']:
                pyautogui.keyUp(key)
            pyautogui.mouseUp(button='left')
            pyautogui.mouseUp(button='right')
            logger.info("Emergency release: all inputs released via pyautogui")
        except Exception as e:
            logger.error(f"pyautogui emergency release failed: {e}")
    
    def _move_mouse_smoothly(self, target_x, target_y):
        """Move mouse smoothly to target position"""
        current_x, current_y = win32api.GetCursorPos()
        
        # Ultra-fast animation with 10 steps
        steps = 10
        for i in range(steps + 1):
            progress = i / steps
            x = int(current_x + (target_x - current_x) * progress)
            y = int(current_y + (target_y - current_y) * progress)
            win32api.SetCursorPos((x, y))
            time.sleep(0.001)  # 1ms between steps

    def _get_click_coords_for_element(self, element_info):
        """
        Determine optimal click coordinates based on element visibility.
        Full elements: pixel centroid on full rect (avoids dead space).
        Partial elements: pixel centroid on visible_rect + adaptive safety clamp
        (keeps click away from clipping edges while guaranteeing it stays inside).
        
        Args:
            element_info: Dictionary containing element, rect, visible_rect, visibility
            
        Returns:
            tuple: (x, y) absolute screen coordinates for optimal click
        """
        visibility = element_info.get('visibility', 'full')
        
        if visibility.startswith('partial'):
            # Use visible portion for analysis
            rect = element_info.get('visible_rect') or element_info['rect']
            
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            # Pixel centroid: finds content, avoids dead space
            centroid_x, centroid_y = self._find_click_point(rect)
            
            # Geometric center: safest point, farthest from all edges
            center_x = rect.left + width // 2
            center_y = rect.top + height // 2
            
            # Blend 50/50: content-aware but edge-safe
            click_x = int(0.5 * center_x + 0.5 * centroid_x)
            click_y = int(0.5 * center_y + 0.5 * centroid_y)
            
            # Adaptive safety margin: min(10px, 25% of dimension)
            margin_x = min(10, width // 4)
            margin_y = min(10, height // 4)
            
            # Calculate safe bounds (always inside visible_rect)
            safe_left = rect.left + margin_x
            safe_right = rect.right - 1 - margin_x
            safe_top = rect.top + margin_y
            safe_bottom = rect.bottom - 1 - margin_y
            
            # If element too small for margin, collapse to center
            if safe_left > safe_right:
                safe_left = safe_right = rect.left + width // 2
            if safe_top > safe_bottom:
                safe_top = safe_bottom = rect.top + height // 2
            
            # Clamp into safe zone
            click_x = max(safe_left, min(click_x, safe_right))
            click_y = max(safe_top, min(click_y, safe_bottom))
            
            return (click_x, click_y)
        else:
            # Full visibility - pixel centroid on full rect
            rect = element_info['rect']
            return self._find_click_point(rect)

    def _find_click_point(self, rect):
        """
        Analyze element pixels to find optimal click point.
        Uses mode (most common color) as background, finds content cluster centroid.
        Works for both normal and Interception-based clicks.
        
        Args:
            rect: Element rectangle with left, top, right, bottom
            
        Returns:
            tuple: (x, y) absolute screen coordinates for optimal click
        """
        try:
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            # Too small - just use center
            if width < 5 or height < 5:
                return (rect.left + width // 2, rect.top + height // 2)
            
            # Capture element region from screen
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            pixels = np.array(img)
            
            # Convert to grayscale for faster processing
            if len(pixels.shape) == 3:
                gray = np.mean(pixels, axis=2).astype(np.uint8)
            else:
                gray = pixels
            
            # Find mode (most common color = background)
            flat = gray.flatten()
            counts = np.bincount(flat, minlength=256)
            background_color = np.argmax(counts)
            
            # Create mask of non-background pixels (with tolerance)
            tolerance = 15
            mask = np.abs(gray.astype(np.int16) - background_color) > tolerance
            
            # If mask is empty or nearly full, use center
            mask_ratio = np.sum(mask) / mask.size
            if mask_ratio < 0.01 or mask_ratio > 0.95:
                return (rect.left + width // 2, rect.top + height // 2)
            
            # Find coordinates of content pixels
            y_coords, x_coords = np.where(mask)
            
            if len(x_coords) == 0:
                return (rect.left + width // 2, rect.top + height // 2)
            
            # Calculate centroid of content
            centroid_x = int(np.mean(x_coords))
            centroid_y = int(np.mean(y_coords))
            
            # Convert to absolute screen coordinates
            abs_x = rect.left + centroid_x
            abs_y = rect.top + centroid_y
            
            return (abs_x, abs_y)
            
        except Exception as e:
            logger.warning(f"Smart click detection failed: {str(e)}, using center")
            # Fallback to center
            center_x = rect.left + (rect.right - rect.left) // 2
            center_y = rect.top + (rect.bottom - rect.top) // 2
            return (center_x, center_y)

    def _interception_mouse_click(self, target_x, target_y, click_type="left"):
        """
        Perform mouse click using Interception driver for UIPI-protected windows.
        
        Args:
            target_x: X coordinate to click
            target_y: Y coordinate to click
            click_type: "left", "right", or "double"
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.stop_event and self.stop_event.is_set():
                logger.info("Interception mouse click skipped — stop_event set")
                return False
            
            logger.info(f"🔧 Using Interception for {click_type} click at ({target_x}, {target_y})")
            
            ctx = Interception()
            if not ctx.valid:
                logger.error("Interception driver not installed!")
                return False
            
            mouse = ctx.mouse
            
            try:
                # Get virtual screen dimensions
                v_x = win32api.GetSystemMetrics(76)
                v_y = win32api.GetSystemMetrics(77)
                v_width = win32api.GetSystemMetrics(78)
                v_height = win32api.GetSystemMetrics(79)
                
                # Get primary monitor dimensions
                p_width = win32api.GetSystemMetrics(0)
                p_height = win32api.GetSystemMetrics(1)

                # Determine mapping strategy
                # If target is on primary monitor, map to primary monitor (0-65535 = Primary)
                # This fixes the issue where driver maps 0-65535 to primary but we calculated for virtual
                if 0 <= target_x < p_width and 0 <= target_y < p_height:
                    use_virtual_flag = False
                    abs_x = int((target_x / p_width) * 65535)
                    abs_y = int((target_y / p_height) * 65535)
                else:
                    # Target is on secondary monitor, must use virtual desktop mapping
                    use_virtual_flag = True
                    abs_x = int(((target_x - v_x) / v_width) * 65535)
                    abs_y = int(((target_y - v_y) / v_height) * 65535)

                # Step 1: Move mouse to position (absolute)
                # MouseStroke signature: (flags, button_flags, button_data, x, y)
                # Found via debug inspection: (flags: 'int', button_flags: 'int', button_data: 'int', x: 'int', y: 'int')
                
                flags = INTERCEPTION_MOUSE_MOVE_ABSOLUTE
                if use_virtual_flag:
                    flags |= INTERCEPTION_MOUSE_VIRTUAL_DESKTOP
                    
                # Arg 1: flags (Movement)
                # Arg 2: button_flags (Clicking)
                # Arg 3: button_data (Rolling)
                ctx.send(mouse, MouseStroke(flags, 0, 0, abs_x, abs_y))
                time.sleep(0.05)
                
                # Step 2: Click at current position (no movement, x=0, y=0)
                if click_type == "left":
                    # flags=0 (Relative/Keep), button_flags=LeftDown
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN, 0, 0, 0))
                    time.sleep(0.05)
                    # flags=0, button_flags=LeftUp
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_UP, 0, 0, 0))
                    
                elif click_type == "right":
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN, 0, 0, 0))
                    time.sleep(0.05)
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_RIGHT_BUTTON_UP, 0, 0, 0))
                    
                elif click_type == "double":
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN, 0, 0, 0))
                    time.sleep(0.05)
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_UP, 0, 0, 0))
                    time.sleep(0.1)
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN, 0, 0, 0))
                    time.sleep(0.05)
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_UP, 0, 0, 0))
                
                time.sleep(0.05)
                
            finally:
                # Only release buttons that were actually pressed
                if click_type == "left":
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_LEFT_BUTTON_UP, 0, 0, 0))
                elif click_type == "right":
                    ctx.send(mouse, MouseStroke(0, INTERCEPTION_MOUSE_RIGHT_BUTTON_UP, 0, 0, 0))
                # Remove the unconditional RIGHT_BUTTON_UP
                time.sleep(0.1)
                del ctx
            
            logger.info(f"✅ Interception {click_type} click successful")
            return True
            
        except Exception as e:
            logger.error(f"❌ Interception mouse click failed: {str(e)}")
            return False
        
    def _escape_for_type_keys(self, text):
        """
        Escape special characters for pywinauto's type_keys method.
        
        pywinauto interprets these characters as control sequences:
        - ( ) for grouping
        - ^ for Ctrl
        - + for Shift
        - % for Alt
        - ~ for Enter
        - { } for special keys
        
        This method wraps them in curly braces to type them literally.
        
        Args:
            text (str): The text to escape
            
        Returns:
            str: Escaped text safe for type_keys
        """
        special_chars = {
            '(': '{(}',
            ')': '{)}',
            '{': '{{}',
            '}': '{}}',
            '^': '{^}',
            '+': '{+}',
            '%': '{%}',
            '~': '{~}',
        }
        result = ''
        for char in text:
            result += special_chars.get(char, char)
        return result
    
    def set_elements(self, elements_mapping, application_name=""):
        """
        Set the elements mapping from scanner
        
        Args:
            elements_mapping (dict): Dictionary with index as key and element info as value
                                   element_info contains 'element' (pywinauto element) and 'rect' (position)
            application_name (str): Current application name for typing mode detection
        """
        self.elements_mapping = elements_mapping
        self.application_name = application_name
        logger.info(f"Controller received {len(self.elements_mapping)} elements for '{application_name}'")
        
    def click(self, index):
        """
        Click on element by index using pywinauto's native click (live coordinates)
        
        Args:
            index (str): The element index to click
            
        Returns:
            dict: Result of click operation
        """
        try:
            index = str(index)  # Ensure index is string
            
            if index not in self.elements_mapping:
                return {
                    "status": "error", 
                    "action": "click",
                    "index": index,
                    "message": f"Element index {index} not found"
                }
            
            element_info = self.elements_mapping[index]
            element = element_info['element']
            
            # OCR_TEXT: no pywinauto element, use coordinate-based click
            if element is None:
                click_x, click_y = self._find_click_point(element_info['rect'])
                self._move_mouse_smoothly(click_x, click_y)
                time.sleep(0.05)
                pyautogui.click(click_x, click_y)
                time.sleep(1.0)
                return {"status": "success", "action": "click", "index": index, "element_name": element_info.get('name', 'Unknown')}
            
            # Check if element is hidden (not clickable)
            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {
                    "status": "error",
                    "action": "click",
                    "index": index,
                    "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."
                }
            
            # For partial elements, try InvokePattern first (no mouse, no coordinates)
            # Falls back to coordinate click if element doesn't support invoke
            if visibility.startswith('partial'):
                try:
                    import comtypes.client
                    _UIA_module = comtypes.client.GetModule("UIAutomationCore.dll")
                    raw_element = element.element_info.element
                    invoke_raw = raw_element.GetCurrentPattern(10000)  # UIA_InvokePatternId
                    if invoke_raw:
                        invoke_iface = invoke_raw.QueryInterface(_UIA_module.IUIAutomationInvokePattern)
                        invoke_iface.Invoke()
                        print(f"✅ InvokePattern clicked element {index} (visibility={visibility})")
                        time.sleep(1.0)
                        return {
                            "status": "success",
                            "action": "click",
                            "index": index,
                            "element_name": element_info.get('name', 'Unknown'),
                            "method": "invoke"
                        }
                except Exception:
                    pass  # No invoke support, fall through to coordinate click
            
            # Try native pywinauto click first (uses live coordinates)
            try:
                # Get fresh element rectangle (live position)
                current_rect = element.rectangle()
                
                # Get optimal click point using pixel analysis on appropriate rect
                click_x, click_y = self._get_click_coords_for_element(element_info)
                
                # Convert absolute coords to relative coords within element
                # Use original rect for offset calculation (pixel analysis was done on it)
                orig_rect = element_info['rect']
                rel_x = click_x - orig_rect.left
                rel_y = click_y - orig_rect.top
                
                # Clamp to current element bounds
                elem_width = current_rect.right - current_rect.left
                elem_height = current_rect.bottom - current_rect.top
                rel_x = max(0, min(rel_x, elem_width - 1))
                rel_y = max(0, min(rel_y, elem_height - 1))
                    
                # Use pywinauto's native click with relative coords (fetches live position internally)
                element.click_input(coords=(rel_x, rel_y))
                
                logger.info(f"Clicked element {index} at relative coords ({rel_x}, {rel_y})")
                
            except Exception as click_error:
                error_str = str(click_error)
                # Check if this is a UIPI/privilege error
                if "SetCursorPos" in error_str or "Cannot create a file" in error_str:
                    logger.warning(f"Normal click blocked by UIPI, trying Interception fallback...")
                    
                    # For Interception, get fresh absolute coords
                    try:
                        current_rect = element.rectangle()
                        abs_x = current_rect.left + rel_x
                        abs_y = current_rect.top + rel_y
                    except:
                        # Fallback to original calculated coords
                        abs_x, abs_y = self._get_click_coords_for_element(element_info)
                    
                    if not self._interception_mouse_click(abs_x, abs_y, "left"):
                        return {
                            "status": "error",
                            "action": "click",
                            "index": index,
                            "message": "Click failed: UIPI blocked and Interception fallback failed"
                        }
                else:
                    raise click_error
            
            # Wait 1 second after click to let UI update
            time.sleep(1.0)
            
            return {
                "status": "success",
                "action": "click", 
                "index": index,
                "element_name": element_info.get('name', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"Error clicking element {index}: {str(e)}")
            return {
                "status": "error",
                "action": "click",
                "index": index,
                "message": str(e)
            }
    
    def input(self, index, value):
        """
        Input text into element by index
        
        Args:
            index (str): The element index to input into
            value (str): The text to input
            
        Returns:
            dict: Result of input operation
        """
        try:
            index = str(index)  # Ensure index is string
            
            if index not in self.elements_mapping:
                return {
                    "status": "error",
                    "action": "input",
                    "index": index,
                    "message": f"Element index {index} not found"
                }
            
            element_info = self.elements_mapping[index]
            element = element_info['element']
            
            # Check if element is hidden (not interactable)
            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {
                    "status": "error",
                    "action": "input",
                    "index": index,
                    "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."
                }
            
            # Click to focus using pywinauto's native click (handles coordinate updates internally)
            element.click_input()
            time.sleep(0.1)
            
            # Clear existing content using element.type_keys (targets specific element)
            element.type_keys('^a', with_spaces=True)  # Ctrl+A to select all
            time.sleep(0.05)
            element.type_keys('{BACKSPACE}', with_spaces=True)  # Backspace to delete
            time.sleep(0.05)
            
            # Check if current app needs slow typing
            is_slow_app = any(app.lower() in self.application_name.lower() for app in SLOW_TYPING_APPS)
            
            # Escape special characters for pywinauto (parentheses, ^, +, %, ~, {, })
            escaped_value = self._escape_for_type_keys(value)
            
            if is_slow_app:
                # Slow typing for legacy apps - character by character
                logger.info(f"Using slow typing mode for '{self.application_name}'")
                for char in escaped_value:
                    element.type_keys(char, with_spaces=True, with_newlines=True)
                    time.sleep(0.05)  # 50ms delay between characters
            else:
                # Fast typing using UIA for modern apps
                element.type_keys(escaped_value, with_spaces=True, with_newlines=True)
            
            logger.info(f"Input '{value}' into element {index}")
            
            # Proportional wait for UI to render (20ms per char, minimum 0.5s)
            wait_time = max(0.5, len(value) * 0.02)
            time.sleep(wait_time)
            
            return {
                "status": "success",
                "action": "input",
                "index": index,
                "value": value,
                "element_name": element_info.get('name', 'Unknown'),
                "message": "verify yourself using Raw Vision"
            }
            
        except Exception as e:
            logger.error(f"Error inputting to element {index}: {str(e)}")
            return {
                "status": "error", 
                "action": "input",
                "index": index,
                "message": str(e)
            }

    def double_click(self, index):
        """
        Double-click on element by index using pywinauto's native double-click (live coordinates)
        
        Args:
            index (str): The element index to double-click
            
        Returns:
            dict: Result of double-click operation
        """
        try:
            index = str(index)  # Ensure index is string
            
            if index not in self.elements_mapping:
                return {
                    "status": "error", 
                    "action": "double_click",
                    "index": index,
                    "message": f"Element index {index} not found"
                }
            
            element_info = self.elements_mapping[index]
            element = element_info['element']
            
            # OCR_TEXT: no pywinauto element, use coordinate-based double click
            if element is None:
                click_x, click_y = self._find_click_point(element_info['rect'])
                self._move_mouse_smoothly(click_x, click_y)
                time.sleep(0.05)
                pyautogui.click(click_x, click_y, clicks=2, interval=0.05)
                time.sleep(1.0)
                return {"status": "success", "action": "double_click", "index": index, "element_name": element_info.get('name', 'Unknown')}
            
            # Check if element is hidden (not clickable)
            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {
                    "status": "error",
                    "action": "double_click",
                    "index": index,
                    "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."
                }
            
            # Try native pywinauto double-click first (uses live coordinates)
            try:
                # Get fresh element rectangle (live position)
                current_rect = element.rectangle()
                
                # Get optimal click point using pixel analysis on appropriate rect
                click_x, click_y = self._get_click_coords_for_element(element_info)
                
                # Convert absolute coords to relative coords within element
                orig_rect = element_info['rect']
                rel_x = click_x - orig_rect.left
                rel_y = click_y - orig_rect.top
                
                # Clamp to current element bounds
                elem_width = current_rect.right - current_rect.left
                elem_height = current_rect.bottom - current_rect.top
                rel_x = max(0, min(rel_x, elem_width - 1))
                rel_y = max(0, min(rel_y, elem_height - 1))
                
                # Use pywinauto's native double-click with relative coords (fetches live position internally)
                element.double_click_input(coords=(rel_x, rel_y))
                
                logger.info(f"Double-clicked element {index} at relative coords ({rel_x}, {rel_y})")
                
            except Exception as click_error:
                error_str = str(click_error)
                # Check if this is a UIPI/privilege error
                if "SetCursorPos" in error_str or "Cannot create a file" in error_str:
                    logger.warning(f"Normal double-click blocked by UIPI, trying Interception fallback...")
                    
                    # For Interception, get fresh absolute coords
                    try:
                        current_rect = element.rectangle()
                        abs_x = current_rect.left + rel_x
                        abs_y = current_rect.top + rel_y
                    except:
                        # Fallback to original calculated coords
                        abs_x, abs_y = self._get_click_coords_for_element(element_info)
                    
                    if not self._interception_mouse_click(abs_x, abs_y, "double"):
                        return {
                            "status": "error",
                            "action": "double_click",
                            "index": index,
                            "message": "Double-click failed: UIPI blocked and Interception fallback failed"
                        }
                else:
                    raise click_error
            
            # Wait 1 second after double-click to let UI update
            time.sleep(1.0)
            
            return {
                "status": "success",
                "action": "double_click", 
                "index": index,
                "element_name": element_info.get('name', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"Error double-clicking element {index}: {str(e)}")
            return {
                "status": "error",
                "action": "double_click",
                "index": index,
                "message": str(e)
            }
    
    def triple_click(self, index):
        """
        Triple-click on element by index (select entire line).
        Used primarily for OCR_TEXT elements to select the full line.
        
        Args:
            index (str): The element index to triple-click
            
        Returns:
            dict: Result of triple-click operation
        """
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {
                    "status": "error",
                    "action": "triple_click",
                    "index": index,
                    "message": f"Element index {index} not found"
                }

            element_info = self.elements_mapping[index]
            element = element_info['element']

            # OCR_TEXT: no pywinauto element, use coordinate-based triple click
            if element is None:
                click_x, click_y = self._find_click_point(element_info['rect'])
                self._move_mouse_smoothly(click_x, click_y)
                time.sleep(0.05)
                pyautogui.click(click_x, click_y, clicks=3, interval=0.05)
                time.sleep(1.0)
                return {"status": "success", "action": "triple_click", "index": index, "element_name": element_info.get('name', 'Unknown')}

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {
                    "status": "error",
                    "action": "triple_click",
                    "index": index,
                    "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."
                }

            try:
                current_rect = element.rectangle()
                click_x, click_y = self._get_click_coords_for_element(element_info)

                orig_rect = element_info['rect']
                rel_x = click_x - orig_rect.left
                rel_y = click_y - orig_rect.top

                elem_width = current_rect.right - current_rect.left
                elem_height = current_rect.bottom - current_rect.top
                rel_x = max(0, min(rel_x, elem_width - 1))
                rel_y = max(0, min(rel_y, elem_height - 1))

                abs_x = current_rect.left + rel_x
                abs_y = current_rect.top + rel_y

                self._move_mouse_smoothly(abs_x, abs_y)
                time.sleep(0.05)
                pyautogui.click(abs_x, abs_y, clicks=3, interval=0.05)

                logger.info(f"Triple-clicked element {index} at ({abs_x}, {abs_y})")

            except Exception as click_error:
                error_str = str(click_error)
                if "SetCursorPos" in error_str or "Cannot create a file" in error_str:
                    logger.warning(f"Normal triple-click blocked by UIPI, trying Interception fallback...")
                    try:
                        current_rect = element.rectangle()
                        abs_x = current_rect.left + rel_x
                        abs_y = current_rect.top + rel_y
                    except:
                        abs_x, abs_y = self._get_click_coords_for_element(element_info)

                    for i in range(3):
                        if not self._interception_mouse_click(abs_x, abs_y, "left"):
                            return {
                                "status": "error",
                                "action": "triple_click",
                                "index": index,
                                "message": "Triple-click failed: UIPI blocked and Interception fallback failed"
                            }
                        if i < 2:
                            time.sleep(0.05)
                else:
                    raise click_error

            time.sleep(1.0)

            return {
                "status": "success",
                "action": "triple_click",
                "index": index,
                "element_name": element_info.get('name', 'Unknown')
            }

        except Exception as e:
            logger.error(f"Error triple-clicking element {index}: {str(e)}")
            return {
                "status": "error",
                "action": "triple_click",
                "index": index,
                "message": str(e)
            }

    def right_click(self, index):
        """
        Right-click on element by index using pywinauto's native right-click (live coordinates)
        
        Args:
            index (str): The element index to right-click
            
        Returns:
            dict: Result of right-click operation
        """
        try:
            index = str(index)  # Ensure index is string
            
            if index not in self.elements_mapping:
                return {
                    "status": "error", 
                    "action": "right_click",
                    "index": index,
                    "message": f"Element index {index} not found"
                }
            
            element_info = self.elements_mapping[index]
            element = element_info['element']
            
            # OCR_TEXT: no pywinauto element, use coordinate-based right click
            if element is None:
                click_x, click_y = self._find_click_point(element_info['rect'])
                self._move_mouse_smoothly(click_x, click_y)
                time.sleep(0.05)
                pyautogui.rightClick(click_x, click_y)
                time.sleep(1.0)
                return {"status": "success", "action": "right_click", "index": index, "element_name": element_info.get('name', 'Unknown')}
            
            # Check if element is hidden (not clickable)
            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {
                    "status": "error",
                    "action": "right_click",
                    "index": index,
                    "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."
                }
            
            # Try native pywinauto right-click first (uses live coordinates)
            try:
                # Get fresh element rectangle (live position)
                current_rect = element.rectangle()
                
                # Get optimal click point using pixel analysis on appropriate rect
                click_x, click_y = self._get_click_coords_for_element(element_info)
                
                # Convert absolute coords to relative coords within element
                orig_rect = element_info['rect']
                rel_x = click_x - orig_rect.left
                rel_y = click_y - orig_rect.top
                
                # Clamp to current element bounds
                elem_width = current_rect.right - current_rect.left
                elem_height = current_rect.bottom - current_rect.top
                rel_x = max(0, min(rel_x, elem_width - 1))
                rel_y = max(0, min(rel_y, elem_height - 1))
                
                # Use pywinauto's native right-click with relative coords (fetches live position internally)
                element.right_click_input(coords=(rel_x, rel_y))
                
                logger.info(f"Right-clicked element {index} at relative coords ({rel_x}, {rel_y})")
                
            except Exception as click_error:
                error_str = str(click_error)
                # Check if this is a UIPI/privilege error
                if "SetCursorPos" in error_str or "Cannot create a file" in error_str:
                    logger.warning(f"Normal right-click blocked by UIPI, trying Interception fallback...")
                    
                    # For Interception, get fresh absolute coords
                    try:
                        current_rect = element.rectangle()
                        abs_x = current_rect.left + rel_x
                        abs_y = current_rect.top + rel_y
                    except:
                        # Fallback to original calculated coords
                        abs_x, abs_y = self._get_click_coords_for_element(element_info)
                    
                    if not self._interception_mouse_click(abs_x, abs_y, "right"):
                        return {
                            "status": "error",
                            "action": "right_click",
                            "index": index,
                            "message": "Right-click failed: UIPI blocked and Interception fallback failed"
                        }
                else:
                    raise click_error
            
            # Wait 1 second after right-click to let context menu appear
            time.sleep(1.0)
            
            return {
                "status": "success",
                "action": "right_click", 
                "index": index,
                "element_name": element_info.get('name', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"Error right-clicking element {index}: {str(e)}")
            return {
                "status": "error",
                "action": "right_click",
                "index": index,
                "message": str(e)
            }
            
    def scroll(self, index, direction):
        """
        Scroll an element in a specified direction
        
        Args:
            index (str): The element index to scroll
            direction (str): Direction to scroll ('up', 'down', 'left', 'right')
            
        Returns:
            dict: Result of scroll operation
        """
        try:
            index = str(index)  # Ensure index is string
            
            if index not in self.elements_mapping:
                return {
                    "status": "error",
                    "action": "scroll",
                    "index": index,
                    "message": f"Element index {index} not found"
                }
            
            element_info = self.elements_mapping[index]
            element = element_info['element']
            
            # For scroll, we allow scrolling even on hidden elements (to reveal them)
            # But we still use visible_rect if available for better positioning
            # Use visible_rect for partial elements, fallback to full rect if None
            rect = element_info.get('visible_rect') or element_info['rect']
            
            # Calculate center position of the element
            center_x = rect.left + (rect.right - rect.left) // 2
            center_y = rect.top + (rect.bottom - rect.top) // 2
            
            # Move mouse to the element
            self._move_mouse_smoothly(center_x, center_y)
            time.sleep(0.1)
            
            # Perform scroll based on direction
            scroll_amount = 3  # Number of scroll clicks
            
            if direction.lower() == "up":
                # Scroll up (positive scroll)
                for _ in range(scroll_amount):
                    pyautogui.scroll(120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "down":
                # Scroll down (negative scroll)
                for _ in range(scroll_amount):
                    pyautogui.scroll(-120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "left":
                # Scroll left (using horizontal scroll if supported)
                for _ in range(scroll_amount):
                    pyautogui.hscroll(-120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "right":
                # Scroll right (using horizontal scroll if supported)
                for _ in range(scroll_amount):
                    pyautogui.hscroll(120, x=center_x, y=center_y)
                    time.sleep(0.05)
            else:
                return {
                    "status": "error",
                    "action": "scroll",
                    "index": index,
                    "message": f"Invalid scroll direction: {direction}. Use 'up', 'down', 'left', or 'right'"
                }
            
            logger.info(f"Scrolled element {index} {direction} at position ({center_x}, {center_y})")
            
            # Wait briefly for UI to update
            time.sleep(0.5)
            
            return {
                "status": "success",
                "action": "scroll",
                "index": index,
                "direction": direction,
                "element_name": element_info.get('name', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"Error scrolling element {index}: {str(e)}")
            return {
                "status": "error",
                "action": "scroll",
                "index": index,
                "message": str(e)
            }
    
    def drag(self, start_x, start_y, end_x, end_y):
        """
        Drag mouse from start position to end position.
        Used for screenshot region selection and similar drag operations.
        
        Args:
            start_x, start_y: Starting coordinates
            end_x, end_y: Ending coordinates
            
        Returns:
            dict: Result of drag operation
        """
        try:
            # Move to start position
            self._move_mouse_smoothly(start_x, start_y)
            time.sleep(0.1)
            
            # Mouse down at start
            pyautogui.mouseDown(x=start_x, y=start_y)
            time.sleep(0.05)
            
            # Drag to end position (smooth movement)
            pyautogui.moveTo(end_x, end_y, duration=0.3)
            time.sleep(0.05)
            
            # Mouse up at end
            pyautogui.mouseUp(x=end_x, y=end_y)
            time.sleep(0.1)
            
            logger.info(f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})")
            
            return {
                "status": "success",
                "action": "drag",
                "start": (start_x, start_y),
                "end": (end_x, end_y)
            }
            
        except Exception as e:
            logger.error(f"Error dragging: {str(e)}")
            return {
                "status": "error",
                "action": "drag",
                "message": str(e)
            }

    def canvas_input(self, text):
        """
        Type text directly into currently focused location (no element targeting).
        UIPI-protected apps (e.g. Windows Security) route to canvas_input.py (kernel driver).
        Normal apps use pyautogui; falls back to kernel driver on failure.
        
        Args:
            text (str): The text to type
            
        Returns:
            dict: Result of canvas input operation
        """
        from .tool.kernel_input import canvas_input as kernel_canvas_input

        if any(app.lower() in self.application_name.lower() for app in KERNEL_INPUT_APPS):
            logger.info(f"App '{self.application_name}' is UIPI-protected, routing to kernel canvas_input")
            return kernel_canvas_input(text, stop_event=self.stop_event)

        try:
            # Type character by character so we can check stop_event
            for char in text:
                if self.stop_event and self.stop_event.is_set():
                    logger.info("canvas_input (pyautogui) interrupted by stop_event")
                    return {"status": "stopped", "action": "canvas_input", "message": "Stopped by user"}
                pyautogui.write(char, interval=0.04)
            time.sleep(0.22)
            
            logger.info(f"Canvas input: typed '{text}' ({len(text)} chars)")
            
            return {
                "status": "success",
                "action": "canvas_input",
                "text": text,
                "message": "verify yourself using visual"
            }
            
        except Exception as e:
            logger.warning(f"pyautogui canvas_input failed: {e}, falling back to kernel driver")
            return kernel_canvas_input(text)
