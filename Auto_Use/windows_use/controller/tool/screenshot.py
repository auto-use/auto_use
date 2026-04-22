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

from ...tree.element import UIElementScanner, ELEMENT_CONFIG
from ..service import ControllerService
from .open_app import open_on_windows

logger = logging.getLogger(__name__)


class ScreenshotService:
    """Service for capturing element screenshots via Snipping Tool app"""
    
    def __init__(self, controller_service: ControllerService):
        self.controller_service = controller_service
    
    def capture_element(self, rect) -> dict:
        """
        Capture a screenshot of a specific element region.
        
        Smart Snipping Tool management (single instance policy):
        - Case 1: Already the topmost window → skip opening, go straight to scan
        - Case 2: Running on taskbar but not focused → click taskbar icon to bring to front
        - Case 3: Not running at all → launch fresh via open_on_windows
        
        After Snipping Tool is in foreground, the flow is always:
        1. Scan for app elements
        2. Ensure Rectangle mode (skip dropdown if already Rectangle)
        3. Click New to start capture
        4. Drag over element rect
        5. Click Copy button
        
        Args:
            rect: Element bounding rectangle with left, top, right, bottom
            
        Returns:
            dict: Result of screenshot operation
        """
        # Step 1: Determine Snipping Tool state (on_top / on_taskbar / not_running)
        state, taskbar_index = self._get_snipping_tool_state()
        
        if state == "on_top":
            logger.info("Screenshot: Snipping Tool already on top, skipping open")
        
        elif state == "on_taskbar":
            logger.info("Screenshot: Snipping Tool on taskbar, clicking to bring to front")
            self.controller_service.click(str(taskbar_index))
            time.sleep(0.7)
        
        else:
            logger.info("Screenshot: Snipping Tool not running, opening fresh")
            success = open_on_windows("snipping tool")
            if not success:
                return {
                    "status": "error",
                    "action": "screenshot",
                    "message": "Failed to open Snipping Tool"
                }
        
        # Step 2: Wait for app window to load
        app_mapping = self._wait_for_app()
        if app_mapping is None:
            return {
                "status": "error",
                "action": "screenshot",
                "message": "Snipping Tool window did not appear within timeout"
            }
        
        # Step 3: Ensure Rectangle mode (skips dropdown entirely if already Rectangle)
        fix_result = self._ensure_rectangle_mode(app_mapping)
        if fix_result and fix_result.get("status") == "error":
            return fix_result
        
        # Step 4: Click New to start capture
        new_result = self._click_new_button(app_mapping)
        if new_result.get("status") == "error":
            return new_result
        
        # Step 5: Wait for capture mode to activate
        time.sleep(0.7)
        
        # Step 6: Drag over element rect
        logger.info(f"Screenshot: dragging from ({rect.left}, {rect.top}) to ({rect.right}, {rect.bottom})")
        time.sleep(0.2)
        drag_result = self.controller_service.drag(rect.left, rect.top, rect.right, rect.bottom)
        
        if drag_result.get("status") != "success":
            return drag_result
        
        # Step 7: Click Copy button (always runs in all 3 scenarios)
        copy_result = self._click_copy_button()
        if copy_result.get("status") == "error":
            return copy_result
        
        return {
            "status": "success",
            "action": "screenshot",
            "message": "Screenshot captured to clipboard. Paste with Ctrl+V, or save with Ctrl+S for use in emails or files"
        }
    
    def _get_snipping_tool_state(self):
        """
        Check if Snipping Tool is running and determine its current state.
        
        Returns:
            tuple: (state, taskbar_index)
                state: "on_top" | "on_taskbar" | "not_running"
                taskbar_index: element index for clicking taskbar icon (only for "on_taskbar")
        """
        try:
            scanner = UIElementScanner(ELEMENT_CONFIG)
            scanner.scan_elements()
            
            # Case 1: Snipping Tool is the topmost/active window
            if "Snipping Tool" in (scanner.application_name or ""):
                logger.info("Screenshot: detected Snipping Tool as active window")
                return ("on_top", None)
            
            # Case 2: Check taskbar tree for Snipping Tool button
            taskbar_item = self._find_in_taskbar(scanner.taskbar_tree, "Snipping Tool")
            if taskbar_item and taskbar_item.get("index"):
                index = taskbar_item["index"]
                self.controller_service.set_elements(scanner.get_elements_mapping())
                logger.info(f"Screenshot: found Snipping Tool on taskbar (index={index})")
                return ("on_taskbar", index)
            
            # Case 3: Not running anywhere
            logger.info("Screenshot: Snipping Tool not found running")
            return ("not_running", None)
            
        except Exception as e:
            logger.warning(f"Screenshot: state detection failed ({e}), falling back to fresh open")
            return ("not_running", None)
    
    def _find_in_taskbar(self, tree, name_substring):
        """
        Recursively search taskbar element tree for an item matching the given name.
        
        Args:
            tree: List of taskbar tree elements
            name_substring: Substring to match against element names (case-insensitive)
            
        Returns:
            dict: Matching element info dict, or None if not found
        """
        name_lower = name_substring.lower()
        for item in tree:
            if name_lower in item.get("name", "").lower():
                return item
            result = self._find_in_taskbar(item.get("children", []), name_substring)
            if result:
                return result
        return None
    
    def _is_rectangle_mode(self, mapping):
        """
        Check if Snipping Tool is already in Rectangle mode by inspecting element properties.
        
        Checks multiple indicators so detection works regardless of how the app was opened:
        - ComboBox / dropdown with value containing "rectangle"
        - Element name containing "rectangle" in snipping area context
        - ListItem named "Rectangle" that is currently selected
        
        Args:
            mapping: Elements mapping from Snipping Tool scan
            
        Returns:
            bool: True if already in Rectangle mode
        """
        for idx, info in mapping.items():
            name = (info.get('name', '') or '').lower()
            value = (info.get('value', '') or '').lower()
            element_type = (info.get('type', '') or '')
            
            # Check 1: ComboBox or dropdown with "rectangle" in value
            if "snipping" in name and "rectangle" in value:
                logger.info("Screenshot: Rectangle mode detected (dropdown value)")
                return True
            
            # Check 2: Any element with "rectangle" in value
            if "rectangle" in value and element_type in ("ComboBox", "ListItem", "Button"):
                logger.info("Screenshot: Rectangle mode detected (element value)")
                return True
            
            # Check 3: Snipping area element name itself contains rectangle
            if "snipping" in name and "rectangle" in name:
                logger.info("Screenshot: Rectangle mode detected (element name)")
                return True
        
        return False
    
    def _wait_for_app(self, max_wait=5, poll_interval=0.3):
        """
        Poll until Snipping Tool app window is loaded and elements are scannable.
        
        Returns:
            dict: Elements mapping if found, None if timeout
        """
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            try:
                scanner = UIElementScanner(ELEMENT_CONFIG)
                scanner.scan_elements()
                scanner.get_scan_data()
                
                if "Snipping Tool" in scanner.application_name:
                    mapping = scanner.get_elements_mapping()
                    for idx, info in mapping.items():
                        if info.get('name', '') == "New screenshot":
                            logger.info("Screenshot: Snipping Tool app loaded")
                            return mapping
            except:
                continue
        
        logger.error("Screenshot: Snipping Tool app detection timed out")
        return None
    
    def _ensure_rectangle_mode(self, mapping):
        """
        Check current snipping mode and switch to Rectangle ONLY if not already Rectangle.
        If already Rectangle, skips entirely - no dropdown click, no selection.
        
        Args:
            mapping: Elements mapping from Snipping Tool app scan
            
        Returns:
            dict or None: Error dict if failed, None if successful
        """
        # Quick check: already Rectangle? Skip everything.
        if self._is_rectangle_mode(mapping):
            return None
        
        # Not in Rectangle - find and click the dropdown
        dropdown_id = None
        for idx, info in mapping.items():
            name = (info.get('name', '') or '').lower()
            if "snipping mode" in name or "snipping area" in name:
                dropdown_id = idx
                break
        
        if dropdown_id is None:
            logger.warning("Screenshot: mode dropdown not found, proceeding with current mode")
            return None
        
        # Click dropdown to open mode list
        self.controller_service.set_elements(mapping)
        self.controller_service.click(dropdown_id)
        
        # 1 second wait for dropdown to open (user-specified)
        time.sleep(1.0)
        
        # Poll until Rectangle option appears
        rectangle_id = None
        list_mapping = None
        max_wait = 3
        poll_interval = 0.3
        elapsed = 0
        
        while elapsed < max_wait:
            try:
                list_scanner = UIElementScanner(ELEMENT_CONFIG)
                list_scanner.scan_elements()
                list_mapping = list_scanner.get_elements_mapping()
                
                for idx, info in list_mapping.items():
                    if info.get('name', '') == "Rectangle":
                        rectangle_id = idx
                        logger.info("Screenshot: Rectangle option found in dropdown")
                        break
                
                if rectangle_id:
                    break
            except:
                pass
            
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        if not rectangle_id:
            logger.warning("Screenshot: Rectangle option not found in dropdown, closing and proceeding")
            keyboard.send('escape')
            time.sleep(0.3)
            return None
        
        # Click Rectangle to select it
        logger.info("Screenshot: clicking Rectangle to select it")
        self.controller_service.set_elements(list_mapping)
        self.controller_service.click(rectangle_id)
        time.sleep(0.7)
        
        return None
    
    def _click_new_button(self, mapping):
        """
        Find and click the New button in Snipping Tool to start capture.
        
        Args:
            mapping: Elements mapping from Snipping Tool app scan
            
        Returns:
            dict: Success or error result
        """
        # Rescan to get fresh mapping (mode may have changed)
        scanner = UIElementScanner(ELEMENT_CONFIG)
        scanner.scan_elements()
        fresh_mapping = scanner.get_elements_mapping()
        
        for idx, info in fresh_mapping.items():
            if info.get('name', '') == "New screenshot":
                self.controller_service.set_elements(fresh_mapping)
                self.controller_service.click(idx)
                logger.info("Screenshot: clicked New screenshot button")
                time.sleep(0.3)
                return {"status": "success"}
        
        return {
            "status": "error",
            "action": "screenshot",
            "message": "New screenshot button not found in Snipping Tool"
        }
    
    def _click_copy_button(self, max_wait=5, poll_interval=0.3):
        """
        Wait for snip result UI and click the Copy button.
        
        Returns:
            dict: Success or error result
        """
        logger.info("Screenshot: waiting for Copy button...")
        time.sleep(0.7)
        
        elapsed = 0
        while elapsed < max_wait:
            try:
                copy_scanner = UIElementScanner(ELEMENT_CONFIG)
                copy_scanner.scan_elements()
                copy_mapping = copy_scanner.get_elements_mapping()
                
                for idx, info in copy_mapping.items():
                    if info.get('name', '') == "Copy":
                        self.controller_service.set_elements(copy_mapping)
                        self.controller_service.click(idx)
                        time.sleep(0.3)
                        logger.info("Screenshot: copied to clipboard")
                        return {"status": "success"}
            except:
                pass
            
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        logger.warning("Screenshot: Copy button not found")
        return {
            "status": "error",
            "action": "screenshot",
            "message": "Copy button not found after snip capture"
        }