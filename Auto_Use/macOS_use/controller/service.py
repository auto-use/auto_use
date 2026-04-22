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

# Auto_Use/macOS_use/controller/service.py
# macOS version — all mouse interactions via Quartz with proven approach:
#   - kCGEventSourceStatePrivate (not CombinedSessionState)
#   - CGWarpMouseCursorPosition for cursor placement
#   - CGEventSetLocation on all down/up events
# Keyboard/scroll still use pyautogui (works fine on macOS)

import logging
import time
import pyautogui
from PIL import ImageGrab
import numpy as np
import Quartz
from Quartz import (
    CGEventCreateMouseEvent, CGEventPost, CGEventSourceCreate,
    CGEventSetIntegerValueField, CGEventSetLocation,
    CGWarpMouseCursorPosition, CGAssociateMouseAndMouseCursorPosition,
    CGPointMake,
    kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGEventRightMouseDown, kCGEventRightMouseUp,
    kCGEventLeftMouseDragged,
    kCGMouseButtonLeft, kCGMouseButtonRight,
    kCGMouseEventClickState,
    kCGHIDEventTap, kCGEventSourceStatePrivate,
)
from ApplicationServices import AXIsProcessTrusted, AXUIElementPerformAction, AXUIElementCopyActionNames
from Cocoa import NSWorkspace, NSApplicationActivateIgnoringOtherApps
from ..tree.element import get_screen, _find_topmost_app_on_screen, find_app

# pyautogui only used for keyboard + scroll (not mouse clicks)
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

logger = logging.getLogger(__name__)

# Legacy apps that need slow character-by-character typing
SLOW_TYPING_APPS = [
    "terminal",
    "iterm2",
]


