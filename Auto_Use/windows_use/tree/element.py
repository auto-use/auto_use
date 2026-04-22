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

import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pywinauto")
from pywinauto import Desktop, Application
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto import uia_element_info
import comtypes.client
from .ocr_detection import OCRScanner
import time
from win32api import RGB
import win32gui
import win32con
import win32api
from PIL import Image, ImageGrab, ImageDraw, ImageFont
import numpy as np
import os
import io
import base64
import threading
from collections import namedtuple
import ctypes
from ctypes import wintypes

# ========== CONFIGURATION ==========
# Toggle switch for screenshot capture
SCREENSHOT = True   # Set to False to only generate ui_elements.txt without screenshot
DEBUG = False             # Set to True to save files to debug folders, False for direct LLM only
FRONTEND = True    # Set to True when running from app.py to send annotated images to frontend

# Define Rect namedtuple once for reuse throughout module
Rect = namedtuple('Rect', ['left', 'top', 'right', 'bottom'])

# ========== PRIMARY MONITOR DETECTION ==========
user32 = ctypes.windll.user32

MONITOR_DEFAULTTONULL = 0
MONITORINFOF_PRIMARY = 1

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]

def is_on_primary_monitor(hwnd):
    """Check if window is on the primary monitor"""
    try:
        hmonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONULL)
        if not hmonitor:
            return False
        
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
            return False
        
        return (mi.dwFlags & MONITORINFOF_PRIMARY) != 0
    except:
        return False

# DWM cloaked check for UWP apps
dwmapi = ctypes.windll.dwmapi
DWMWA_CLOAKED = 14

def is_window_cloaked(hwnd):
    """Check if window is cloaked (hidden by DWM) - common for UWP apps like Settings"""
    try:
        cloaked = ctypes.c_int(0)
        result = dwmapi.DwmGetWindowAttribute(
            hwnd, 
            DWMWA_CLOAKED, 
            ctypes.byref(cloaked), 
            ctypes.sizeof(cloaked)
        )
        return result == 0 and cloaked.value != 0
    except:
        return False

def _xml_escape(text):
    """Escape special characters for XML attributes"""
    if not text:
        return ""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))

# Load raw UIA COM interface for parallel scanning
UIAutomationClient = comtypes.client.GetModule("UIAutomationCore.dll")
_uia = comtypes.client.CreateObject(
    "{ff48dba4-60ef-4201-aa87-54103eef594e}",
    interface=UIAutomationClient.IUIAutomation
)

# ========== LAYER DETECTION FUNCTIONS ==========
def detect_windows_overlay():
    """Check root UIA children for Windows overlays (Start, Search, Notifications, etc.)"""
    
    overlay_names = {
        "start": "Start Menu",
        "search": "Windows Search",
        "notification center": "Notification Center",
        "notifications": "Notifications",
        "action center": "Action Center",
        "quick settings": "Quick Settings",
        "windows shell experience host": "Windows Shell",
    }
    
    try:
        root = _uia.GetRootElement()
        walker = _uia.ControlViewWalker
        child = walker.GetFirstChildElement(root)
        
        while child:
            try:
                name = child.CurrentName or ""
                class_name = child.CurrentClassName or ""
                
                if class_name == "Windows.UI.Core.CoreWindow":
                    name_lower = name.lower().strip()
                    
                    if name_lower in overlay_names:
                        return (overlay_names[name_lower], "Windows.UI.Core.CoreWindow", child)
                
            except:
                pass
            
            child = walker.GetNextSiblingElement(child)
    except:
        pass
    
    return None


def detect_system_tray_overflow():
    """Check if system tray overflow window is visible"""
    
    overflow_hwnd = None
    
    def enum_callback(hwnd, _):
        nonlocal overflow_hwnd
        
        if not win32gui.IsWindowVisible(hwnd):
            return True
        
        try:
            class_name = win32gui.GetClassName(hwnd)
        except:
            return True
        
        if class_name in {"NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland"}:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = right - left
                height = bottom - top
                
                if width > 50 and height > 50 and left > -30000 and top > -30000:
                    overflow_hwnd = (hwnd, "System Tray Overflow", class_name)
                    return False
            except:
                pass
        
        return True
    
    win32gui.EnumWindows(enum_callback, None)
    
    return overflow_hwnd


def detect_popup():
    """Check if a popup/context menu is visible"""
    
    popup_classes = {
        "Microsoft.UI.Content.PopupWindowSiteBridge",
        "Xaml_WindowedPopupClass",
    }
    
    popup_hwnd = None
    
    def enum_callback(hwnd, _):
        nonlocal popup_hwnd
        
        if not win32gui.IsWindowVisible(hwnd):
            return True
        
        try:
            class_name = win32gui.GetClassName(hwnd)
        except:
            return True
        
        try:
            window_text = win32gui.GetWindowText(hwnd)
        except:
            window_text = ""
        
        if class_name in popup_classes:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = right - left
                height = bottom - top
                
                if width > 20 and height > 20 and left > -30000 and top > -30000:
                    popup_hwnd = (hwnd, window_text or "Context Menu", class_name)
                    return False
            except:
                pass
        
        if window_text.lower() in {"pop-uphost", "popuphost"}:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = right - left
                height = bottom - top
                
                if width > 20 and height > 20 and left > -30000 and top > -30000:
                    popup_hwnd = (hwnd, "Context Menu", class_name)
                    return False
            except:
                pass
        
        return True
    
    win32gui.EnumWindows(enum_callback, None)
    
    return popup_hwnd


def get_topmost_app():
    """Find topmost regular application window by Z-order"""
    
    screen_width = win32api.GetSystemMetrics(0)
    screen_height = win32api.GetSystemMetrics(1)
    
    skip_classes = {
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "Progman",
        "WorkerW",
        "NotifyIconOverflowWindow",
        "TopLevelWindowForOverflowXamlIsland",
        "Windows.UI.Core.CoreWindow",
        "XamlExplorerHostIslandWindow",
        "CEF-OSC-WIDGET",
        "Microsoft.UI.Content.PopupWindowSiteBridge",
        "Xaml_WindowedPopupClass",
    }
    
    skip_names = {
        "nvidia geforce overlay",
        "rzmonitoreforegroundwindow",
        "pop-uphost",
        "popuphost",
    }
    
    topmost_app = None
    desktop_hwnd = None
    
    def enum_callback(hwnd, _):
        nonlocal topmost_app, desktop_hwnd
        
        if topmost_app is not None:
            return True
        
        if not win32gui.IsWindowVisible(hwnd):
            return True
        
        try:
            class_name = win32gui.GetClassName(hwnd)
        except:
            return True
        
        if class_name in {"Progman", "WorkerW"}:
            if desktop_hwnd is None:
                desktop_hwnd = hwnd
            return True
        
        if class_name in skip_classes:
            return True
        
        try:
            window_text = win32gui.GetWindowText(hwnd)
        except:
            window_text = ""
        
        if window_text.lower() in skip_names:
            return True
        
        if not window_text.strip():
            return True
        
        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            if placement[1] == win32con.SW_SHOWMINIMIZED:
                return True
        except:
            return True
        
        # Skip cloaked windows (UWP apps that are hidden but have WS_VISIBLE)
        if is_window_cloaked(hwnd):
            return True
        
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
        except:
            return True
        
        if width < 100 or height < 100:
            return True
        
        # Skip windows not on primary monitor
        if not is_on_primary_monitor(hwnd):
            return True
        
        if left <= -30000 or top <= -30000:
            return True
        if right <= 0 or bottom <= 0:
            return True
        if left >= screen_width or top >= screen_height:
            return True
        
        # Skip windows mostly on secondary monitor (less than 100px visible on main)
        if left < 0 and right < 100:
            return True
        if top < 0 and bottom < 100:
            return True
        
        topmost_app = (hwnd, window_text, class_name)
        return True
    
    win32gui.EnumWindows(enum_callback, None)
    
    if topmost_app:
        return topmost_app
    elif desktop_hwnd:
        return (desktop_hwnd, "Desktop", "Progman")
    
    return None


def get_topmost_layers():
    """Get top layer and second layer if overlay is active"""
    
    result = {
        "top_layer": None,
        "second_layer": None
    }
    
    overlay = detect_windows_overlay()
    tray_overflow = detect_system_tray_overflow()
    popup = detect_popup()
    app = get_topmost_app()
    
    if overlay:
        result["top_layer"] = {"type": "overlay", "name": overlay[0], "class": overlay[1], "element": overlay[2], "hwnd": None}
        if app:
            result["second_layer"] = {"type": "app", "name": app[1], "class": app[2], "hwnd": app[0]}
    elif tray_overflow:
        hwnd, name, class_name = tray_overflow
        result["top_layer"] = {"type": "tray_overflow", "name": name, "class": class_name, "hwnd": hwnd}
        if app:
            result["second_layer"] = {"type": "app", "name": app[1], "class": app[2], "hwnd": app[0]}
    elif popup:
        hwnd, name, class_name = popup
        result["top_layer"] = {"type": "popup", "name": name, "class": class_name, "hwnd": hwnd}
        if app:
            result["second_layer"] = {"type": "app", "name": app[1], "class": app[2], "hwnd": app[0]}
    else:
        if app:
            result["top_layer"] = {"type": "app", "name": app[1], "class": app[2], "hwnd": app[0]}
    
    return result

ELEMENT_CONFIG = {
    "MenuItem": {
        "track": True,
        "uia_control_type": 50011,
        "win32_classes": [],
        "keyboard_focusable": True,
        "is_enabled_check": True,
        "fallback": ["name", "automation_id"]
    },
    "Menu": {
        "track": True,
        "uia_control_type": 50009,
        "win32_classes": [],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "Button": {
        "track": True,
        "uia_control_type": 50000,
        "win32_classes": ["Button"],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id", "legacy_description", "class_name"]
    },
    "TabItem": {
        "track": True,
        "uia_control_type": 50019,
        "win32_classes": ["SysTabControl32"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "TreeItem": {
        "track": True,
        "uia_control_type": 50024,
        "win32_classes": ["SysTreeView32"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "CheckBox": {
        "track": True,
        "uia_control_type": 50002,
        "win32_classes": ["Button"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "ListItem": {
        "track": True,
        "uia_control_type": 50007,
        "win32_classes": ["ListBox", "SysListView32"],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id"]
    },
    "Document": {
        "track": True,
        "uia_control_type": 50030,
        "win32_classes": ["RichEdit", "RichEdit20W", "RichEdit20A"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "ComboBox": {
        "track": True,
        "uia_control_type": 50003,
        "win32_classes": ["ComboBox"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id", "class_name"]
    },
    "RadioButton": {
        "track": True,
        "uia_control_type": 50013,
        "win32_classes": ["Button"],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id"]
    },
    "Edit": {
        "track": True,
        "uia_control_type": 50004,
        "win32_classes": ["Edit"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "Group": {
        "track": True,
        "uia_control_type": 50026,
        "win32_classes": ["Button"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "Hyperlink": {
        "track": True,
        "uia_control_type": 50005,
        "win32_classes": ["SysLink"],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id", "class_name"]
    },
    "Pane": {
        "track": True,
        "uia_control_type": 50033,
        "win32_classes": [],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "Image": {
        "track": True,
        "uia_control_type": 50006,
        "win32_classes": ["Static"],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id", "class_name"]
    },
    "SplitButton": {
        "track": True,
        "uia_control_type": 50031,
        "win32_classes": [],
        "keyboard_focusable": True,
        "fallback": ["name", "automation_id"]
    },
    "DataItem": {
        "track": True,
        "uia_control_type": 50029,
        "win32_classes": [],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id"]
    },
    "Text": {
        "track": True,
        "uia_control_type": 50020,
        "win32_classes": ["Static"],
        "keyboard_focusable": False,
        "fallback": ["name", "automation_id"]
    }
    # Add more element types here as needed
}

# Single magenta color for all elements in screenshot
BOX_COLOR = (255, 0, 255)  # Bright magenta for all boxes
NUMBER_COLOR = (255, 0, 255)  # Same magenta for numbers

# Browser configuration for loading detection
BROWSER_CONFIG = {
    "chrome": {
        "app_name_contains": "Google Chrome"
        # Chrome uses FullDescription check ("Stop loading this page" = loading) instead of template matching
    },
    "edge": {
        "app_name_contains": "Edge"
        # Edge uses FullDescription check ("Stop (Esc)" = loading) instead of template matching
    },
    "firefox": {
        "app_name_contains": "Firefox"
        # Firefox uses button name check ("Stop" = loading) instead of template matching
    },
    "opera": {
        "app_name_contains": "Opera"
        # Opera uses button name check ("Stop" = loading) instead of template matching
    },
    "brave": {
        "app_name_contains": "Brave"
        # Brave uses FullDescription check ("Stop loading this page" = loading) - same as Chrome
    }
}

# ========== SCANNER CLASS ==========
class UIElementScanner:
    def __init__(self, config, frontend_callback=None):
        self.config = config
        self.desktop = Desktop(backend="uia")
        self.found_elements = {}  # Dictionary to store elements by type
        self.element_tree = []  # Hierarchical tree structure for active window (UIA)
        self.win32_elements = []  # Flat list for Win32 scan results
        self.raw_uia_elements = []  # Flat list for raw UIA COM scan results
        self.taskbar_tree = []  # Hierarchical tree structure for taskbar
        self.element_index = 0  # Global index counter
        self.win32_thread = None  # Thread handle for parallel Win32 scan
        self.raw_uia_thread = None  # Thread handle for parallel raw UIA scan
        self.ocr_thread = None  # Thread handle for parallel OCR scan
        self.ocr_scanner = None  # OCR scanner instance
        self.ocr_words = []  # Raw OCR results (filtered later)
        self.disabled_button_rects = []  # Rects of disabled buttons (block their OCR shadows)
        self.application_name = "Desktop"  # Store the application name
        self.elements_to_draw = []  # List for screenshot bounding boxes
        self.elements_mapping = {}  # Mapping of index to element for controller
        self.app_rect = None  # Store application window bounding box
        self.frontend_callback = frontend_callback  # Callback to send images to frontend
        
        # Layer-based scanning storage
        self.top_layer_tree = []  # Elements from top layer
        self.second_layer_tree = []  # Elements from second layer (if exists)
        self.top_layer_info = None  # Metadata about top layer
        self.second_layer_info = None  # Metadata about second layer
        self._is_browser = False  # Cached browser detection result
        
        # Build reverse lookup: uia_control_type -> element_type name
        self.uia_type_map = {}
        for element_type, cfg in config.items():
            if cfg.get("track") and "uia_control_type" in cfg:
                self.uia_type_map[cfg["uia_control_type"]] = element_type
        
        # Build reverse lookup: win32_class -> element_type name
        self.win32_class_map = {}
        for element_type, cfg in config.items():
            if cfg.get("track") and "win32_classes" in cfg:
                for win32_class in cfg["win32_classes"]:
                    self.win32_class_map[win32_class] = element_type
        
        # Initialize storage for each element type
        for element_type in config:
            if config[element_type]["track"]:
                self.found_elements[element_type] = []
        
        # Create debug directories if DEBUG is enabled
        if DEBUG:
            os.makedirs("debug/element", exist_ok=True)
            os.makedirs("debug/screenshot", exist_ok=True)

    def _is_browser_app(self):
        """Check if the current application is a web browser"""
        browser_keywords = ["chrome", "firefox", "edge", "opera", "brave", "safari", "vivaldi", "browser"]
        app_name_lower = self.application_name.lower()
        return any(browser in app_name_lower for browser in browser_keywords)
    
    def _detect_browser_popup(self, children):
        """Check if Document children contain an open dropdown/popup (ListItems, MenuItems, Menu)"""
        popup_types = {"ListItem", "MenuItem", "Menu"}
        popup_items = [c for c in children if c["type"] in popup_types]
        # 2+ popup-type direct children = likely an open dropdown
        return len(popup_items) >= 2
    
    def _detect_browser_type(self):
        """
        Detect which browser is active based on application name.
        Returns browser key from BROWSER_CONFIG or None if not found.
        """
        if not self._is_browser_app():
            return None
        
        # Check against each browser config
        for browser_key, config in BROWSER_CONFIG.items():
            if config["app_name_contains"] in self.application_name:
                return browser_key
        
        return None

    def _scan_layer(self, layer_info, target_tree, is_top_layer=True):
        """Scan a detected layer (overlay, popup, tray_overflow, or app)"""
        layer_type = layer_info["type"]
        layer_name = layer_info["name"]
        
        if layer_type == "overlay":
            # Windows overlay (Start Menu, Search, etc.) - use raw UIA element
            raw_element = layer_info.get("element")
            if raw_element:
                try:
                    # Wrap raw UIA element for pywinauto compatibility
                    child_info = uia_element_info.UIAElementInfo(raw_element)
                    wrapped_element = UIAWrapper(child_info)
                    
                    # Get bounding rect for app_rect
                    try:
                        rect = raw_element.CurrentBoundingRectangle
                        self.app_rect = Rect(rect.left, rect.top, rect.right, rect.bottom)
                    except:
                        pass
                    
                    self._scan_element_recursive(wrapped_element, target_tree, 0, skip_visibility=False)
                except Exception as e:
                    pass
        
        elif layer_type in ["app", "tray_overflow", "popup"]:
            # Regular window - use hwnd
            hwnd = layer_info.get("hwnd")
            if hwnd:
                try:
                    app = Application(backend="uia").connect(handle=hwnd)
                    window = app.window(handle=hwnd)
                    
                    self.app_rect = window.rectangle()
                    
                    # Prime browser accessibility tree before scanning
                    # Chrome/Chromium lazy-loads UIA tree - a quick query wakes it up
                    if is_top_layer and self._is_browser_app():
                        try:
                            # Force UIA tree population by querying descendants
                            _ = window.descendants(depth=1)
                            time.sleep(0.1)
                        except:
                            pass
                    
                    # Start parallel scans only for top layer
                    if is_top_layer:
                        # Start Win32 scan in parallel
                        self.win32_thread = threading.Thread(target=self._scan_with_win32_parallel, args=(layer_name,))
                        self.win32_thread.start()
                        
                        # Start raw UIA scan in parallel
                        self.raw_uia_thread = threading.Thread(target=self._scan_with_raw_uia_parallel, args=(hwnd,))
                        self.raw_uia_thread.start()
                    
                    self._scan_element_recursive(window, target_tree, 0, skip_visibility=False)
                    
                except Exception as e:
                    # Fallback to desktop scan if app connection fails
                    if is_top_layer and layer_type == "app" and layer_info.get("class") == "Progman":
                        self._scan_desktop()
                        target_tree.extend(self.element_tree)
    
    def _is_browser_loading(self, browser_type=None):
        """Check if browser is loading using dual template comparison"""
        # Auto-detect browser type if not provided
        if browser_type is None:
            browser_type = self._detect_browser_type()
        
        if browser_type is None or browser_type not in BROWSER_CONFIG:
            return False
        
        # Special handling for Opera and Firefox - just check button name
        # "Stop" button = loading, "Reload" button = loaded
        if browser_type in ["opera", "firefox"]:
            try:
                window = self.desktop.window(active_only=True)
                buttons = window.descendants(control_type="Button")
                for btn in buttons:
                    try:
                        name = btn.element_info.name or ""
                        if name == "Stop":
                            return True  # Loading
                    except:
                        continue
                return False  # Not loading (Reload button present or neither found)
            except:
                return False
        
        # Special handling for Chrome and Brave - check FullDescription of Reload button
        # "Stop loading this page" = loading, "Reload this page" = loaded
        if browser_type in ["chrome", "brave"]:
            try:
                window = self.desktop.window(active_only=True)
                buttons = window.descendants(control_type="Button")
                for btn in buttons:
                    try:
                        name = btn.element_info.name or ""
                        if name == "Reload":
                            # Get FullDescription property (UIA_FullDescriptionPropertyId = 30159)
                            raw_element = btn.element_info.element
                            full_desc = str(raw_element.GetCurrentPropertyValue(30159) or "")
                            if "Stop" in full_desc:
                                return True  # Loading
                            return False  # Loaded
                    except:
                        continue
                return False  # Button not found
            except:
                return False
        
        # Special handling for Edge - check FullDescription of Refresh button
        # "Stop (Esc)" = loading, "Refresh (Ctrl+R)" = loaded
        if browser_type == "edge":
            try:
                window = self.desktop.window(active_only=True)
                buttons = window.descendants(control_type="Button")
                for btn in buttons:
                    try:
                        name = btn.element_info.name or ""
                        if name == "Refresh":
                            # Get FullDescription property (UIA_FullDescriptionPropertyId = 30159)
                            raw_element = btn.element_info.element
                            full_desc = str(raw_element.GetCurrentPropertyValue(30159) or "")
                            if "Stop" in full_desc:
                                return True  # Loading
                            return False  # Loaded
                    except:
                        continue
                return False  # Button not found
            except:
                return False

        return False

    def _is_partially_visible(self, rect, app_rect):
        """
        Check if element rectangle extends beyond application window bounds
        Args:
            rect: Element's rectangle
            app_rect: Application window's rectangle
        Returns: 'full' if fully within app bounds, 'partial' if extends beyond
        """
        # If no app_rect provided, fall back to screen bounds check
        if app_rect is None:
            screen_width = win32api.GetSystemMetrics(0)
            screen_height = win32api.GetSystemMetrics(1)
            # Use screen as the boundary
            if (rect.left < 0 or rect.top < 0 or 
                rect.right > screen_width or rect.bottom > screen_height):
                return 'partial'
            return 'full'
        
        # Check if element extends beyond application window bounds
        if (rect.left < app_rect.left or 
            rect.top < app_rect.top or 
            rect.right > app_rect.right or 
            rect.bottom > app_rect.bottom):
            return 'partial'
        
        # Additional check: if element is very close to app edges (might appear cut off)
        edge_threshold = 5  # pixels
        if (rect.left < app_rect.left + edge_threshold or 
            rect.top < app_rect.top + edge_threshold or 
            rect.right > app_rect.right - edge_threshold or 
            rect.bottom > app_rect.bottom - edge_threshold):
            return 'partial'
        
        return 'full'

    def _get_clipping_ancestors(self, element):
        """
        Walk up parent chain and collect clipping containers.
        Returns: list of tuples (rect, name, control_type) for ancestors that clip content
        """
        clipping_ancestors = []
        
        # Get the element's own rect for validation
        try:
            element_rect = element.rectangle()
        except:
            return clipping_ancestors
        
        # Get screen bounds for validation
        screen_width = win32api.GetSystemMetrics(0)
        screen_height = win32api.GetSystemMetrics(1)
        
        try:
            current = element.parent()
            
            while current is not None:
                try:
                    control_type = current.element_info.control_type
                    
                    # Stop at window/document level - they don't clip in the way we care about
                    if control_type in {"Window", "Document", "Desktop"}:
                        break
                    
                    ancestor_rect = current.rectangle()
                    
                    # ===== VALIDATION: Is this ancestor rect trustworthy? =====
                    
                    # Check 1: Ancestor rect must have reasonable size
                    ancestor_width = ancestor_rect.right - ancestor_rect.left
                    ancestor_height = ancestor_rect.bottom - ancestor_rect.top
                    if ancestor_width <= 10 or ancestor_height <= 10:
                        current = current.parent()
                        continue
                    
                    # Check 2: Ancestor rect must be on screen (not garbage values)
                    if (ancestor_rect.right <= 0 or ancestor_rect.bottom <= 0 or
                        ancestor_rect.left >= screen_width or ancestor_rect.top >= screen_height):
                        current = current.parent()
                        continue
                    
                    # Check 3: Ancestor rect must OVERLAP with element rect
                    # If ancestor doesn't even overlap element, its rect is garbage
                    overlap_left = max(element_rect.left, ancestor_rect.left)
                    overlap_top = max(element_rect.top, ancestor_rect.top)
                    overlap_right = min(element_rect.right, ancestor_rect.right)
                    overlap_bottom = min(element_rect.bottom, ancestor_rect.bottom)
                    
                    has_overlap = (overlap_right > overlap_left and overlap_bottom > overlap_top)
                    
                    if not has_overlap:
                        # Ancestor rect doesn't contain/overlap element - skip it
                        current = current.parent()
                        continue
                    
                    # Check 4: Ancestor must actually be SMALLER than element in at least one dimension
                    # to be a real clipper (otherwise it's just a container, not clipping)
                    is_actually_clipping = (
                        ancestor_rect.left > element_rect.left or
                        ancestor_rect.top > element_rect.top or
                        ancestor_rect.right < element_rect.right or
                        ancestor_rect.bottom < element_rect.bottom
                    )
                    
                    if not is_actually_clipping:
                        # Ancestor fully contains element - not clipping it
                        current = current.parent()
                        continue
                    
                    # ===== Now check if this is a clipping container type =====
                    
                    is_clipping = False
                    
                    # Method 1: Has ScrollPattern (definite clipper)
                    try:
                        raw_element = current.element_info.element
                        # UIA_ScrollPatternId = 10004
                        scroll_pattern = raw_element.GetCurrentPattern(10004)
                        if scroll_pattern:
                            is_clipping = True
                    except:
                        pass
                    
                    # Method 2: Is a known clipping control type
                    # Only use control type as hint if rect validation passed
                    clipping_types = {"List", "ListBox", "Menu", "ComboBox", "ScrollViewer", "Tree"}
                    if not is_clipping and control_type in clipping_types:
                        is_clipping = True
                    
                    # Method 3: Even if not a known type, if ancestor is smaller and clips element, count it
                    # This catches custom containers that clip but aren't standard types
                    if not is_clipping and is_actually_clipping:
                        # Only count as clipping if it's significantly clipping (more than 5% of element)
                        element_area = (element_rect.right - element_rect.left) * (element_rect.bottom - element_rect.top)
                        overlap_area = (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
                        if element_area > 0 and overlap_area < element_area * 0.95:
                            is_clipping = True
                    
                    if is_clipping:
                        # Get a name for this container
                        try:
                            name = current.element_info.name or control_type
                        except:
                            name = control_type
                        
                        clipping_ancestors.append((ancestor_rect, name, control_type))
                    
                    # Move to next parent
                    current = current.parent()
                    
                except Exception:
                    break
                    
        except Exception:
            pass
        
        return clipping_ancestors

    def _calculate_visible_rect(self, element_rect, clipping_ancestors):
        """
        Calculate the actual visible rectangle by intersecting with all clipping ancestors.
        
        Args:
            element_rect: The element's full bounding rectangle
            clipping_ancestors: List of (rect, name, control_type) from _get_clipping_ancestors
            
        Returns:
            tuple: (visible_rect or None, clipped_by_name or None)
                   visible_rect is None if element is fully hidden
        """
        if not clipping_ancestors:
            return element_rect, None
        
        # Start with element's full rect
        visible_left = element_rect.left
        visible_top = element_rect.top
        visible_right = element_rect.right
        visible_bottom = element_rect.bottom
        
        first_clipper_name = None
        
        for ancestor_rect, ancestor_name, control_type in clipping_ancestors:
            # Calculate intersection
            new_left = max(visible_left, ancestor_rect.left)
            new_top = max(visible_top, ancestor_rect.top)
            new_right = min(visible_right, ancestor_rect.right)
            new_bottom = min(visible_bottom, ancestor_rect.bottom)
            
            # Check if this ancestor actually clips the element
            if (new_left > visible_left or new_top > visible_top or 
                new_right < visible_right or new_bottom < visible_bottom):
                # This ancestor is clipping - record it as the clipper if first one
                if first_clipper_name is None:
                    first_clipper_name = ancestor_name
            
            visible_left = new_left
            visible_top = new_top
            visible_right = new_right
            visible_bottom = new_bottom
            
            # Check if fully clipped (no visible area remains)
            if visible_right <= visible_left or visible_bottom <= visible_top:
                return None, first_clipper_name or ancestor_name
        
        # Create visible rect using module-level Rect namedtuple
        visible_rect = Rect(visible_left, visible_top, visible_right, visible_bottom)
        
        return visible_rect, first_clipper_name

    def _compute_visibility(self, element, element_rect):
        """
        Compute true visibility of an element based on ancestor clipping.
        
        Args:
            element: The pywinauto element
            element_rect: The element's bounding rectangle
            
        Returns:
            tuple: (visibility_status, visible_rect, clipped_by)
                   visibility_status: "full", "partial:XX%", or "hidden"
                   visible_rect: The actual visible rectangle (or None if hidden)
                   clipped_by: Name of the clipping container (or None if full)
        """
        # Get clipping ancestors
        clipping_ancestors = self._get_clipping_ancestors(element)
        
        # Calculate visible rect
        visible_rect, clipped_by = self._calculate_visible_rect(element_rect, clipping_ancestors)
        
        # Also check against application window bounds (app_rect)
        if visible_rect is not None and self.app_rect is not None:
            new_left = max(visible_rect.left, self.app_rect.left)
            new_top = max(visible_rect.top, self.app_rect.top)
            new_right = min(visible_rect.right, self.app_rect.right)
            new_bottom = min(visible_rect.bottom, self.app_rect.bottom)
            
            # Check if app window is clipping this element
            if (new_left > visible_rect.left or new_top > visible_rect.top or 
                new_right < visible_rect.right or new_bottom < visible_rect.bottom):
                if clipped_by is None:
                    clipped_by = self.application_name
            
            # Update visible_rect or set to None if no visible area
            if new_right > new_left and new_bottom > new_top:
                visible_rect = Rect(new_left, new_top, new_right, new_bottom)
            else:
                visible_rect = None
        
        # Calculate element's total area
        total_width = element_rect.right - element_rect.left
        total_height = element_rect.bottom - element_rect.top
        total_area = total_width * total_height
        
        # Handle zero area elements
        if total_area <= 0:
            return "hidden", None, clipped_by
        
        # If no visible rect, element is fully hidden
        if visible_rect is None:
            return "hidden", None, clipped_by
        
        # Calculate visible area
        visible_width = visible_rect.right - visible_rect.left
        visible_height = visible_rect.bottom - visible_rect.top
        visible_area = visible_width * visible_height
        
        # Handle edge case where visible dimensions are negative/zero
        if visible_area <= 0:
            return "hidden", None, clipped_by
        
        # Calculate percentage
        percentage = (visible_area / total_area) * 100
        
        # Classify visibility
        if percentage >= 95:
            return "full", visible_rect, None
        elif percentage > 0:
            return f"partial:{int(percentage)}%", visible_rect, clipped_by
        else:
            return "hidden", None, clipped_by

    def scan_elements(self):
        """Scan the active window and taskbar for configured element types using layer-based detection"""
        
        # Clear previous scans
        self.element_tree = []
        self.taskbar_tree = []
        self.win32_elements = []  # Clear Win32 parallel scan results
        self.raw_uia_elements = []  # Clear raw UIA parallel scan results
        self.ocr_words = []  # Clear OCR results
        self.disabled_button_rects = []  # Clear disabled button rects
        self.element_index = 0
        self.application_name = "Desktop"  # Default application name
        self.elements_to_draw = []  # Clear screenshot elements
        self.elements_mapping = {}  # Clear elements mapping
        self.app_rect = None  # Reset application rectangle
        
        # Clear layer storage
        self.top_layer_tree = []
        self.second_layer_tree = []
        self.top_layer_info = None
        self.second_layer_info = None
        
        # Start OCR scan in parallel (full screen, thread-safe)
        self.ocr_scanner = OCRScanner()
        self.ocr_thread = threading.Thread(target=self.ocr_scanner.scan)
        self.ocr_thread.start()
        
        # Detect visible layers using visibility-based detection (no focus required)
        layers = get_topmost_layers()
        self.top_layer_info = layers["top_layer"]
        self.second_layer_info = layers["second_layer"]
        
        # Scan top layer
        if self.top_layer_info:
            self.application_name = self.top_layer_info["name"]
            self._is_browser = self._is_browser_app()  # Cache browser detection
            self._scan_layer(self.top_layer_info, self.top_layer_tree, is_top_layer=True)
        else:
            # Fallback: scan desktop if no layer detected
            self.application_name = "Desktop"
            self.top_layer_info = {"type": "app", "name": "Desktop", "class": "Progman", "hwnd": None}
            self._scan_desktop()
            self.top_layer_tree = self.element_tree.copy()
        
        # Scan second layer (if exists)
        if self.second_layer_info:
            self._scan_layer(self.second_layer_info, self.second_layer_tree, is_top_layer=False)
        
        # Combine results: element_tree = top_layer
        self.element_tree = self.top_layer_tree.copy()
        
        # Set application_name from top layer for compatibility
        if self.top_layer_info:
            self.application_name = self.top_layer_info["name"]
        
        # Check if browser is loading and wait until loaded, then rescan
        browser_type = self._detect_browser_type()
        if browser_type:
            if self._is_browser_loading(browser_type):
                browser_name = BROWSER_CONFIG[browser_type]["app_name_contains"]
                print(f"{browser_name} is loading... waiting")
                while self._is_browser_loading(browser_type):
                    time.sleep(0.25)
                print("Browser loaded. Rescanning...")
                
                # Reset state for rescan
                self.top_layer_tree = []
                self.second_layer_tree = []
                self.element_tree = []
                self.win32_elements = []
                self.raw_uia_elements = []
                self.ocr_words = []
                self.disabled_button_rects = []
                self.element_index = 0
                self.elements_to_draw = []
                self.elements_mapping = {}
                
                # Restart OCR scan (previous one captured loading state)
                if self.ocr_thread is not None:
                    self.ocr_thread.join()
                self.ocr_scanner = OCRScanner()
                self.ocr_thread = threading.Thread(target=self.ocr_scanner.scan)
                self.ocr_thread.start()
                
                # Rescan using layer-based approach
                if self.top_layer_info:
                    self._scan_layer(self.top_layer_info, self.top_layer_tree, is_top_layer=True)
                
                if self.second_layer_info:
                    self._scan_layer(self.second_layer_info, self.second_layer_tree, is_top_layer=False)
                
                # Combine results
                self.element_tree = self.top_layer_tree.copy()
                
                # Wait for parallel threads
                if self.win32_thread is not None:
                    self.win32_thread.join()
                    self.win32_thread = None
                if self.raw_uia_thread is not None:
                    self.raw_uia_thread.join()
                    self.raw_uia_thread = None
                
                # Merge results
                self._dedupe_and_merge()
        
        # Wait for Win32 thread to complete
        if self.win32_thread is not None:
            self.win32_thread.join()
            self.win32_thread = None
        
        # Wait for raw UIA thread to complete
        if self.raw_uia_thread is not None:
            self.raw_uia_thread.join()
            self.raw_uia_thread = None
        
        # Merge and deduplicate all results (merges into element_tree)
        self._dedupe_and_merge()
            
        # Always scan the taskbar before OCR filtering so taskbar rects are available
        try:
            taskbar = self.desktop.window(class_name="Shell_TrayWnd")
            self._scan_element_recursive(taskbar, self.taskbar_tree, 0, skip_visibility=True)
        except Exception as e:
            pass
        
        # Wait for OCR thread to complete
        if self.ocr_thread is not None:
            self.ocr_thread.join()
            self.ocr_thread = None
            self.ocr_words = self.ocr_scanner.get_lines()
        
        # Filter OCR results against UIA elements, merge survivors into tree
        self._filter_and_merge_ocr()
        
        # Re-index entire tree in document order for continuous numbering
        self.element_index = 0
        self.elements_mapping = {}
        self._reindex_tree(self.element_tree)
        self._reindex_tree(self.taskbar_tree)
        
        # Rebuild elements_to_draw with updated indices
        self.elements_to_draw = []
        self._rebuild_draw_list(self.element_tree)
        self._rebuild_draw_list(self.taskbar_tree)
        
        # Sync merged results back to top_layer_tree for save_to_file()
        self.top_layer_tree = self.element_tree.copy()
        
        # Only save to file if DEBUG is enabled
        if DEBUG:
            self.save_to_file()

    def _filter_and_merge_ocr(self):
        """Filter OCR lines against UIA elements, nest survivors into the tree.
        Only leaf element rects (no children) claim screen space. Parent containers
        are structural wrappers — gaps between their children are where OCR fills in.
        Surviving OCR lines are inserted into the deepest matching container rather
        than appended flat at the end.
        """
        if not self.ocr_words:
            return
        
        # Collect only leaf element rects (elements with no children actually claim screen space)
        leaf_rects = []
        self._collect_leaf_rects(self.element_tree, leaf_rects)
        self._collect_leaf_rects(self.taskbar_tree, leaf_rects)
        leaf_rects.extend(self.disabled_button_rects)
        
        # Filter OCR lines: discard if overlapping a detected leaf element, keep otherwise
        kept_lines = []
        for line in self.ocr_words:
            cx = (line["left"] + line["right"]) // 2
            cy = (line["top"] + line["bottom"]) // 2
            
            overlaps_leaf = False
            for rect in leaf_rects:
                if rect.left <= cx <= rect.right and rect.top <= cy <= rect.bottom:
                    overlaps_leaf = True
                    break
            
            if not overlaps_leaf:
                kept_lines.append(line)
        
        # Nest each surviving OCR line into the deepest matching container in the tree
        for line in kept_lines:
            self.element_index += 1
            line_rect = Rect(line["left"], line["top"], line["right"], line["bottom"])
            
            element_info = {
                "element": None,
                "name": line["text"],
                "aria_role": "",
                "type": "OCR_TEXT",
                "active": True,
                "index": self.element_index,
                "value": None,
                "actions": None,
                "visibility": "full",
                "clipped_by": None,
                "rect": line_rect,
                "visible_rect": line_rect,
                "children": [],
                "source": "ocr"
            }
            
            # Find deepest container and insert there
            cx = (line["left"] + line["right"]) // 2
            cy = (line["top"] + line["bottom"]) // 2
            target_list = self._find_deepest_container(self.element_tree, cx, cy)
            target_list.append(element_info)
            
            # Add to elements mapping for controller (index updated later by reindex)
            self.elements_mapping[str(self.element_index)] = {
                'element': None,
                'rect': line_rect,
                'visible_rect': line_rect,
                'name': line["text"],
                'aria_role': '',
                'type': 'OCR_TEXT',
                'value': None,
                'visibility': 'full',
                'clipped_by': None
            }
            
            # Add to screenshot draw list
            self.elements_to_draw.append({
                "rect": line_rect,
                "index": self.element_index,
                "depth": 0,
                "visibility": "full",
                "source": "ocr"
            })
    
    def _reindex_tree(self, tree_list):
        """Walk tree in document order and assign continuous indices."""
        for item in tree_list:
            self.element_index += 1
            item["index"] = self.element_index
            
            # Rebuild elements_mapping with new index
            self.elements_mapping[str(self.element_index)] = {
                'element': item.get('element'),
                'rect': item.get('rect'),
                'visible_rect': item.get('visible_rect'),
                'name': item.get('name', ''),
                'aria_role': item.get('aria_role', ''),
                'type': item.get('type', ''),
                'value': item.get('value'),
                'visibility': item.get('visibility', 'full'),
                'clipped_by': item.get('clipped_by')
            }
            
            if item.get("browser_top_layer") is not None:
                self._reindex_tree(item["browser_top_layer"])
                self._reindex_tree(item["browser_second_layer"])
            elif item.get("children"):
                self._reindex_tree(item["children"])

    def _rebuild_draw_list(self, tree_list, depth=0):
        """Rebuild elements_to_draw from tree with updated indices."""
        for item in tree_list:
            rect = item.get("rect") or item.get("visible_rect")
            if rect:
                self.elements_to_draw.append({
                    "rect": rect,
                    "index": item["index"],
                    "depth": depth,
                    "visibility": item.get("visibility", "full"),
                    "source": item.get("source", "")
                })
            if item.get("browser_top_layer") is not None:
                self._rebuild_draw_list(item["browser_top_layer"], depth + 1)
                self._rebuild_draw_list(item["browser_second_layer"], depth + 1)
            elif item.get("children"):
                self._rebuild_draw_list(item["children"], depth + 1)

    def _find_deepest_container(self, tree_list, cx, cy):
        """Find the deepest element whose rect contains the point (cx, cy).
        Returns the children list of that element, or the top-level tree_list
        if no container claims the point. Also checks browser_second_layer.
        """
        for item in tree_list:
            rect = item.get("rect") or item.get("visible_rect")
            if not rect:
                continue
            
            if rect.left <= cx <= rect.right and rect.top <= cy <= rect.bottom:
                # Point is inside this element — try to go deeper
                
                # Check browser_second_layer first (OCR fills web page gaps)
                if item.get("browser_second_layer") is not None:
                    deeper = self._find_deepest_container(item["browser_second_layer"], cx, cy)
                    if deeper is not item["browser_second_layer"]:
                        return deeper
                    # Landed in browser_second_layer but no deeper match — nest here
                    return item["browser_second_layer"]
                
                # Check regular children
                if item.get("children"):
                    deeper = self._find_deepest_container(item["children"], cx, cy)
                    if deeper is not item["children"]:
                        return deeper
                    # Children exist but none claimed the point — nest among siblings
                    return item["children"]
                
                # Leaf element that contains the point — nest as its child
                return item.setdefault("children", [])
        
        # No element in this list contains the point — caller decides
        return tree_list
    
    _STRUCTURAL_CONTAINER_TYPES = {"Pane", "Document", "Group", "Edit"}

    def _collect_leaf_rects(self, tree_list, rects):
        """Recursively collect rects for OCR overlap checking.
        Structural types (Pane, Document, Group) never claim screen space.
        Edit is structural only when it has no value (content container like
        rich text editors). Edits with a value are real textboxes — collect rect.
        All other element types always collect their rect.
        """
        for item in tree_list:
            has_children = bool(item.get("children"))
            elem_type = item["type"]
            is_structural = elem_type in self._STRUCTURAL_CONTAINER_TYPES

            if is_structural:
                if elem_type == "Edit" and item.get("value") and not has_children:
                    rect = item.get("rect") or item.get("visible_rect")
                    if rect:
                        rects.append(rect)
                if has_children:
                    self._collect_leaf_rects(item["children"], rects)
            else:
                rect = item.get("rect") or item.get("visible_rect")
                if rect:
                    rects.append(rect)
                if has_children:
                    self._collect_leaf_rects(item["children"], rects)

    def _dedupe_and_merge(self):
        """Deduplicate elements from UIA, Win32, and raw UIA by coordinates, then merge into unified tree"""
        if not self.win32_elements and not self.raw_uia_elements:
            return  # Nothing to merge
        
        # Collect all UIA element rects for comparison
        uia_rects = []
        self._collect_rects_recursive(self.element_tree, uia_rects)
        
        # Track all merged rects (UIA + newly added)
        all_rects = list(uia_rects)
        
        # Flatten Win32 tree for deduplication check
        win32_flat = []
        self._flatten_win32_tree(self.win32_elements, win32_flat)
        
        # Check each Win32 element against existing rects
        for win32_elem in win32_flat:
            win32_rect = win32_elem["rect"]
            is_duplicate = False
            
            for existing_rect in all_rects:
                if self._rects_match(win32_rect, existing_rect, tolerance=5):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                # Assign index and add to tree
                self.element_index += 1
                win32_elem["index"] = self.element_index
                
                # Track this rect
                all_rects.append(win32_rect)
                
                # Add to elements mapping for controller
                self.elements_mapping[str(self.element_index)] = {
                    'element': win32_elem.get("element"),
                    'rect': win32_rect,
                    'visible_rect': win32_elem.get("visible_rect", win32_rect),
                    'name': win32_elem.get("name", ""),
                    'aria_role': win32_elem.get("aria_role", ""),
                    'type': win32_elem.get("type", ""),
                    'value': win32_elem.get("value"),
                    'visibility': win32_elem.get("visibility", "full"),
                    'clipped_by': win32_elem.get("clipped_by")
                }
                
                # Clean up temporary keys used for deduplication
                if "rect" in win32_elem:
                    del win32_elem["rect"]
                if "source" in win32_elem:
                    del win32_elem["source"]
                
                self.element_tree.append(win32_elem)
                
                # Add to found_elements for summary
                element_type = win32_elem["type"]
                if element_type not in self.found_elements:
                    self.found_elements[element_type] = []
                self.found_elements[element_type].append(win32_elem)
                
                # Add to screenshot draw list
                if SCREENSHOT:
                    self.elements_to_draw.append({
                        "rect": win32_elem["visible_rect"],
                        "index": win32_elem["index"],
                        "depth": 0,
                        "visibility": win32_elem.get("visibility", "full")
                    })
        
        # Flatten raw UIA list for deduplication check
        raw_uia_flat = []
        self._flatten_raw_uia_list(self.raw_uia_elements, raw_uia_flat)
        
        # Check each raw UIA element against all existing rects
        for raw_elem in raw_uia_flat:
            raw_rect = raw_elem["rect"]
            is_duplicate = False
            
            for existing_rect in all_rects:
                if self._rects_match(raw_rect, existing_rect, tolerance=5):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                # Assign index and add to tree
                self.element_index += 1
                raw_elem["index"] = self.element_index
                
                # Track this rect
                all_rects.append(raw_rect)
                
                # Add to elements mapping for controller
                self.elements_mapping[str(self.element_index)] = {
                    'element': raw_elem.get("element"),
                    'rect': raw_rect,
                    'visible_rect': raw_elem.get("visible_rect", raw_rect),
                    'name': raw_elem.get("name", ""),
                    'aria_role': raw_elem.get("aria_role", ""),
                    'type': raw_elem.get("type", ""),
                    'value': raw_elem.get("value"),
                    'visibility': raw_elem.get("visibility", "full"),
                    'clipped_by': raw_elem.get("clipped_by")
                }
                
                # Clean up temporary keys used for deduplication
                if "rect" in raw_elem:
                    del raw_elem["rect"]
                if "source" in raw_elem:
                    del raw_elem["source"]
                if "raw_element" in raw_elem:
                    del raw_elem["raw_element"]
                
                self.element_tree.append(raw_elem)
                
                # Add to found_elements for summary
                element_type = raw_elem["type"]
                if element_type not in self.found_elements:
                    self.found_elements[element_type] = []
                self.found_elements[element_type].append(raw_elem)
                
                # Add to screenshot draw list
                if SCREENSHOT:
                    self.elements_to_draw.append({
                        "rect": raw_elem["visible_rect"],
                        "index": raw_elem["index"],
                        "depth": 0,
                        "visibility": raw_elem.get("visibility", "full")
                    })
    
    def _flatten_win32_tree(self, tree_list, flat_list):
        """Recursively flatten Win32 tree into a flat list for deduplication"""
        for item in tree_list:
            flat_list.append(item)
            if item.get("children"):
                self._flatten_win32_tree(item["children"], flat_list)
                # Clear children since we're flattening (will be added as separate items)
                item["children"] = []
    
    def _flatten_raw_uia_list(self, tree_list, flat_list):
        """Flatten raw UIA list into a flat list for deduplication"""
        for item in tree_list:
            flat_list.append(item)
            if item.get("children"):
                self._flatten_raw_uia_list(item["children"], flat_list)
                # Clear children since we're flattening
                item["children"] = []
    
    def _collect_rects_recursive(self, tree_list, rects):
        """Recursively collect all element rectangles from tree for deduplication"""
        for item in tree_list:
            # Use original full rect for deduplication (not visible_rect which may be clipped)
            if item.get("rect"):
                rects.append(item["rect"])
            elif item.get("visible_rect"):
                rects.append(item["visible_rect"])
            if item.get("children"):
                self._collect_rects_recursive(item["children"], rects)
    
    def _rects_match(self, rect1, rect2, tolerance=5):
        """Check if two rectangles match within tolerance"""
        return (abs(rect1.left - rect2.left) <= tolerance and
                abs(rect1.top - rect2.top) <= tolerance and
                abs(rect1.right - rect2.right) <= tolerance and
                abs(rect1.bottom - rect2.bottom) <= tolerance)
    
    def _scan_desktop(self):
        """Helper method to scan desktop"""
        try:
            desktop_window = self.desktop.window(class_name="Progman")
            if not desktop_window.exists():
                desktop_window = self.desktop.window(class_name="WorkerW")
            
            self.app_rect = desktop_window.rectangle()  # Capture desktop window bounds
            
            # Get hwnd for parallel scans
            try:
                desktop_hwnd = desktop_window.handle
            except:
                desktop_hwnd = None
            
            # Start Win32 scan in parallel
            self.win32_thread = threading.Thread(target=self._scan_with_win32_parallel, args=("Program Manager",))
            self.win32_thread.start()
            
            # Start raw UIA scan in parallel
            if desktop_hwnd:
                self.raw_uia_thread = threading.Thread(target=self._scan_with_raw_uia_parallel, args=(desktop_hwnd,))
                self.raw_uia_thread.start()
            
            self._scan_element_recursive(desktop_window, self.element_tree, 0, skip_visibility=False)
        except Exception as e:
            pass

    def _scan_with_win32_parallel(self, window_title):
        """Parallel Win32 scan - stores results in self.win32_elements for later merge"""
        try:
            warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
            app = Application(backend="win32").connect(title=window_title)
            dialog = app.window(title=window_title)
            
            # Scan recursively just like UIA
            self._scan_win32_recursive(dialog, self.win32_elements, 0)
                    
        except Exception:
            pass  # Silent fail - UIA results will be used

    def _scan_win32_recursive(self, element, tree_list, depth):
        """Recursively scan Win32 elements - mirrors UIA approach, stores for later merge"""
        try:
            ctrl_class = element.class_name()
            ctrl_text = element.window_text()
            
            # Check if class name exists in our win32_class_map (built from ELEMENT_CONFIG)
            if ctrl_class in self.win32_class_map:
                element_type = self.win32_class_map[ctrl_class]
            elif ctrl_class in self.config:
                element_type = ctrl_class
            else:
                element_type = None
            
            should_track_element = False
            
            if element_type and element_type in self.config and self.config[element_type]["track"]:
                should_track_element = True
                
                # Check if enabled
                if should_track_element:
                    try:
                        if not element.is_enabled():
                            should_track_element = False
                    except:
                        pass
                
                # Check if visible
                if should_track_element:
                    try:
                        if not element.is_visible():
                            should_track_element = False
                    except:
                        pass
                
                # Browser keyboard focusable check
                if should_track_element and self.config[element_type].get("keyboard_focusable", False):
                    if self._is_browser_app():
                        try:
                            # Win32 doesn't have direct keyboard_focusable, skip these in browsers
                            should_track_element = False
                        except:
                            pass
                
                # Skip window control buttons at depth 0
                if should_track_element and depth == 0 and element_type == "Button":
                    try:
                        btn_name = ctrl_text.lower()
                        if any(word in btn_name for word in ["minimize", "minimise", "maximize", "maximise", "close"]):
                            should_track_element = False
                    except:
                        pass
                
                # Skip Text elements in Win32 - no AriaRole to check for heading
                # UIA scanner handles Text elements with AriaRole="heading" check
                if should_track_element and element_type == "Text":
                    should_track_element = False
                
                # Check element size
                if should_track_element:
                    try:
                        rect = element.rectangle()
                        width = rect.right - rect.left
                        height = rect.bottom - rect.top
                        if width < 10 or height < 10:
                            should_track_element = False
                    except:
                        should_track_element = False
                
                # Get name using fallback chain
                name = ""
                if should_track_element:
                    for prop in self.config[element_type].get("fallback", ["name"]):
                        try:
                            if prop == "name":
                                name = ctrl_text
                            elif prop == "class_name":
                                name = ctrl_class
                        except:
                            continue
                        if name and name.strip():
                            break
                    
                    # Remove Unicode control characters
                    name = ''.join(char for char in name if ord(char) >= 32 and ord(char) != 0x200E)
                    
                    if not name or name.strip() == "":
                        should_track_element = False
            
            if should_track_element:
                rect = element.rectangle()
                
                # Get value based on element type
                value = None
                if element_type == "Edit":
                    try:
                        value = element.window_text()
                    except:
                        value = ""
                elif element_type == "CheckBox":
                    try:
                        value = "Checked" if element.is_checked() else "Unchecked"
                    except:
                        value = ""
                elif element_type in ["ComboBox", "ListItem"]:
                    try:
                        value = element.window_text()
                    except:
                        value = ""
                
                # Win32 doesn't have AriaRole - leave empty
                aria_role = ""
                
                # Compute visibility (simplified for Win32 - use app_rect)
                visibility_status = "full"
                clipped_by = None
                
                if self.app_rect is not None:
                    if (rect.left < self.app_rect.left or rect.top < self.app_rect.top or
                        rect.right > self.app_rect.right or rect.bottom > self.app_rect.bottom):
                        visibility_status = "partial"
                        clipped_by = self.application_name
                
                # Add actions hint for ListItem in non-browser apps
                actions = None
                if element_type == "ListItem" and not self._is_browser:
                    actions = "{click: select, double_click: open}"
                
                # Store without index - will be assigned after merge/dedupe
                element_info = {
                    "element": element,
                    "name": name,
                    "aria_role": aria_role,
                    "type": element_type,
                    "active": element.is_enabled(),
                    "index": None,  # Assigned after dedupe
                    "value": value,
                    "actions": actions,
                    "visibility": visibility_status,
                    "clipped_by": clipped_by,
                    "visible_rect": rect,
                    "rect": rect,  # Store rect for deduplication
                    "children": [],
                    "source": "win32"  # Track source for debugging
                }
                
                tree_list.append(element_info)
                
                # Recursively scan children
                try:
                    for child in element.children():
                        self._scan_win32_recursive(child, element_info["children"], depth + 1)
                except:
                    pass
            else:
                # Even if we don't track this element, scan its children
                try:
                    for child in element.children():
                        self._scan_win32_recursive(child, tree_list, depth + 1)
                except:
                    pass
                    
        except Exception:
            pass

    def _scan_with_raw_uia_parallel(self, hwnd):
        """Parallel raw UIA COM scan - ONLY for Start Menu LauncherFrameXAMLWindow
        
        Only runs when LauncherFrameXAMLWindow sibling is detected.
        This element contains Start Menu content (Pinned, Recommended, etc.)
        that pywinauto cannot see because it's a sibling with empty name.
        """
        try:
            # Get UIA element from window handle
            foreground_element = _uia.ElementFromHandle(hwnd)
            if not foreground_element:
                return
            
            # Get parent to search for LauncherFrameXAMLWindow sibling
            walker = _uia.ControlViewWalker
            parent_element = walker.GetParentElement(foreground_element)
            
            if not parent_element:
                return  # No parent, can't find siblings
            
            # Search siblings for LauncherFrameXAMLWindow
            launcher_frame = None
            child = walker.GetFirstChildElement(parent_element)
            
            while child:
                try:
                    auto_id = child.CurrentAutomationId or ""
                    if auto_id == "LauncherFrameXAMLWindow":
                        launcher_frame = child
                        break
                except:
                    pass
                child = walker.GetNextSiblingElement(child)
            
            # If LauncherFrameXAMLWindow not found, skip raw UIA entirely
            if not launcher_frame:
                return
            
            # Found LauncherFrameXAMLWindow - scan ONLY this element
            self._scan_raw_uia_recursive(launcher_frame, self.raw_uia_elements, 0)
                
        except Exception:
            pass  # Silent fail - other scan results will be used

    def _scan_raw_uia_recursive(self, element, tree_list, depth, max_depth=30):
        """Recursively scan using raw UIA COM interface - same rules as pywinauto UIA"""
        if depth > max_depth:
            return
        
        try:
            control_type = element.CurrentControlType
            name = element.CurrentName or ""
            
            # Check if this control type is in our config
            element_type = self.uia_type_map.get(control_type)
            
            # Special handling: Group (50026) that might be Edit
            if control_type == 50026:  # Group
                try:
                    is_keyboard_focusable = element.CurrentIsKeyboardFocusable
                    is_control = element.CurrentIsControlElement
                    if is_control and is_keyboard_focusable:
                        element_type = "Edit"
                except:
                    pass
            
            should_track_element = False
            
            if element_type and element_type in self.config and self.config[element_type]["track"]:
                should_track_element = True
                
                # Check if enabled
                if should_track_element:
                    try:
                        if not element.CurrentIsEnabled:
                            should_track_element = False
                    except:
                        pass
                
                # Check if offscreen (basic visibility)
                if should_track_element:
                    try:
                        if element.CurrentIsOffscreen:
                            should_track_element = False
                    except:
                        pass
                
                # Browser keyboard focusable check
                if should_track_element and self.config[element_type].get("keyboard_focusable", False):
                    if self._is_browser_app():
                        try:
                            if not element.CurrentIsKeyboardFocusable:
                                should_track_element = False
                        except:
                            pass
                
                # Skip window control buttons at depth 0
                if should_track_element and depth == 0 and element_type == "Button":
                    try:
                        btn_name = (element.CurrentName or "").lower()
                        if any(word in btn_name for word in ["minimize", "minimise", "maximize", "maximise", "close"]):
                            should_track_element = False
                    except:
                        pass
                
                # Text elements: only track if AriaRole is "heading"
                if should_track_element and element_type == "Text":
                    try:
                        aria_role = element.CurrentAriaRole
                        if aria_role != "heading":
                            should_track_element = False
                    except:
                        should_track_element = False
                
                # Check element size
                if should_track_element:
                    try:
                        rect = element.CurrentBoundingRectangle
                        width = rect.right - rect.left
                        height = rect.bottom - rect.top
                        if width < 10 or height < 10:
                            should_track_element = False
                    except:
                        should_track_element = False
                
                # Get name using fallback chain
                if should_track_element:
                    name = ""
                    for prop in self.config[element_type].get("fallback", ["name"]):
                        try:
                            if prop == "name":
                                name = element.CurrentName or ""
                            elif prop == "automation_id":
                                name = element.CurrentAutomationId or ""
                            elif prop == "class_name":
                                name = element.CurrentClassName or ""
                            elif prop == "legacy_description":
                                name = element.GetCurrentPropertyValue(30094) or ""
                        except:
                            continue
                        if name and name.strip():
                            break
                    
                    # Remove Unicode control characters
                    name = ''.join(char for char in name if ord(char) >= 32 and ord(char) != 0x200E)
                    
                    if not name or name.strip() == "":
                        should_track_element = False
                
                if should_track_element:
                    rect = element.CurrentBoundingRectangle
                    
                    # Create rect tuple using module-level Rect namedtuple
                    rect_tuple = Rect(rect.left, rect.top, rect.right, rect.bottom)
                    
                    # Wrap raw element for pywinauto compatibility
                    wrapped_element = None
                    try:
                        child_info = uia_element_info.UIAElementInfo(element)
                        wrapped_element = UIAWrapper(child_info)
                    except:
                        pass
                    
                    # Compute visibility using same logic as main UIA scan
                    visibility_status = "full"
                    visible_rect = rect_tuple
                    clipped_by = None
                    
                    if wrapped_element:
                        try:
                            visibility_status, visible_rect, clipped_by = self._compute_visibility(wrapped_element, rect_tuple)
                        except:
                            # Fallback to simple app_rect check
                            if self.app_rect is not None:
                                if (rect_tuple.left < self.app_rect.left or 
                                    rect_tuple.top < self.app_rect.top or
                                    rect_tuple.right > self.app_rect.right or 
                                    rect_tuple.bottom > self.app_rect.bottom):
                                    visibility_status = "partial"
                                    clipped_by = self.application_name
                    
                    # Skip hidden elements
                    if visibility_status == "hidden":
                        should_track_element = False
                
                if should_track_element:
                    # Get value based on element type
                    value = None
                    if element_type == "Edit":
                        try:
                            value_pattern = element.GetCurrentPattern(10002)  # UIA_ValuePatternId
                            if value_pattern:
                                value = value_pattern.CurrentValue
                        except:
                            value = ""
                    elif element_type == "CheckBox":
                        try:
                            toggle_pattern = element.GetCurrentPattern(10015)  # UIA_TogglePatternId
                            if toggle_pattern:
                                state = toggle_pattern.CurrentToggleState
                                value = "Checked" if state == 1 else "Unchecked"
                        except:
                            value = ""
                    elif element_type in ["ComboBox", "ListItem"]:
                        try:
                            value_pattern = element.GetCurrentPattern(10002)
                            if value_pattern:
                                value = value_pattern.CurrentValue
                        except:
                            value = ""
                    elif element_type == "Document":
                        try:
                            value_pattern = element.GetCurrentPattern(10002)
                            if value_pattern:
                                text = value_pattern.CurrentValue
                                value = text[:100] + "..." if len(text) > 100 else text
                        except:
                            value = ""
                    elif element_type == "Group":
                        try:
                            value_pattern = element.GetCurrentPattern(10002)
                            if value_pattern:
                                value = value_pattern.CurrentValue
                        except:
                            value = ""
                    
                    # Get AriaRole
                    aria_role = ""
                    try:
                        aria_role = element.CurrentAriaRole or ""
                    except:
                        aria_role = ""
                    
                    # Add actions hint for ListItem in non-browser apps
                    actions = None
                    if element_type == "ListItem" and not self._is_browser:
                        actions = "{click: select, double_click: open}"
                    
                    element_info = {
                        "element": wrapped_element,
                        "raw_element": element,
                        "name": name,
                        "aria_role": aria_role,
                        "type": element_type,
                        "active": element.CurrentIsEnabled,
                        "index": None,  # Assigned after dedupe
                        "value": value,
                        "actions": actions,
                        "visibility": visibility_status,
                        "clipped_by": clipped_by,
                        "visible_rect": visible_rect if visible_rect else rect_tuple,
                        "rect": rect_tuple,  # For deduplication
                        "children": [],
                        "source": "raw_uia"
                    }
                    
                    tree_list.append(element_info)
            
            # Recurse children using ControlViewWalker
            walker = _uia.ControlViewWalker
            child = walker.GetFirstChildElement(element)
            
            while child:
                self._scan_raw_uia_recursive(child, tree_list, depth + 1, max_depth)
                child = walker.GetNextSiblingElement(child)
                
        except Exception:
            pass

    def _scan_element_recursive(self, element, tree_list, depth, skip_visibility=False):
        """Recursively scan elements to build tree structure"""
        try:
            control_type = element.element_info.control_type
            # Special handling for Group elements that are actually textboxes
            if control_type == "Group":
                try:
                    # Check if this Group has input field properties:
                    # IsControlElement = True AND IsKeyboardFocusable = True
                    is_control = False
                    is_keyboard_focusable = False
                    
                    # Get IsKeyboardFocusable from element wrapper
                    if hasattr(element, 'is_keyboard_focusable'):
                        is_keyboard_focusable = element.is_keyboard_focusable()
                    
                    # Get IsControlElement from raw UIA element
                    try:
                        raw_element = element.element_info.element
                        is_control = raw_element.CurrentIsControlElement
                    except:
                        is_control = element.element_info.visible and element.element_info.enabled
                    
                    if is_control and is_keyboard_focusable:
                        control_type = "Edit"
                except:
                    pass  # If properties not accessible, keep as Group
            
            # Check if this element type is in our config and is enabled
            if control_type in self.config and self.config[control_type]["track"]:
                should_track_element = True
                
                if not element.is_enabled():
                    if control_type == "Button":
                        try:
                            rect = element.rectangle()
                            self.disabled_button_rects.append(rect)
                        except:
                            pass
                    should_track_element = False
                
                if should_track_element and not element.is_visible():
                    should_track_element = False
                
                # Only enforce keyboard_focusable for browsers (Chrome, Edge, etc.)
                # Native apps handle focus differently, so we skip this check for them
                if should_track_element and self.config[control_type].get("keyboard_focusable", False) and not self.config[control_type].get("is_enabled_check", False):
                    if self._is_browser_app():
                        # Browser detected - enforce keyboard focusable check
                        is_keyboard_focusable = False
                        try:
                            raw_element = element.element_info.element
                            is_keyboard_focusable = raw_element.CurrentIsKeyboardFocusable
                        except:
                            try:
                                if hasattr(element, 'is_keyboard_focusable'):
                                    is_keyboard_focusable = element.is_keyboard_focusable()
                            except:
                                try:
                                    raw_element = element.element_info.element
                                    is_keyboard_focusable = bool(raw_element.GetCurrentPropertyValue(30009))
                                except:
                                    pass
                        if not is_keyboard_focusable:
                            should_track_element = False
                    # else: Native app - skip keyboard_focusable check entirely
                
                if should_track_element and depth == 0 and control_type == "Button":
                    try:
                        name = element.element_info.name.lower()
                        if any(word in name for word in ["minimize", "minimise", "maximize", "maximise", "close"]):
                            should_track_element = False
                    except:
                        pass

                # Text elements: only track if AriaRole is "heading"
                if should_track_element and control_type == "Text":
                    try:
                        raw_element = element.element_info.element
                        aria_role = raw_element.CurrentAriaRole
                        if aria_role != "heading":
                            should_track_element = False
                    except:
                        should_track_element = False
                
                if should_track_element:
                    # Check element size - filter out very small elements
                    try:
                        rect = element.rectangle()
                        width = rect.right - rect.left
                        height = rect.bottom - rect.top

                        # Ignore elements smaller than 10x10 pixels (they're usually not useful)
                        if width < 10 or height < 10:
                            should_track_element = False
                    except:
                        should_track_element = False
                
                if should_track_element:
                    # Get name using fallback chain from config
                    name = ""
                    for prop in self.config[control_type].get("fallback", ["name"]):
                        try:
                            if prop == "name":
                                name = element.element_info.name
                            elif prop == "automation_id":
                                name = element.automation_id()
                            elif prop == "class_name":
                                name = element.element_info.class_name
                            elif prop == "legacy_description":
                                # LegacyIAccessiblePattern.Description (UIA Property ID: 30094)
                                raw_element = element.element_info.element
                                name = raw_element.GetCurrentPropertyValue(30094) or ""
                        except:
                            continue
                        if name and name.strip():
                            break

                    # Remove Unicode control characters like U+200E (Left-to-Right Mark)
                    name = ''.join(char for char in name if ord(char) >= 32 and ord(char) != 0x200E)
                    
                    # ========== FILTER: Skip elements with empty names ==========
                    # This filter removes elements that have no name from the tree and screenshot
                    # To disable this filter, comment out the next 2 lines
                    if not name or name.strip() == "":
                        should_track_element = False
                    # ============================================================
                    
                if should_track_element:
                    self.element_index += 1

                    # Get the value/state based on element type
                    value = None
                    if control_type == "Edit":
                        try:
                            try:
                                value = element.element_info.current_value
                            except:
                                try:
                                    value = element.get_value()
                                except:
                                    value = element.window_text()
                        except:
                            value = ""
                    elif control_type == "CheckBox":
                        try:
                            value = "Checked" if element.get_toggle_state() == 1 else "Unchecked"
                        except:
                            value = ""
                    elif control_type in ["ComboBox", "ListItem"]:
                        try:
                            try:
                                value = element.element_info.current_value
                            except:
                                try:
                                    value = element.get_value()
                                except:
                                    value = element.window_text()
                        except:
                            value = ""
                    elif control_type == "Document":
                        try:
                            text = element.window_text()
                            value = text[:100] + "..." if len(text) > 100 else text
                        except:
                            value = ""
                    elif control_type == "Group":
                        try:
                            try:
                                value = element.element_info.current_value
                            except:
                                try:
                                    value = element.get_value()
                                except:
                                    value = ""
                        except:
                            value = ""
                    
                    # Get AriaRole property (UIA Property ID: 30101)
                    aria_role = ""
                    try:
                        raw_element = element.element_info.element
                        aria_role = raw_element.CurrentAriaRole
                    except:
                        try:
                            # Fallback: Try using GetCurrentPropertyValue with AriaRole property ID
                            raw_element = element.element_info.element
                            aria_role = raw_element.GetCurrentPropertyValue(30101)
                        except:
                            aria_role = ""
                    
                    rect = element.rectangle()
                    
                    if skip_visibility:
                        visibility_status = 'full'
                        visible_rect = rect
                        clipped_by = None
                    else:
                        visibility_status, visible_rect, clipped_by = self._compute_visibility(element, rect)

                    self.elements_mapping[str(self.element_index)] = {
                        'element': element,
                        'rect': rect,
                        'visible_rect': visible_rect,  # Actual visible rectangle (clipped by ancestors)
                        'name': name,
                        'aria_role': aria_role,
                        'type': control_type,
                        'value': value,
                        'visibility': visibility_status,
                        'clipped_by': clipped_by  # Name of the container clipping this element
                    }
                    
                    if SCREENSHOT:
                        self.elements_to_draw.append({
                            "rect": rect,
                            "index": self.element_index,
                            "depth": depth,
                            "visibility": visibility_status
                        })
                    
                    # Add actions hint for ListItem in non-browser apps
                    actions = None
                    if control_type == "ListItem" and not self._is_browser:
                        actions = "{click: select, double_click: open}"
                    
                    element_info = {
                        "element": element,
                        "name": name,
                        "aria_role": aria_role,
                        "type": control_type,
                        "active": element.is_enabled(),
                        "index": self.element_index,
                        "value": value,
                        "actions": actions,
                        "visibility": visibility_status,
                        "clipped_by": clipped_by,
                        "rect": rect,  # Store original full rect for deduplication
                        "visible_rect": visible_rect,
                        "children": []
                    }
                    
                    tree_list.append(element_info)
                    
                    if control_type not in self.found_elements:
                        self.found_elements[control_type] = []
                    self.found_elements[control_type].append(element_info)
                    
                    for child in element.children():
                        self._scan_element_recursive(child, element_info["children"], depth + 1, skip_visibility)
                    
                    # Browser Document: split children into top/second layer when popup detected
                    if control_type == "Document" and self._is_browser and element_info["children"]:
                        if self._detect_browser_popup(element_info["children"]):
                            popup_types = {"ListItem", "MenuItem", "Menu"}
                            element_info["browser_top_layer"] = [c for c in element_info["children"] if c["type"] in popup_types]
                            element_info["browser_second_layer"] = [c for c in element_info["children"] if c["type"] not in popup_types]
                            element_info["children"] = []  # Moved into layers
                
                if not should_track_element:
                    for child in element.children():
                        self._scan_element_recursive(child, tree_list, depth + 1, skip_visibility)
            else:
                # Even if we don't track this element, scan its children
                for child in element.children():
                    self._scan_element_recursive(child, tree_list, depth + 1, skip_visibility)
                    
        except:
            pass

    def get_elements_mapping(self):
        """Get the elements mapping for controller
        Returns: dict mapping index to element info
        """
        return self.elements_mapping

    def print_summary(self):
        """Print summary of found elements"""
        # Silent - no output
        pass
    
    def save_to_file(self):
        """Save found elements to file in hierarchical structure with layers"""
        if DEBUG:
            filename = f"debug/element/ui_elements_{int(time.time())}.txt"
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "w", encoding="utf-8") as f:
                # Write top layer
                f.write("<top_layer>\n")
                if self.top_layer_info:
                    layer_name = _xml_escape(self.top_layer_info["name"])
                    layer_type = self.top_layer_info["type"]
                    f.write(f'  <application name="{layer_name}" type="{layer_type}" />\n')
                else:
                    f.write('  <application name="Desktop" type="app" />\n')
                self._write_tree_recursive(f, self.top_layer_tree, 1)
                f.write("</top_layer>\n\n")
                
                # Write second layer (if exists)
                if self.second_layer_info and self.second_layer_tree:
                    f.write("<second_layer>\n")
                    layer_name = _xml_escape(self.second_layer_info["name"])
                    layer_type = self.second_layer_info["type"]
                    f.write(f'  <application name="{layer_name}" type="{layer_type}" />\n')
                    self._write_tree_recursive(f, self.second_layer_tree, 1)
                    f.write("</second_layer>\n\n")
                
                # Write taskbar
                f.write("<taskbar>\n")
                self._write_tree_recursive(f, self.taskbar_tree, 1)
                f.write("</taskbar>\n")

    def _write_tree_recursive(self, file, tree_list, depth):
        """Recursively write tree structure with indentation in XML format"""
        indent = "  " * depth  # 2 spaces per level for cleaner look
        
        for item in tree_list:
            # OCR_TEXT elements use a distinct format
            if item.get("source") == "ocr":
                text = _xml_escape(item['name'])
                file.write(f'{indent}[{item["index"]}]<Line="{text}", type="OCR_TEXT", active="True", visibility="full" />\n')
                if item.get("children"):
                    self._write_tree_recursive(file, item["children"], depth + 1)
                continue

            # Escape special characters in name for XML
            name = _xml_escape(item['name'])
            
            # Get aria_role - default to empty if not present
            aria_role = _xml_escape(item.get('aria_role', ''))
            
            # Get visibility status - default to 'full' if not present (for backward compatibility)
            visibility = item.get('visibility', 'full')
            
            # Get clipped_by - only include if visibility is not full
            clipped_by = item.get('clipped_by', None)
            clipped_by_attr = ""
            if clipped_by and visibility != "full":
                clipped_by_attr = f', clipped_by="{_xml_escape(clipped_by)}"'
            
            # Build actions attribute if present
            actions_attr = ""
            if item.get("actions"):
                actions_attr = f', actions="{item["actions"]}"'
            # Write element in the new format: [index]<element name="...", AriaRole="...", type="...", active="...", visibility="...", clipped_by="..." />
            # Include AriaRole right after name
            # Include valuePattern.value attribute if it exists and is not empty
            if item.get("value") and item["value"]:
                value = _xml_escape(item["value"])
                if aria_role:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}"{actions_attr}, visibility="{visibility}"{clipped_by_attr} />\n')
                else:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}"{actions_attr}, visibility="{visibility}"{clipped_by_attr} />\n')
            else:
                if aria_role:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", type="{item["type"]}", active="{item["active"]}"{actions_attr}, visibility="{visibility}"{clipped_by_attr} />\n')
                else:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", type="{item["type"]}", active="{item["active"]}"{actions_attr}, visibility="{visibility}"{clipped_by_attr} />\n')
            
            # Recursively write children or browser layers
            if item.get("browser_top_layer") is not None:
                file.write(f'{indent}  <top_layer_browser>\n')
                self._write_tree_recursive(file, item["browser_top_layer"], depth + 2)
                file.write(f'{indent}  </top_layer_browser>\n')
                file.write(f'{indent}  <second_layer_browser>\n')
                self._write_tree_recursive(file, item["browser_second_layer"], depth + 2)
                file.write(f'{indent}  </second_layer_browser>\n')
            elif item["children"]:
                self._write_tree_recursive(file, item["children"], depth + 1)
    
    def get_scan_data(self):
        """Get scan data for use by AgentService
        Returns: tuple (element_tree_text, annotated_image_base64, uac_detected)
        """
        # Generate element tree text with layer format
        element_tree_text = ""
        
        # Write top layer
        element_tree_text += "<top_layer>\n"
        if self.top_layer_info:
            layer_name = _xml_escape(self.top_layer_info["name"])
            layer_type = self.top_layer_info["type"]
            element_tree_text += f'  <application name="{layer_name}" type="{layer_type}" />\n'
        else:
            element_tree_text += '  <application name="Desktop" type="app" />\n'
        element_tree_text += self._get_tree_text_recursive(self.top_layer_tree, 1)
        element_tree_text += "</top_layer>\n\n"
        
        # Write second layer (if exists)
        if self.second_layer_info and self.second_layer_tree:
            element_tree_text += "<second_layer>\n"
            layer_name = _xml_escape(self.second_layer_info["name"])
            layer_type = self.second_layer_info["type"]
            element_tree_text += f'  <application name="{layer_name}" type="{layer_type}" />\n'
            element_tree_text += self._get_tree_text_recursive(self.second_layer_tree, 1)
            element_tree_text += "</second_layer>\n\n"
        
        # Write taskbar
        element_tree_text += "<taskbar>\n"
        element_tree_text += self._get_tree_text_recursive(self.taskbar_tree, 1)
        element_tree_text += "</taskbar>\n"
        
        # Capture and annotate screenshot, get as base64
        annotated_image_base64 = None
        if SCREENSHOT and self.elements_to_draw:
            # Capture full screen - may fail if UAC secure desktop is active
            try:
                screenshot = ImageGrab.grab()
            except OSError as e:
                # UAC secure desktop detected - screen grab failed
                print("🔒 UAC secure desktop detected - requesting agent decision")
                return None, None, True  # uac_detected = True
            
            # Keep a copy of plain screenshot for frontend when DEBUG=False
            plain_screenshot = screenshot.copy()
            
            # Now draw annotations on the original screenshot
            draw = ImageDraw.Draw(screenshot)
            
            # Try to load a regular (not bold) font
            font = None
            try:
                for font_name in ["arial.ttf", "verdana.ttf", "tahoma.ttf"]:
                    try:
                        font = ImageFont.truetype(font_name, 11)
                        break
                    except:
                        continue
            except:
                font = None
            
            # Draw each bounding box with index labels
            for item in self.elements_to_draw:
                rect = item["rect"]
                index = str(item["index"])
                is_ocr = item.get("source") == "ocr"
                
                # OCR boxes get slight padding for breathing room
                if is_ocr:
                    pad = 3
                    box = (rect.left - pad, rect.top - pad, rect.right + pad, rect.bottom + pad)
                else:
                    box = (rect.left, rect.top, rect.right, rect.bottom)
                
                draw.rectangle(box, outline=BOX_COLOR, width=2)
                
                label = f"[{index}]"
                if font:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                else:
                    text_width = len(label) * 8
                    text_height = 15
                
                if is_ocr:
                    # OCR: position label above the box
                    text_x = box[0]
                    text_y = box[1] - text_height - 2
                else:
                    # UIA: position label at top-left corner inside the box
                    text_x = rect.left + 4
                    text_y = rect.top + 3
                
                # ========== STYLING: text with white outline, no background ==========
                outline_color = (255, 255, 255)
                for ox, oy in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                    draw.text((text_x + ox, text_y + oy), label, fill=outline_color, font=font)
                draw.text((text_x, text_y), label, fill=NUMBER_COLOR, font=font)
                # ================================================================
            
            # Resize if image is too large (to reduce payload size)
            max_dimension = 1920  # Max width or height
            width, height = screenshot.size
            if width > max_dimension or height > max_dimension:
                # Calculate new dimensions maintaining aspect ratio
                if width > height:
                    new_width = max_dimension
                    new_height = int(height * (max_dimension / width))
                else:
                    new_height = max_dimension
                    new_width = int(width * (max_dimension / height))
                screenshot = screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert annotated screenshot to RGB (JPEG doesn't support transparency)
            if screenshot.mode in ('RGBA', 'LA', 'P'):
                rgb_screenshot = Image.new('RGB', screenshot.size, (255, 255, 255))
                rgb_screenshot.paste(screenshot, mask=screenshot.split()[-1] if screenshot.mode == 'RGBA' else None)
                screenshot = rgb_screenshot
            elif screenshot.mode != 'RGB':
                screenshot = screenshot.convert('RGB')
            
            # Convert annotated image to base64 with JPEG compression
            buffered_annotated = io.BytesIO()
            screenshot.save(buffered_annotated, format="JPEG", quality=100, optimize=True)
            annotated_image_base64 = base64.b64encode(buffered_annotated.getvalue()).decode('utf-8')
            
            # Save to debug folder if DEBUG is enabled (exact same images as sent to LLM)
            if DEBUG:
                timestamp = int(time.time())
                os.makedirs("debug/screenshot", exist_ok=True)
                filename_annotated = f"debug/screenshot/annotated_screenshot_{timestamp}.jpg"
                screenshot.save(filename_annotated, format="JPEG", quality=100, optimize=True)

            # Send image to frontend if FRONTEND is enabled and callback exists
            # DEBUG=True: annotated image, DEBUG=False: plain image (production)
            if FRONTEND and self.frontend_callback:
                if DEBUG:
                    self.frontend_callback(annotated_image_base64)
                else:
                    # Prepare plain screenshot for production frontend
                    width, height = plain_screenshot.size
                    if width > max_dimension or height > max_dimension:
                        if width > height:
                            new_width = max_dimension
                            new_height = int(height * (max_dimension / width))
                        else:
                            new_height = max_dimension
                            new_width = int(width * (max_dimension / height))
                        plain_screenshot = plain_screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    if plain_screenshot.mode in ('RGBA', 'LA', 'P'):
                        rgb_plain = Image.new('RGB', plain_screenshot.size, (255, 255, 255))
                        rgb_plain.paste(plain_screenshot, mask=plain_screenshot.split()[-1] if plain_screenshot.mode == 'RGBA' else None)
                        plain_screenshot = rgb_plain
                    elif plain_screenshot.mode != 'RGB':
                        plain_screenshot = plain_screenshot.convert('RGB')
                    
                    buffered_plain = io.BytesIO()
                    plain_screenshot.save(buffered_plain, format="JPEG", quality=100, optimize=True)
                    plain_image_base64 = base64.b64encode(buffered_plain.getvalue()).decode('utf-8')
                    self.frontend_callback(plain_image_base64)
        
        return element_tree_text, annotated_image_base64, False  # uac_detected = False
    
    def _get_tree_text_recursive(self, tree_list, depth):
        """Helper method to generate tree text recursively"""
        result = ""
        indent = "  " * depth
        
        for item in tree_list:
            # OCR_TEXT elements use a distinct format
            if item.get("source") == "ocr":
                text = _xml_escape(item['name'])
                result += f'{indent}[{item["index"]}]<Line="{text}", type="OCR_TEXT", active="True", visibility="full" />\n'
                if item["children"]:
                    result += self._get_tree_text_recursive(item["children"], depth + 1)
                continue

            name = _xml_escape(item['name'])
            
            # Get aria_role - default to empty if not present
            aria_role = _xml_escape(item.get('aria_role', ''))
            
            # Get visibility status - default to 'full' if not present (for backward compatibility)
            visibility = item.get('visibility', 'full')
            
            # Get clipped_by - only include if visibility is not full
            clipped_by = item.get('clipped_by', None)
            clipped_by_attr = ""
            if clipped_by and visibility != "full":
                clipped_by_attr = f', clipped_by="{_xml_escape(clipped_by)}"'
            
            if item.get("value") and item["value"]:
                value = _xml_escape(item["value"])
                if aria_role:
                    result += f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n'
                else:
                    result += f'{indent}[{item["index"]}]<element name="{name}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n'
            else:
                if aria_role:
                    result += f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n'
                else:
                    result += f'{indent}[{item["index"]}]<element name="{name}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n'
            
            # Recursively write children or browser layers
            if item.get("browser_top_layer") is not None:
                result += f'{indent}  <top_layer_browser>\n'
                result += self._get_tree_text_recursive(item["browser_top_layer"], depth + 2)
                result += f'{indent}  </top_layer_browser>\n'
                result += f'{indent}  <second_layer_browser>\n'
                result += self._get_tree_text_recursive(item["browser_second_layer"], depth + 2)
                result += f'{indent}  </second_layer_browser>\n'
            elif item["children"]:
                result += self._get_tree_text_recursive(item["children"], depth + 1)
        
        return result

# ========== MAIN PROGRAM ==========
def main():
    print("Starting scan now!\n")

    # Create scanner with configuration
    scanner = UIElementScanner(ELEMENT_CONFIG)
    
    # Scan for elements
    scanner.scan_elements()
    
    if DEBUG:
        print("Scan complete. Check debug/element/ for element tree and debug/screenshot/ for screenshots.")
    else:
        print("Scan complete. Data sent directly to LLM without saving.")

if __name__ == "__main__":
    main()