class ControllerService:
    def __init__(self, stop_event=None):
        """Initialize the Controller Service"""
        self.elements_mapping = {}
        self.application_name = ""
        self.stop_event = stop_event

        trusted = AXIsProcessTrusted()
        if not trusted:
            logger.warning(
                "Accessibility permission NOT granted — mouse clicks will be silently dropped by macOS. "
                "Go to System Settings > Privacy & Security > Accessibility and add this app."
            )
        else:
            logger.info("Accessibility permission OK")

    def release_all_inputs(self):
        """Emergency release all hardware inputs (keyboard + mouse) via pyautogui."""
        try:
            for key in ['shift', 'ctrl', 'alt', 'shiftleft', 'shiftright',
                        'ctrlleft', 'ctrlright', 'altleft', 'altright']:
                pyautogui.keyUp(key)
            pyautogui.mouseUp(button='left')
            pyautogui.mouseUp(button='right')
            logger.info("Emergency release: all inputs released via pyautogui")
        except Exception as e:
            logger.error(f"pyautogui emergency release failed: {e}")

    # ------------------------------------------------------------------
    # Quartz primitives — single source per interaction
    # The move and click MUST share the same event source or macOS
    # drops the click silently.
    # ------------------------------------------------------------------

    def _quartz_source(self):
        """Create a Private event source — required for clicks to register."""
        return CGEventSourceCreate(kCGEventSourceStatePrivate)

    def _force_focus_target_app(self):
        """Re-activate the topmost app on the built-in display before clicking.

        After extract_all() scans the AX tree it restores focus to the calling
        process (this agent).  macOS treats the first click on an inactive
        window as an activation click rather than an element click, so we must
        bring the target app back to front before posting Quartz events.
        Mirrors the force_focus_main() step from element/click.py.
        """
        try:
            screen = get_screen()
            top, _ = _find_topmost_app_on_screen(screen)
            target_pid = top["pid"] if top else None

            if target_pid is None:
                finder = find_app("com.apple.finder")
                if finder:
                    target_pid = finder.processIdentifier()

            if target_pid is None:
                return

            ws = NSWorkspace.sharedWorkspace()
            for app in ws.runningApplications():
                if app.processIdentifier() == target_pid:
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(0.5)
                    return
        except Exception as e:
            logger.warning(f"force_focus_target_app failed: {e}")

    def _warp_move_click(self, x, y, click_count=1):
        """
        Full click sequence with ONE event source (proven working approach):
        force-focus target app → warp cursor → move event → click down/up.
        """
        self._force_focus_target_app()

        point = CGPointMake(float(x), float(y))
        source = self._quartz_source()

        # Warp cursor physically
        CGWarpMouseCursorPosition(point)
        CGAssociateMouseAndMouseCursorPosition(True)
        time.sleep(0.5)

        # Move event (same source)
        move = CGEventCreateMouseEvent(
            source, kCGEventMouseMoved, point, kCGMouseButtonLeft
        )
        if move is None:
            logger.error("Quartz: failed to create move event")
            return
        CGEventPost(kCGHIDEventTap, move)
        time.sleep(0.3)

        # Click down/up (same source)
        for i in range(1, click_count + 1):
            down = CGEventCreateMouseEvent(
                source, kCGEventLeftMouseDown, point, kCGMouseButtonLeft
            )
            up = CGEventCreateMouseEvent(
                source, kCGEventLeftMouseUp, point, kCGMouseButtonLeft
            )
            if down is None or up is None:
                logger.error(f"Quartz: failed to create click events (pass {i})")
                return

            CGEventSetIntegerValueField(down, kCGMouseEventClickState, i)
            CGEventSetIntegerValueField(up, kCGMouseEventClickState, i)
            CGEventSetLocation(down, point)
            CGEventSetLocation(up, point)

            CGEventPost(kCGHIDEventTap, down)
            time.sleep(0.08)
            CGEventPost(kCGHIDEventTap, up)
            if i < click_count:
                time.sleep(0.06)

    def _warp_move_right_click(self, x, y):
        """
        Full right-click sequence with ONE event source.
        """
        self._force_focus_target_app()

        point = CGPointMake(float(x), float(y))
        source = self._quartz_source()

        CGWarpMouseCursorPosition(point)
        CGAssociateMouseAndMouseCursorPosition(True)
        time.sleep(0.5)

        move = CGEventCreateMouseEvent(
            source, kCGEventMouseMoved, point, kCGMouseButtonLeft
        )
        if move is None:
            logger.error("Quartz: failed to create move event")
            return
        CGEventPost(kCGHIDEventTap, move)
        time.sleep(0.3)

        down = CGEventCreateMouseEvent(
            source, kCGEventRightMouseDown, point, kCGMouseButtonRight
        )
        up = CGEventCreateMouseEvent(
            source, kCGEventRightMouseUp, point, kCGMouseButtonRight
        )
        if down is None or up is None:
            logger.error("Quartz: failed to create right-click events")
            return

        CGEventSetIntegerValueField(down, kCGMouseEventClickState, 1)
        CGEventSetIntegerValueField(up, kCGMouseEventClickState, 1)
        CGEventSetLocation(down, point)
        CGEventSetLocation(up, point)

        CGEventPost(kCGHIDEventTap, down)
        time.sleep(0.08)
        CGEventPost(kCGHIDEventTap, up)

    def _warp_cursor_only(self, x, y):
        """
        Just warp + move (for scroll, drag start). No click.
        Returns the source so drag can reuse it.
        """
        point = CGPointMake(float(x), float(y))
        source = self._quartz_source()

        CGWarpMouseCursorPosition(point)
        CGAssociateMouseAndMouseCursorPosition(True)
        time.sleep(0.5)

        move = CGEventCreateMouseEvent(
            source, kCGEventMouseMoved, point, kCGMouseButtonLeft
        )
        if move:
            CGEventPost(kCGHIDEventTap, move)
        time.sleep(0.3)

        return source

    def _quartz_mouse_down(self, source, x, y):
        """Mouse down using provided source."""
        point = CGPointMake(float(x), float(y))
        down = CGEventCreateMouseEvent(
            source, kCGEventLeftMouseDown, point, kCGMouseButtonLeft
        )
        if down is None:
            logger.error("Quartz: failed to create mouseDown event")
            return
        CGEventSetIntegerValueField(down, kCGMouseEventClickState, 1)
        CGEventSetLocation(down, point)
        CGEventPost(kCGHIDEventTap, down)

    def _quartz_mouse_up(self, source, x, y):
        """Mouse up using provided source."""
        point = CGPointMake(float(x), float(y))
        up = CGEventCreateMouseEvent(
            source, kCGEventLeftMouseUp, point, kCGMouseButtonLeft
        )
        if up is None:
            logger.error("Quartz: failed to create mouseUp event")
            return
        CGEventSetIntegerValueField(up, kCGMouseEventClickState, 1)
        CGEventSetLocation(up, point)
        CGEventPost(kCGHIDEventTap, up)

    # ------------------------------------------------------------------
    # Click coordinate calculation
    # ------------------------------------------------------------------

    def _get_click_coords_for_element(self, element_info):
        """
        Determine optimal click coordinates based on element visibility.
        Full elements: pixel centroid on full rect (avoids dead space).
        Partial elements: pixel centroid on visible_rect + adaptive safety clamp.
        Text input fields: geometric center (centroid is unreliable due to
        borders and baselines pulling the click point away from the input area).
        """
        visibility = element_info.get('visibility', 'full')
        element_type = element_info.get('type', '')

        # Text input fields: always use geometric center.
        text_input_types = {'TextField', 'TextArea', 'ComboBox', 'SearchField'}
        if element_type in text_input_types:
            if visibility.startswith('partial'):
                rect = element_info.get('visible_rect') or element_info['rect']
            else:
                rect = element_info['rect']
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            return (rect.left + width // 2, rect.top + height // 2)

        if visibility.startswith('partial'):
            rect = element_info.get('visible_rect') or element_info['rect']

            width = rect.right - rect.left
            height = rect.bottom - rect.top

            centroid_x, centroid_y = self._find_click_point(rect)

            center_x = rect.left + width // 2
            center_y = rect.top + height // 2

            click_x = int(0.5 * center_x + 0.5 * centroid_x)
            click_y = int(0.5 * center_y + 0.5 * centroid_y)

            margin_x = min(10, width // 4)
            margin_y = min(10, height // 4)

            safe_left = rect.left + margin_x
            safe_right = rect.right - 1 - margin_x
            safe_top = rect.top + margin_y
            safe_bottom = rect.bottom - 1 - margin_y

            if safe_left > safe_right:
                safe_left = safe_right = rect.left + width // 2
            if safe_top > safe_bottom:
                safe_top = safe_bottom = rect.top + height // 2

            click_x = max(safe_left, min(click_x, safe_right))
            click_y = max(safe_top, min(click_y, safe_bottom))

            return (click_x, click_y)
        else:
            rect = element_info['rect']
            return self._find_click_point(rect)

    def _find_click_point(self, rect):
        """
        Analyze element pixels to find optimal click point.
        Uses mode (most common color) as background, finds content cluster centroid.
        """
        try:
            width = rect.right - rect.left
            height = rect.bottom - rect.top

            if width < 5 or height < 5:
                return (rect.left + width // 2, rect.top + height // 2)

            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            pixels = np.array(img)

            if len(pixels.shape) == 3:
                gray = np.mean(pixels, axis=2).astype(np.uint8)
            else:
                gray = pixels

            flat = gray.flatten()
            counts = np.bincount(flat, minlength=256)
            background_color = np.argmax(counts)

            tolerance = 15
            mask = np.abs(gray.astype(np.int16) - background_color) > tolerance

            mask_ratio = np.sum(mask) / mask.size
            if mask_ratio < 0.01 or mask_ratio > 0.95:
                return (rect.left + width // 2, rect.top + height // 2)

            y_coords, x_coords = np.where(mask)

            if len(x_coords) == 0:
                return (rect.left + width // 2, rect.top + height // 2)

            centroid_x = int(np.mean(x_coords))
            centroid_y = int(np.mean(y_coords))

            return (rect.left + centroid_x, rect.top + centroid_y)

        except Exception as e:
            logger.warning(f"Smart click detection failed: {str(e)}, using center")
            center_x = rect.left + (rect.right - rect.left) // 2
            center_y = rect.top + (rect.bottom - rect.top) // 2
            return (center_x, center_y)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_elements(self, elements_mapping, application_name=""):
        """Set the elements mapping from scanner"""
        self.elements_mapping = elements_mapping
        self.application_name = application_name
        logger.info(f"Controller received {len(self.elements_mapping)} elements for '{application_name}'")

    def click(self, index):
        """Click on element by index"""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "click", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {"status": "error", "action": "click", "index": index,
                        "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            if visibility.startswith('partial'):
                ax_el = element_info.get('ax_element')
                if ax_el:
                    try:
                        err, actions = AXUIElementCopyActionNames(ax_el, None)
                        if err == 0 and actions and "AXPress" in actions:
                            err = AXUIElementPerformAction(ax_el, "AXPress")
                            if err == 0:
                                time.sleep(1.0)
                                logger.info(f"AXPress element {index} (partial)")
                                return {"status": "success", "action": "click", "index": index,
                                        "element_name": element_info.get('name', 'Unknown')}
                            else:
                                logger.warning(f"AXPress failed (err={err}) for element {index}, falling back to mouse click")
                        else:
                            logger.info(f"AXPress not available for element {index}, falling back to mouse click")
                    except Exception as e:
                        logger.warning(f"AXPress exception for element {index}: {e}, falling back to mouse click")

            click_x, click_y = self._get_click_coords_for_element(element_info)
            self._warp_move_click(click_x, click_y, click_count=1)
            time.sleep(1.0)

            logger.info(f"Clicked element {index} at ({click_x}, {click_y})")
            return {"status": "success", "action": "click", "index": index,
                    "element_name": element_info.get('name', 'Unknown')}

        except Exception as e:
            logger.error(f"Error clicking element {index}: {str(e)}")
            return {"status": "error", "action": "click", "index": index, "message": str(e)}

    def input(self, index, value):
        """Input text into element by index"""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "input", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {"status": "error", "action": "input", "index": index,
                        "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            click_x, click_y = self._get_click_coords_for_element(element_info)
            self._warp_move_click(click_x, click_y, click_count=1)
            time.sleep(0.1)

            # Select all and delete existing content (Cmd+A on macOS)
            pyautogui.hotkey('command', 'a')
            time.sleep(0.05)
            pyautogui.press('backspace')
            time.sleep(0.05)

            # Type the new value character by character
            is_slow_app = any(app.lower() in self.application_name.lower()
                             for app in SLOW_TYPING_APPS)
            interval = 0.05 if is_slow_app else 0.04

            for char in value:
                if self.stop_event and self.stop_event.is_set():
                    return {"status": "stopped", "action": "input", "message": "Stopped by user"}
                pyautogui.write(char, interval=interval)

            logger.info(f"Input '{value}' into element {index}")

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
            return {"status": "error", "action": "input", "index": index, "message": str(e)}

    def double_click(self, index):
        """Double-click on element by index"""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "double_click", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {"status": "error", "action": "double_click", "index": index,
                        "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            click_x, click_y = self._get_click_coords_for_element(element_info)
            self._warp_move_click(click_x, click_y, click_count=2)
            time.sleep(1.0)

            logger.info(f"Double-clicked element {index} at ({click_x}, {click_y})")
            return {"status": "success", "action": "double_click", "index": index,
                    "element_name": element_info.get('name', 'Unknown')}

        except Exception as e:
            logger.error(f"Error double-clicking element {index}: {str(e)}")
            return {"status": "error", "action": "double_click", "index": index, "message": str(e)}

    def triple_click(self, index):
        """Triple-click on element by index (select entire line)."""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "triple_click", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {"status": "error", "action": "triple_click", "index": index,
                        "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            click_x, click_y = self._get_click_coords_for_element(element_info)
            self._warp_move_click(click_x, click_y, click_count=3)
            time.sleep(1.0)

            logger.info(f"Triple-clicked element {index} at ({click_x}, {click_y})")
            return {"status": "success", "action": "triple_click", "index": index,
                    "element_name": element_info.get('name', 'Unknown')}

        except Exception as e:
            logger.error(f"Error triple-clicking element {index}: {str(e)}")
            return {"status": "error", "action": "triple_click", "index": index, "message": str(e)}

    def right_click(self, index):
        """Right-click on element by index"""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "right_click", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]

            visibility = element_info.get('visibility', 'full')
            if visibility == 'hidden':
                clipped_by = element_info.get('clipped_by', 'unknown container')
                return {"status": "error", "action": "right_click", "index": index,
                        "message": f"Element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            click_x, click_y = self._get_click_coords_for_element(element_info)
            self._warp_move_right_click(click_x, click_y)
            time.sleep(1.0)

            logger.info(f"Right-clicked element {index} at ({click_x}, {click_y})")
            return {"status": "success", "action": "right_click", "index": index,
                    "element_name": element_info.get('name', 'Unknown')}

        except Exception as e:
            logger.error(f"Error right-clicking element {index}: {str(e)}")
            return {"status": "error", "action": "right_click", "index": index, "message": str(e)}

    def scroll(self, index, direction):
        """Scroll an element in a specified direction"""
        try:
            index = str(index)

            if index not in self.elements_mapping:
                return {"status": "error", "action": "scroll", "index": index,
                        "message": f"Element index {index} not found"}

            element_info = self.elements_mapping[index]
            rect = element_info.get('visible_rect') or element_info['rect']

            center_x = rect.left + (rect.right - rect.left) // 2
            center_y = rect.top + (rect.bottom - rect.top) // 2

            # Warp cursor to scroll target
            self._warp_cursor_only(center_x, center_y)

            scroll_amount = 3

            if direction.lower() == "up":
                for _ in range(scroll_amount):
                    pyautogui.scroll(120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "down":
                for _ in range(scroll_amount):
                    pyautogui.scroll(-120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "left":
                for _ in range(scroll_amount):
                    pyautogui.hscroll(-120, x=center_x, y=center_y)
                    time.sleep(0.05)
            elif direction.lower() == "right":
                for _ in range(scroll_amount):
                    pyautogui.hscroll(120, x=center_x, y=center_y)
                    time.sleep(0.05)
            else:
                return {"status": "error", "action": "scroll", "index": index,
                        "message": f"Invalid scroll direction: {direction}. Use 'up', 'down', 'left', or 'right'"}

            logger.info(f"Scrolled element {index} {direction} at position ({center_x}, {center_y})")
            time.sleep(0.5)

            return {"status": "success", "action": "scroll", "index": index,
                    "direction": direction, "element_name": element_info.get('name', 'Unknown')}

        except Exception as e:
            logger.error(f"Error scrolling element {index}: {str(e)}")
            return {"status": "error", "action": "scroll", "index": index, "message": str(e)}

    def drag(self, start_x, start_y, end_x, end_y):
        """Drag mouse from start position to end position via Quartz events."""
        try:
            # Warp to start position — returns source for reuse
            source = self._warp_cursor_only(start_x, start_y)

            # Mouse down at start (same source)
            self._quartz_mouse_down(source, start_x, start_y)
            time.sleep(0.05)

            # Drag in steps (same source)
            steps = 20
            for i in range(1, steps + 1):
                progress = i / steps
                ix = int(start_x + (end_x - start_x) * progress)
                iy = int(start_y + (end_y - start_y) * progress)
                point = CGPointMake(float(ix), float(iy))
                drag_ev = CGEventCreateMouseEvent(
                    source, kCGEventLeftMouseDragged, point, kCGMouseButtonLeft
                )
                if drag_ev:
                    CGEventSetLocation(drag_ev, point)
                    CGEventPost(kCGHIDEventTap, drag_ev)
                time.sleep(0.015)

            # Mouse up at end (same source)
            self._quartz_mouse_up(source, end_x, end_y)
            time.sleep(0.1)

            logger.info(f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})")
            return {"status": "success", "action": "drag",
                    "start": (start_x, start_y), "end": (end_x, end_y)}

        except Exception as e:
            logger.error(f"Error dragging: {str(e)}")
            return {"status": "error", "action": "drag", "message": str(e)}

    def drag_drop(self, from_index, to_index):
        """Drag from one element to another by index (drag and drop)."""
        try:
            from_index = str(from_index)
            to_index = str(to_index)

            if from_index not in self.elements_mapping:
                return {"status": "error", "action": "drag_drop", "from_index": from_index,
                        "message": f"Source element index {from_index} not found"}

            if to_index not in self.elements_mapping:
                return {"status": "error", "action": "drag_drop", "to_index": to_index,
                        "message": f"Target element index {to_index} not found"}

            from_info = self.elements_mapping[from_index]
            to_info = self.elements_mapping[to_index]

            for label, idx, info in [("Source", from_index, from_info), ("Target", to_index, to_info)]:
                if info.get('visibility', 'full') == 'hidden':
                    clipped_by = info.get('clipped_by', 'unknown container')
                    return {"status": "error", "action": "drag_drop", "index": idx,
                            "message": f"{label} element is hidden (clipped by '{clipped_by}'). Scroll to make it visible first."}

            from_x, from_y = self._get_click_coords_for_element(from_info)
            to_x, to_y = self._get_click_coords_for_element(to_info)

            result = self.drag(from_x, from_y, to_x, to_y)

            if result.get("status") == "success":
                logger.info(f"Drag-dropped from element {from_index} to element {to_index}")
                return {"status": "success", "action": "drag_drop",
                        "from_index": from_index, "to_index": to_index,
                        "from_element": from_info.get('name', 'Unknown'),
                        "to_element": to_info.get('name', 'Unknown')}
            return result

        except Exception as e:
            logger.error(f"Error drag-dropping from {from_index} to {to_index}: {str(e)}")
            return {"status": "error", "action": "drag_drop", "message": str(e)}

    def canvas_input(self, text):
        """Type text directly into currently focused location (no element targeting)."""
        try:
            for char in text:
                if self.stop_event and self.stop_event.is_set():
                    logger.info("canvas_input interrupted by stop_event")
                    return {"status": "stopped", "action": "canvas_input",
                            "message": "Stopped by user"}
                pyautogui.write(char, interval=0.04)
            time.sleep(0.22)

            logger.info(f"Canvas input: typed '{text}' ({len(text)} chars)")
            return {"status": "success", "action": "canvas_input", "text": text,
                    "message": "verify yourself using visual"}

        except Exception as e:
            logger.error(f"canvas_input failed: {e}")
            return {"status": "error", "action": "canvas_input", "message": str(e)}