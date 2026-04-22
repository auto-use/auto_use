#!/usr/bin/env python3
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

"""
macOS UI Element Scanner — drop-in replacement for Windows element.py
Uses macOS Accessibility API via PyObjC.
Requires: System Settings > Privacy & Security > Accessibility

Exposes the same UIElementScanner class interface that Auto_Use/macOS_use/agent/service.py
and Auto_Use/macOS_use/controller/ expect:
    - UIElementScanner(config, frontend_callback=None)
    - scanner.scan_elements()
    - scanner.get_scan_data()      → (element_tree_text, annotated_image_base64, uac_detected)
    - scanner.get_elements_mapping() → dict
    - scanner.application_name     → str
    - scanner.print_summary()
    - scanner.save_to_file()
"""

import sys
import os
import re
import io
import time
import base64
import numpy as np
from collections import namedtuple
from PIL import Image, ImageDraw, ImageFont
from Quartz import (
    CGWindowListCreateImage, CGRectMake,
    kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
    CGImageGetWidth, CGImageGetHeight,
    CGDisplayIsBuiltin, CGGetActiveDisplayList, CGDisplayBounds,
    CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
    kCGWindowListExcludeDesktopElements,
)
from Cocoa import (
    NSWorkspace, NSScreen, NSBitmapImageRep, NSPNGFileType,
    NSApplicationActivateIgnoringOtherApps,
)
from ApplicationServices import (
    AXUIElementCreateSystemWide, AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue, AXUIElementSetAttributeValue,
    AXIsProcessTrusted, kAXErrorSuccess,
)


# ========== CONFIGURATION ==========
# Toggle switches — same semantics as Windows element.py
SCREENSHOT = True    # Set to False to only generate element tree without screenshot
DEBUG = False        # Set to True to save files to debug folders, False for direct LLM only
FRONTEND = True      # Set to True when running from app.py to send images to frontend

# Define Rect namedtuple matching Windows format (left, top, right, bottom)
Rect = namedtuple('Rect', ['left', 'top', 'right', 'bottom'])

# Single magenta color for all elements in screenshot (matches Windows)
BOX_COLOR = (255, 0, 255)   # Bright magenta for all boxes
NUMBER_COLOR = (255, 0, 255) # Same magenta for numbers

MAX_DEPTH = 30

BROWSER_BUNDLES = {
    "com.apple.Safari",
    "com.google.Chrome",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",   # Arc
    "com.brave.Browser",
    "com.operasoftware.Opera",
    "org.mozilla.firefox",
}

LOADING_TEMPLATE = os.path.join(os.path.dirname(__file__), "loading.png")
BROWSER_LOAD_TIMEOUT = 15
BROWSER_LOAD_INTERVAL = 0.5
AX_TREE_READY_TIMEOUT = 5
AX_TREE_READY_INTERVAL = 0.25


# ========== ELEMENT CONFIG (macOS AX roles) ==========
ELEMENT_CONFIG = {
    "AXGroup": {
        "track": True,
        "is_enabled_flag": False,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXRadioButton": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXButton": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXCheckBox": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXCell": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXValue", "AXIdentifier", "AXHelp", "_children_text"],
    },
    "AXMenuBarItem": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXLink": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXPopUpButton": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXTextField": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXDescription", "AXTitle", "AXValue", "AXRoleDescription"],
    },
    "AXTextArea": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXDescription", "AXTitle", "AXValue", "AXRoleDescription"],
    },
    "AXComboBox": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXImage": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXDescription", "AXTitle", "AXFilename", "AXRoleDescription"],
    },
    "AXIcon": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXMenuItem": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXValue", "AXRoleDescription", "_children_text"],
    },
    "AXStaticText": {
        "track": True,
        "is_enabled_flag": False,
        "fallback": ["AXValue", "AXTitle", "AXDescription", "AXRoleDescription"],
    },
    "AXMenuButton": {
        "track": True,
        "is_enabled_flag": True,
        "fallback": ["AXTitle", "AXDescription", "AXRoleDescription"],
    },
}


# ========== AX HELPERS ==========

def ax_attr(element, attr):
    """Safely read a single AX attribute."""
    try:
        err, val = AXUIElementCopyAttributeValue(element, attr, None)
        if err == kAXErrorSuccess and val is not None:
            return val
    except Exception:
        pass
    return None


# ========== GEOMETRY ==========

def _extract_two_floats(val):
    """Pull two floats from any AXValue format."""
    try:
        return (val.pointValue().x, val.pointValue().y)
    except Exception:
        pass
    try:
        return (val.sizeValue().width, val.sizeValue().height)
    except Exception:
        pass
    s = str(val)
    m = re.search(r'x:([-\d.]+)\s+y:([-\d.]+)', s)
    if m:
        return (float(m[1]), float(m[2]))
    m = re.search(r'w:([-\d.]+)\s+h:([-\d.]+)', s)
    if m:
        return (float(m[1]), float(m[2]))
    m = re.search(r'\{([-\d.]+),\s*([-\d.]+)\}', s)
    if m:
        return (float(m[1]), float(m[2]))
    return None


def _extract_four_floats(val):
    """Pull x, y, w, h from an AXFrame value."""
    s = str(val)
    m = re.search(r'x:([-\d.]+)\s+y:([-\d.]+)\s+w:([-\d.]+)\s+h:([-\d.]+)', s)
    if m:
        return (float(m[1]), float(m[2]), float(m[3]), float(m[4]))
    m = re.search(r'\{([-\d.]+),\s*([-\d.]+)\}.*?\{([-\d.]+),\s*([-\d.]+)\}', s)
    if m:
        return (float(m[1]), float(m[2]), float(m[3]), float(m[4]))
    return None


def get_frame(element):
    """Return {x, y, width, height} or None. Works for native + Electron."""
    frame_val = ax_attr(element, "AXFrame")
    if frame_val is not None:
        r = _extract_four_floats(frame_val)
        if r:
            return {"x": r[0], "y": r[1], "width": r[2], "height": r[3]}

    pos = ax_attr(element, "AXPosition")
    size = ax_attr(element, "AXSize")
    if pos is None or size is None:
        return None
    pt = _extract_two_floats(pos)
    sz = _extract_two_floats(size)
    if pt and sz:
        return {"x": pt[0], "y": pt[1], "width": sz[0], "height": sz[1]}
    return None


def _display_for_point(x, y):
    """Return CG bounds dict of the display that contains point (x, y), or None."""
    err, display_ids, count = CGGetActiveDisplayList(10, None, None)
    if err == 0:
        for did in display_ids[:count]:
            b = CGDisplayBounds(did)
            if (b.origin.x <= x < b.origin.x + b.size.width and
                    b.origin.y <= y < b.origin.y + b.size.height):
                return {"x": b.origin.x, "y": b.origin.y,
                        "width": b.size.width, "height": b.size.height}
    return None


def get_screen():
    """Return built-in display bounds in CG coordinates (same as AX coords)."""
    err, display_ids, count = CGGetActiveDisplayList(10, None, None)
    if err == 0:
        for did in display_ids[:count]:
            if CGDisplayIsBuiltin(did):
                b = CGDisplayBounds(did)
                scale = 2.0
                for s in NSScreen.screens():
                    sid = s.deviceDescription().get("NSScreenNumber", 0)
                    if sid == did:
                        scale = s.backingScaleFactor()
                        break
                return {
                    "x": b.origin.x, "y": b.origin.y,
                    "width": b.size.width, "height": b.size.height,
                    "scale": scale,
                }
    main = NSScreen.mainScreen()
    if main:
        f = main.frame()
        return {
            "x": 0, "y": 0,
            "width": f.size.width, "height": f.size.height,
            "scale": main.backingScaleFactor(),
        }
    return {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 2.0}


# ========== BROWSER LOAD DETECTION ==========

def _pid_to_bundle(pid):
    """Return bundle ID for a given PID, or None."""
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.processIdentifier() == pid:
            bid = app.bundleIdentifier()
            return str(bid) if bid else None
    return None


def _is_browser(pid):
    """Check if PID belongs to a recognized browser."""
    bid = _pid_to_bundle(pid)
    return bid in BROWSER_BUNDLES if bid else False


def _grab_toolbar(screen, window_frame, scale):
    """Capture and crop the browser toolbar region (top 80pt of window)."""
    cg_img = CGWindowListCreateImage(
        CGRectMake(screen["x"], screen["y"], screen["width"], screen["height"]),
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID, 0,
    )
    if not cg_img:
        return None
    bmp = NSBitmapImageRep.alloc().initWithCGImage_(cg_img)
    png = bmp.representationUsingType_properties_(NSPNGFileType, None)
    tmp = "/tmp/_toolbar_check.png"
    png.writeToFile_atomically_(tmp, True)
    img = Image.open(tmp)

    ox, oy = screen["x"], screen["y"]
    toolbar_h = 80  # points
    x = int((window_frame["x"] - ox) * scale)
    y = int((window_frame["y"] - oy) * scale)
    w = int(window_frame["width"] * scale)
    h = int(toolbar_h * scale)
    return img.crop((max(x, 0), max(y, 0),
                     min(x + w, img.width), min(y + h, img.height)))


def _template_match(haystack, needle, threshold=0.75, step=3):
    """Normalized cross-correlation. Returns True if needle found."""
    h = np.array(haystack.convert("L"), dtype=np.float64)
    n = np.array(needle.convert("L"), dtype=np.float64)
    nh, nw = n.shape
    hh, hw = h.shape
    if nh > hh or nw > hw:
        return False
    n_mean = n.mean()
    n_std = n.std()
    if n_std < 1.0:
        return False
    n_norm = n - n_mean
    denom = n_std * nh * nw

    for y in range(0, hh - nh + 1, step):
        for x in range(0, hw - nw + 1, step):
            patch = h[y:y + nh, x:x + nw]
            p_std = patch.std()
            if p_std < 1.0:
                continue
            score = np.sum((patch - patch.mean()) * n_norm) / (p_std * denom)
            if score >= threshold:
                return True
    return False


def _is_browser_loading(screen, window_frame, scale):
    """Return True if ✕ stop button is visible in browser toolbar."""
    if not os.path.exists(LOADING_TEMPLATE):
        print(f"  Template '{LOADING_TEMPLATE}' not found, skipping load check")
        return False

    toolbar = _grab_toolbar(screen, window_frame, scale)
    if toolbar is None:
        return False

    template = Image.open(LOADING_TEMPLATE)
    base_w, base_h = template.size
    for s in (1.0, 0.75, 0.5, 1.25, 1.5):
        sw, sh = max(int(base_w * s), 4), max(int(base_h * s), 4)
        scaled = template.resize((sw, sh), Image.LANCZOS)
        if _template_match(toolbar, scaled):
            return True
    return False


def wait_for_browser_load(screen, window_frame, scale):
    """Block until browser page finishes loading (stop icon gone) or timeout."""
    print("  Browser detected — waiting for page load...")
    deadline = time.time() + BROWSER_LOAD_TIMEOUT

    while time.time() < deadline:
        if not _is_browser_loading(screen, window_frame, scale):
            print("  Page loaded.")
            return True
        remaining = int(deadline - time.time())
        print(f"  Still loading... ({remaining}s left)")
        time.sleep(BROWSER_LOAD_INTERVAL)

    print("  Timeout — scanning anyway.")
    return False


def _find_ax_web_area(element, depth=0, max_depth=8):
    """Recursively search for an AXWebArea element in the AX subtree."""
    if depth > max_depth:
        return None
    role = ax_attr(element, "AXRole")
    if role and str(role) == "AXWebArea":
        return element
    children = ax_attr(element, "AXChildren")
    if children:
        try:
            for child in children:
                found = _find_ax_web_area(child, depth + 1, max_depth)
                if found:
                    return found
        except Exception:
            pass
    return None


def _wait_for_ax_web_content(app_ax, window, timeout=AX_TREE_READY_TIMEOUT):
    """Poll until the AXWebArea inside a browser window has children."""
    deadline = time.time() + timeout

    web_area = None
    while time.time() < deadline:
        web_area = _find_ax_web_area(window)
        if web_area:
            break
        time.sleep(AX_TREE_READY_INTERVAL)

    if not web_area:
        print("  AXWebArea not found — non-web window or timeout.")
        return False

    while time.time() < deadline:
        children = ax_attr(web_area, "AXChildren")
        if children and len(children) > 0:
            print("  Web content AX tree ready.")
            return True
        time.sleep(AX_TREE_READY_INTERVAL)

    print("  Timeout waiting for web content AX tree — scanning anyway.")
    return False


# ========== LABEL BUILDER ==========

GENERIC_LABELS = frozenset({
    "", "group", "application", "image", "text", "button", "cell", "row",
    "tab", "radio button", "check box", "menu bar item", "menu extra"
})


def build_label(element, cfg):
    """Try each fallback attribute, return first non-empty, non-generic string."""
    for attr in cfg.get("fallback", []):
        if attr == "_children_text":
            children = ax_attr(element, "AXChildren")
            if children:
                try:
                    for child in children:
                        cr = ax_attr(child, "AXRole")
                        if cr and str(cr) == "AXStaticText":
                            val = ax_attr(child, "AXValue") or ax_attr(child, "AXTitle")
                            if val:
                                label = str(val).replace("\n", " ").strip()
                                if label.lower() not in GENERIC_LABELS:
                                    return label[:50] if len(label) > 50 else label
                except Exception:
                    pass
            continue

        val = ax_attr(element, attr)
        if val:
            label = str(val).replace("\n", " ").strip()
            if label.lower() in GENERIC_LABELS:
                continue
            return label[:50] if len(label) > 50 else label
    return ""


# ========== TREE WALK ==========

_seen_roles = set()

CLIP_ROLES = frozenset({"AXScrollArea", "AXList", "AXOutline", "AXTable"})


def _overlaps(a, b):
    """Return True if rect a overlaps rect b."""
    return not (a["x"] + a["width"] <= b["x"] or a["x"] >= b["x"] + b["width"] or
                a["y"] + a["height"] <= b["y"] or a["y"] >= b["y"] + b["height"])


def _on_screen(frame, screen):
    """Return True if frame overlaps the target screen bounds."""
    return not (frame["x"] + frame["width"] <= screen["x"]
                or frame["x"] >= screen["x"] + screen["width"]
                or frame["y"] + frame["height"] <= screen["y"]
                or frame["y"] >= screen["y"] + screen["height"])


def _rect_intersect(a, b):
    """Return intersection rect of a and b, or None if no overlap."""
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["width"], b["x"] + b["width"])
    y2 = min(a["y"] + a["height"], b["y"] + b["height"])
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def _visibility_pct(frame, clip, screen):
    """Compute what % of frame is visible within clip rect and screen bounds."""
    total = frame["width"] * frame["height"]
    if total <= 0:
        return 0.0
    visible = frame
    if clip:
        visible = _rect_intersect(visible, clip)
        if not visible:
            return 0.0
    visible = _rect_intersect(visible, screen)
    if not visible:
        return 0.0
    return (visible["width"] * visible["height"]) / total * 100.0


def _point_in_rect(px, py, rect):
    """Return True if point (px, py) is inside rect."""
    return (rect["x"] <= px <= rect["x"] + rect["width"]
            and rect["y"] <= py <= rect["y"] + rect["height"])


def _ancestor_clipped_visibility(frame, ancestors, screen, window_clip=None):
    """Bottom-up visibility check — mirrors Windows _get_clipping_ancestors.
    Returns (visibility_str, visible_rect_dict_or_None)."""
    visible = dict(frame)

    for anc in ancestors:
        if anc is None:
            continue
        if anc["width"] < 50 or anc["height"] < 50:
            continue

        inter = _rect_intersect(visible, anc)
        if inter is None:
            anc_on_screen = _rect_intersect(anc, screen) is not None
            anc_large = anc["width"] >= 100 and anc["height"] >= 100
            if anc_on_screen and anc_large:
                # Safety net for CSS position:fixed / sticky elements —
                # their AX parent frames may not encompass them even though
                # the element is clearly visible within the window.
                if (window_clip
                        and _rect_intersect(frame, window_clip)
                        and _rect_intersect(frame, screen)):
                    continue
                return "hidden", None
            continue

        vis_area = visible["width"] * visible["height"]
        int_area = inter["width"] * inter["height"]
        if vis_area > 0 and int_area < vis_area * 0.95:
            visible = inter

    visible = _rect_intersect(visible, screen)
    if visible is None:
        return "hidden", None

    total = frame["width"] * frame["height"]
    if total <= 0:
        return "hidden", None
    pct = (visible["width"] * visible["height"]) / total * 100.0
    if pct >= 99.0:
        return "full", None
    elif pct > 0:
        return f"partial {int(pct)}%", visible
    else:
        return "hidden", None


def walk(element, results, depth, screen, clip=None, parent_frame=None,
         skip_roles=None, ancestors=None, is_browser=False, window_clip=None):
    """Recursively walk AX tree, collect elements matching ELEMENT_CONFIG."""
    if depth > MAX_DEPTH:
        return
    if ancestors is None:
        ancestors = []

    role = ax_attr(element, "AXRole")
    if role is None:
        return
    role_str = str(role)
    _seen_roles.add(role_str)

    my_frame = get_frame(element)
    child_clip = clip
    if role_str in CLIP_ROLES and my_frame:
        if clip:
            child_clip = _rect_intersect(clip, my_frame) or clip
        else:
            child_clip = my_frame

    cfg = ELEMENT_CONFIG.get(role_str)
    if cfg and cfg.get("track") and not (skip_roles and role_str in skip_roles):
        if is_browser and not cfg.get("is_enabled_flag", True):
            focused = ax_attr(element, "AXFocused")
            skip = focused is not None and not focused
        else:
            enabled = ax_attr(element, "AXEnabled")
            skip = enabled is not None and not enabled

        if not skip:
            frame = my_frame or get_frame(element)

            if frame and frame["width"] > 0 and frame["height"] > 0:
                label = build_label(element, cfg)
                if label:
                    vis_str, vis_rect = _ancestor_clipped_visibility(frame, ancestors, screen, window_clip)

                    if vis_str != "hidden":
                        results.append({
                            "type": role_str,
                            "label": label,
                            "x": frame["x"],
                            "y": frame["y"],
                            "width": frame["width"],
                            "height": frame["height"],
                            "depth": depth,
                            "visibility": vis_str,
                            "visible_rect_raw": vis_rect,
                            "ax_element": element,
                        })

    child_ancestors = ancestors + [my_frame] if my_frame else ancestors
    children = ax_attr(element, "AXChildren")
    if children:
        try:
            for child in children:
                walk(child, results, depth + 1, screen, child_clip,
                     my_frame, skip_roles, child_ancestors, is_browser, window_clip)
        except Exception:
            pass


# ========== SOURCE EXTRACTORS ==========

def find_app(bundle_id):
    """Find running app by bundle ID."""
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == bundle_id:
            return app
    return None


def _rect_overlaps(ax, ay, aw, ah, screen):
    """Check if a rectangle overlaps the screen bounds."""
    return not (ax + aw <= screen["x"] or ax >= screen["x"] + screen["width"] or
                ay + ah <= screen["y"] or ay >= screen["y"] + screen["height"])


def _find_topmost_app_on_screen(screen):
    """Find the topmost app window on the built-in screen.
    Returns (app_info, window_stack)."""
    flags = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    win_list = CGWindowListCopyWindowInfo(flags, kCGNullWindowID)
    if not win_list:
        return None, []

    skip_owners = {"Window Server", "Dock", "SystemUIServer", "Control Center", "Notification Center"}

    topmost = None
    window_stack = []

    for w in win_list:
        owner = w.get("kCGWindowOwnerName", "")
        if owner in skip_owners:
            continue
        if w.get("kCGWindowLayer", -1) != 0:
            continue
        bounds = w.get("kCGWindowBounds")
        if not bounds:
            continue
        wx = bounds.get("X", 0)
        wy = bounds.get("Y", 0)
        ww = bounds.get("Width", 0)
        wh = bounds.get("Height", 0)
        if ww < 50 or wh < 50:
            continue
        if not _rect_overlaps(wx, wy, ww, wh, screen):
            continue

        pid = w.get("kCGWindowOwnerPID", 0)
        frame = {"x": wx, "y": wy, "width": ww, "height": wh}
        window_stack.append({"pid": pid, "name": owner, "frame": frame})

        if topmost is None:
            topmost = {"name": owner, "pid": pid, "frame": frame}

    return topmost, window_stack


def _is_occluded(element, allowed_pids, window_stack):
    """Check if element is behind another app's window."""
    cx = element["x"] + element["width"] / 2
    cy = element["y"] + element["height"] / 2
    for win in window_stack:
        if _point_in_rect(cx, cy, win["frame"]):
            if win["pid"] in allowed_pids:
                return False
            else:
                return True
    return False


def _scan_menu_bar(screen, top_pid):
    """Return app-menu-bar items visible on the target screen."""
    cfg = ELEMENT_CONFIG.get("AXMenuBarItem", {})
    menu_strip_bottom = screen["y"] + 40

    def _x_overlaps_screen(frame):
        return not (frame["x"] + frame["width"] <= screen["x"]
                    or frame["x"] >= screen["x"] + screen["width"])

    def _collect(ax_source):
        out = []
        mb = ax_attr(ax_source, "AXMenuBar")
        if not mb:
            return out
        children = ax_attr(mb, "AXChildren")
        if not children:
            return out
        for child in children:
            role = ax_attr(child, "AXRole")
            if not (role and str(role) == "AXMenuBarItem"):
                continue
            frame = get_frame(child)
            if not (frame and frame["width"] > 0 and frame["height"] > 0):
                continue
            if not _x_overlaps_screen(frame):
                continue
            if frame["y"] > menu_strip_bottom:
                continue
            label = build_label(child, cfg)
            if not label:
                continue
            subrole = str(ax_attr(child, "AXSubrole") or "")
            mtype = "AXStatusMenu" if subrole == "AXMenuExtra" else "AXMenuBarItem"
            out.append({
                "type": mtype, "label": label,
                "x": frame["x"], "y": frame["y"],
                "width": frame["width"], "height": frame["height"],
            })
        return out

    def _try_app(pid):
        return _collect(AXUIElementCreateApplication(pid))

    if top_pid:
        items = _try_app(top_pid)
        if items:
            return items

    finder = find_app("com.apple.finder")
    if finder:
        items = _try_app(finder.processIdentifier())
        if items:
            return items

    ws = NSWorkspace.sharedWorkspace()
    for app in ws.runningApplications():
        try:
            if app.activationPolicy() != 0:
                continue
            pid = app.processIdentifier()
            ax_app = AXUIElementCreateApplication(pid)
            mb = ax_attr(ax_app, "AXMenuBar")
            if not mb:
                continue
            mf = get_frame(mb)
            if not (mf and _x_overlaps_screen(mf)
                    and mf["width"] > screen["width"] * 0.3):
                continue
            items = _collect(ax_app)
            if items:
                return items
        except Exception:
            pass

    return []


def _walk_finder_desktop(screen, results):
    """Walk Finder's AXDesktop window to capture desktop icons/widgets."""
    finder = find_app("com.apple.finder")
    if not finder:
        return
    finder_ax = AXUIElementCreateApplication(finder.processIdentifier())
    windows = ax_attr(finder_ax, "AXWindows")
    if not windows:
        return
    screen_rect = {"x": screen["x"], "y": screen["y"],
                   "width": screen["width"], "height": screen["height"]}
    try:
        for win in windows:
            role = ax_attr(win, "AXRole")
            if role and str(role) == "AXDesktop":
                walk(win, results, 0, screen, clip=screen_rect, window_clip=screen_rect)
                return
    except Exception:
        pass


def _force_focus_topmost(screen, top):
    """Activate the topmost app so macOS updates its menu bar.

    Skips activation when the frontmost process has no real menu bar
    (Spotlight, status-menu popup, etc.) — the visible menu bar still
    belongs to the last regular app, and activating would dismiss the
    transient UI.

    Returns the target_pid used for menu-bar scanning.
    """
    ws = NSWorkspace.sharedWorkspace()
    prev = ws.frontmostApplication()
    prev_pid = prev.processIdentifier() if prev else -1

    target_pid = top["pid"] if top else None

    if target_pid is None:
        finder = find_app("com.apple.finder")
        if finder:
            target_pid = finder.processIdentifier()

    if target_pid is None or target_pid == prev_pid:
        return target_pid

    # If the frontmost app has no AXMenuBar (or fewer than 2 items),
    # it is system-level transient UI (Spotlight, status menu popup).
    # The on-screen menu bar still belongs to the last regular app —
    # skip activation so the transient UI is not dismissed.
    front_ax = AXUIElementCreateApplication(prev_pid)
    front_mb = ax_attr(front_ax, "AXMenuBar")
    if not front_mb:
        return target_pid
    mb_children = ax_attr(front_mb, "AXChildren")
    if not mb_children or len(mb_children) < 2:
        return target_pid

    for app in ws.runningApplications():
        if app.processIdentifier() == target_pid:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            time.sleep(0.3)
            break

    return target_pid


def extract_all(screen):
    """Gather elements from all visible sources. Returns (app_info, menu_items, elements)."""
    results = []
    menu_items = []
    app_info = None

    top, window_stack = _find_topmost_app_on_screen(screen)

    if top and _is_browser(top["pid"]):
        wait_for_browser_load(screen, top["frame"], screen.get("scale", 2.0))

    activated_pid = _force_focus_topmost(screen, top)
    menu_items.extend(_scan_menu_bar(screen, activated_pid))

    if activated_pid:
        mb = ax_attr(AXUIElementCreateApplication(activated_pid), "AXMenuBar")
        if mb:
            walk(mb, results, 0, screen, skip_roles={"AXMenuBarItem"})

    if top:
        app_info = {"name": top["name"], "frame": top["frame"]}
        app_ax = AXUIElementCreateApplication(top["pid"])
        top_frame = top["frame"]

        is_browser = _is_browser(top["pid"])
        AXUIElementSetAttributeValue(app_ax, "AXEnhancedUserInterface", True)
        time.sleep(0.3)

        windows = ax_attr(app_ax, "AXWindows")
        if windows:
            tolerance = 20
            matched_windows = []
            for win in windows:
                wf = get_frame(win)
                if wf and (abs(wf["x"] - top_frame["x"]) < tolerance
                           and abs(wf["y"] - top_frame["y"]) < tolerance
                           and abs(wf["width"] - top_frame["width"]) < tolerance
                           and abs(wf["height"] - top_frame["height"]) < tolerance):
                    matched_windows.append((win, wf))

            if is_browser and matched_windows:
                _wait_for_ax_web_content(app_ax, matched_windows[0][0])

            if matched_windows:
                walked_wins = set()
                for win, wf in matched_windows:
                    walk(win, results, 0, screen, clip=wf, is_browser=is_browser, window_clip=wf)
                    walked_wins.add(id(win))
                # Walk any remaining visible, on-screen windows (dialogs, sheets, panels)
                for win in windows:
                    if id(win) in walked_wins:
                        continue
                    minimized = ax_attr(win, "AXMinimized")
                    if minimized:
                        continue
                    wf = get_frame(win)
                    if wf and _on_screen(wf, screen):
                        walk(win, results, 0, screen, clip=wf, is_browser=is_browser, window_clip=wf)
            else:
                screen_clip = {"x": screen["x"], "y": screen["y"],
                               "width": screen["width"], "height": screen["height"]}
                for win in windows:
                    walk(win, results, 0, screen, clip=screen_clip, is_browser=is_browser, window_clip=screen_clip)

        if window_stack:
            # Find overlay/dialog windows from any process that overlap the topmost app
            dialog_pids = set()
            skip_dialog_owners = {"Window Server", "Dock"}
            top_frame = top["frame"]
            flags = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
            all_wins = CGWindowListCopyWindowInfo(flags, kCGNullWindowID)
            if all_wins:
                for w in all_wins:
                    wpid = w.get("kCGWindowOwnerPID", 0)
                    if wpid == top["pid"]:
                        continue  # Skip topmost app's own windows
                    owner = w.get("kCGWindowOwnerName", "")
                    if owner in skip_dialog_owners:
                        continue
                    bounds = w.get("kCGWindowBounds")
                    if not bounds:
                        continue
                    ww = bounds.get("Width", 0)
                    wh = bounds.get("Height", 0)
                    if ww < 50 or wh < 50:
                        continue
                    wx = bounds.get("X", 0)
                    wy = bounds.get("Y", 0)
                    if not _rect_overlaps(wx, wy, ww, wh, top_frame):
                        continue
                    dialog_pids.add(wpid)

            for dpid in dialog_pids:
                dialog_ax = AXUIElementCreateApplication(dpid)
                d_windows = ax_attr(dialog_ax, "AXWindows")
                if d_windows:
                    for dwin in d_windows:
                        dwf = get_frame(dwin)
                        if dwf and _on_screen(dwf, screen):
                            walk(dwin, results, 0, screen, clip=dwf, window_clip=dwf)

            allowed_pids = {top["pid"]} | dialog_pids
            results = [e for e in results
                       if not _is_occluded(e, allowed_pids, window_stack)]

    else:
        finder = find_app("com.apple.finder")
        if finder:
            app_info = {"name": "Finder", "frame": {
                "x": screen["x"], "y": screen["y"],
                "width": screen["width"], "height": screen["height"],
            }}
            finder_ax = AXUIElementCreateApplication(finder.processIdentifier())
            screen_clip = {"x": screen["x"], "y": screen["y"],
                           "width": screen["width"], "height": screen["height"]}
            windows = ax_attr(finder_ax, "AXWindows")
            if windows:
                for win in windows:
                    wf = get_frame(win)
                    if wf and _on_screen(wf, screen):
                        minimized = ax_attr(win, "AXMinimized")
                        if minimized:
                            continue
                        walk(win, results, 0, screen, clip=screen_clip, window_clip=screen_clip)

        # Scan for overlay dialogs on desktop (no topmost app)
        skip_dialog_owners = {"Window Server", "Dock"}
        flags = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
        all_wins = CGWindowListCopyWindowInfo(flags, kCGNullWindowID)
        if all_wins:
            dialog_pids = set()
            for w in all_wins:
                owner = w.get("kCGWindowOwnerName", "")
                if owner in skip_dialog_owners:
                    continue
                bounds = w.get("kCGWindowBounds")
                if not bounds:
                    continue
                ww = bounds.get("Width", 0)
                wh = bounds.get("Height", 0)
                if ww < 50 or wh < 50:
                    continue
                wx = bounds.get("X", 0)
                wy = bounds.get("Y", 0)
                if not _rect_overlaps(wx, wy, ww, wh, screen):
                    continue
                dialog_pids.add(w.get("kCGWindowOwnerPID", 0))

            for dpid in dialog_pids:
                dialog_ax = AXUIElementCreateApplication(dpid)
                d_windows = ax_attr(dialog_ax, "AXWindows")
                if d_windows:
                    for dwin in d_windows:
                        dwf = get_frame(dwin)
                        if dwf and _on_screen(dwf, screen):
                            walk(dwin, results, 0, screen, clip=dwf, window_clip=dwf)

    # Status menu items (right side)
    ws = NSWorkspace.sharedWorkspace()
    for app in ws.runningApplications():
        try:
            ax = AXUIElementCreateApplication(app.processIdentifier())
            bar = ax_attr(ax, "AXExtrasMenuBar")
            if not bar:
                continue
            items = ax_attr(bar, "AXChildren")
            if not items:
                continue
            for item in items:
                role = ax_attr(item, "AXRole")
                role_s = str(role) if role else ""
                if role_s in ("AXMenuExtra", "AXMenuBarItem", "AXStatusItem"):
                    frame = get_frame(item)
                    if frame and frame["width"] > 0 and frame["height"] > 0:
                        if not _on_screen(frame, screen):
                            continue
                        cfg = ELEMENT_CONFIG.get("AXMenuBarItem", {})
                        label = build_label(item, cfg)
                        if label:
                            menu_items.append({
                                "type": "AXStatusMenu",
                                "label": label,
                                "x": frame["x"], "y": frame["y"],
                                "width": frame["width"],
                                "height": frame["height"],
                            })
        except Exception:
            pass

    menu_items.sort(key=lambda m: m["x"])

    # Desktop icons
    _walk_finder_desktop(screen, results)

    # Dock
    dock = find_app("com.apple.dock")
    if dock:
        walk(AXUIElementCreateApplication(dock.processIdentifier()), results, 0, screen)

    # Deduplicate
    seen = set()
    unique = []
    for e in results:
        key = (e["label"], e["type"], round(e["x"]), round(e["y"]))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    results = unique

    return app_info, menu_items, results


# ========== SCREENSHOT ==========

def take_screenshot(screen):
    """Capture built-in display only, return (PIL Image, scale)."""
    try:
        scale = screen.get("scale", 2.0)
        cg_img = CGWindowListCreateImage(
            CGRectMake(screen["x"], screen["y"], screen["width"], screen["height"]),
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID, 0,
        )
        if cg_img:
            bmp = NSBitmapImageRep.alloc().initWithCGImage_(cg_img)
            png = bmp.representationUsingType_properties_(NSPNGFileType, None)
            tmp = "/tmp/_screenshot.png"
            png.writeToFile_atomically_(tmp, True)
            return Image.open(tmp), scale
    except Exception as e:
        print(f"Screenshot error: {e}")
    return None, 2.0


# ========== XML ESCAPE ==========

def _xml_escape(text):
    """Escape special characters for XML attributes."""
    if not text:
        return ""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


# ========== SPATIAL CONTAINMENT (for tree hierarchy) ==========

def _contains(a, b):
    """Return True if element a spatially contains element b."""
    return (a["x"] <= b["x"] and a["y"] <= b["y"]
            and a["x"] + a["width"] >= b["x"] + b["width"]
            and a["y"] + a["height"] >= b["y"] + b["height"])


# ========== SCANNER CLASS ==========

class UIElementScanner:
    """macOS drop-in replacement for the Windows UIElementScanner.
    
    Exposes the same public interface so Auto_Use/macOS_use/agent/service.py,
    Auto_Use/macOS_use/controller/service.py, and Auto_Use/macOS_use/controller/view.py
    work without modifications.
    """

    def __init__(self, config, frontend_callback=None):
        self.config = config
        self.frontend_callback = frontend_callback

        # State populated by scan_elements()
        self.element_tree = []          # Hierarchical tree structure (top layer)
        self.menu_bar_tree = []         # Menu bar items as tree nodes
        self.element_index = 0          # Global index counter
        self.application_name = "Desktop"
        self.elements_to_draw = []      # List for screenshot bounding boxes
        self.elements_mapping = {}      # Mapping of index → element info for controller
        self.app_rect = None            # Application window rectangle
        self.top_layer_info = None      # {"name": ..., "type": "app"}
        self.second_layer_info = None   # Not used on macOS (no overlay layers)
        self.second_layer_tree = []     # Empty on macOS
        self.found_elements = {}        # Dictionary to store elements by type
        self._debug_iteration = 0       # Debug iteration counter

    def scan_elements(self):
        """Scan the active window and menu bar for configured element types."""

        # Clear previous scan state
        self.element_tree = []
        self.menu_bar_tree = []
        self.second_layer_tree = []
        self.element_index = 0
        self.application_name = "Desktop"
        self.elements_to_draw = []
        self.elements_mapping = {}
        self.app_rect = None
        self.top_layer_info = None
        self.second_layer_info = None
        self.found_elements = {}

        # Check accessibility permission
        if not AXIsProcessTrusted():
            print("\n⚠️  Accessibility permission required.")
            print("Grant in: System Settings > Privacy & Security > Accessibility")
            return

        # Get screen info
        screen = get_screen()

        # Run the macOS AX scan
        _seen_roles.clear()
        app_info, menu_items, elements = extract_all(screen)
        elements.sort(key=lambda e: (e["y"], e["x"]))

        # Store application name
        if app_info:
            self.application_name = app_info["name"]
            self.top_layer_info = {"name": app_info["name"], "type": "app"}
            if app_info.get("frame"):
                f = app_info["frame"]
                self.app_rect = Rect(
                    int(f["x"]), int(f["y"]),
                    int(f["x"] + f["width"]), int(f["y"] + f["height"])
                )
        else:
            self.top_layer_info = {"name": "Desktop", "type": "app"}

        # ----- Build menu bar tree nodes -----
        for m in menu_items:
            self.element_index += 1
            # Map AX type to clean name (strip "AX" prefix)
            clean_type = m["type"].replace("AX", "") if m["type"].startswith("AX") else m["type"]
            rect = Rect(
                int(m["x"]), int(m["y"]),
                int(m["x"] + m["width"]), int(m["y"] + m["height"])
            )

            node = {
                "element": None,    # No pywinauto element on macOS
                "name": m["label"],
                "aria_role": "",
                "type": clean_type,
                "active": True,
                "index": self.element_index,
                "value": None,
                "actions": None,
                "visibility": "full",
                "clipped_by": None,
                "rect": rect,
                "visible_rect": rect,
                "children": [],
                "browser_top_layer": None,
                "browser_second_layer": None,
                "source": "",
            }
            self.menu_bar_tree.append(node)

            self.elements_mapping[str(self.element_index)] = {
                'element': None,
                'rect': rect,
                'visible_rect': rect,
                'name': m["label"],
                'aria_role': '',
                'type': clean_type,
                'value': None,
                'visibility': 'full',
                'clipped_by': None,
            }

            if SCREENSHOT:
                self.elements_to_draw.append({
                    "rect": rect,
                    "index": self.element_index,
                    "depth": 0,
                    "visibility": "full",
                    "source": "",
                })

        # ----- Build element tree from flat elements using spatial containment -----
        self.element_tree = self._build_hierarchical_tree(elements)

        # ----- Capture and annotate screenshot -----
        self._debug_iteration += 1
        if SCREENSHOT and self.elements_to_draw:
            self._capture_and_annotate(screen)

        # ----- Save debug tree file -----
        if DEBUG:
            self.save_to_file()

    def _build_hierarchical_tree(self, flat_elements):
        """Convert flat element list into a hierarchical tree using spatial containment,
        assign indices, and populate elements_mapping."""

        if not flat_elements:
            return []

        # Sort by area descending — larger containers first
        by_area = sorted(flat_elements, key=lambda e: e["width"] * e["height"], reverse=True)

        # Assign each element its nearest containing parent
        parent = [None] * len(by_area)
        depth = [0] * len(by_area)
        for i in range(len(by_area)):
            for j in range(i):
                if _contains(by_area[j], by_area[i]):
                    parent[i] = j
            if parent[i] is not None:
                depth[i] = depth[parent[i]] + 1

        # Create tree nodes (indices assigned later after position sorting)
        nodes = []
        for i, e in enumerate(by_area):
            clean_type = e["type"].replace("AX", "") if e["type"].startswith("AX") else e["type"]

            rect = Rect(
                int(e["x"]), int(e["y"]),
                int(e["x"] + e["width"]), int(e["y"] + e["height"])
            )

            vis = e.get("visibility", "full")
            vr = e.get("visible_rect_raw")
            if vr:
                visible_rect = Rect(
                    int(vr["x"]), int(vr["y"]),
                    int(vr["x"] + vr["width"]), int(vr["y"] + vr["height"])
                )
            else:
                visible_rect = rect

            node = {
                "element": None,
                "name": e["label"],
                "aria_role": "",
                "type": clean_type,
                "active": True,
                "index": None,  # assigned after position sorting
                "value": None,
                "actions": None,
                "visibility": vis,
                "clipped_by": None,
                "rect": rect,
                "visible_rect": visible_rect,
                "children": [],
                "browser_top_layer": None,
                "browser_second_layer": None,
                "source": "",
                "_parent_idx": parent[i],
                "_depth": depth[i],
                "_orig_idx": i,
                "_raw_element": e,
            }
            nodes.append(node)

        # Build parent-child relationships
        for i, node in enumerate(nodes):
            p = node["_parent_idx"]
            if p is not None:
                nodes[p]["children"].append(node)

        # Root nodes are those with no parent
        roots = [n for n in nodes if n["_parent_idx"] is None]

        # Sort children by position (top-to-bottom, left-to-right)
        def _sort_children(node_list):
            node_list.sort(key=lambda n: (n["rect"].top, n["rect"].left))
            for n in node_list:
                if n["children"]:
                    _sort_children(n["children"])

        _sort_children(roots)

        # Assign sequential indices via tree traversal (depth-first)
        def _assign_indices(node_list):
            for n in node_list:
                self.element_index += 1
                n["index"] = self.element_index
                e = n.pop("_raw_element")

                # Populate elements_mapping for controller
                self.elements_mapping[str(self.element_index)] = {
                    'element': None,
                    'rect': n["rect"],
                    'visible_rect': n["visible_rect"],
                    'name': n["name"],
                    'aria_role': '',
                    'type': n["type"],
                    'value': None,
                    'visibility': n["visibility"],
                    'clipped_by': None,
                    'ax_element': e.get("ax_element"),
                }

                if SCREENSHOT:
                    self.elements_to_draw.append({
                        "rect": n["rect"],
                        "index": self.element_index,
                        "depth": n.get("_depth", 0),
                        "visibility": n["visibility"],
                        "source": "",
                    })

                # Track found elements by type
                if n["type"] not in self.found_elements:
                    self.found_elements[n["type"]] = []
                self.found_elements[n["type"]].append(n)

                if n["children"]:
                    _assign_indices(n["children"])

        _assign_indices(roots)

        # Clean up internal keys
        def _cleanup(node_list):
            for n in node_list:
                n.pop("_parent_idx", None)
                n.pop("_depth", None)
                n.pop("_orig_idx", None)
                n.pop("_raw_element", None)
                if n["children"]:
                    _cleanup(n["children"])

        _cleanup(roots)

        return roots

    def _capture_and_annotate(self, screen):
        """Capture screenshot, draw bounding boxes, store as base64."""
        screenshot, scale = take_screenshot(screen)
        if screenshot is None:
            self._annotated_image_base64 = None
            self._plain_screenshot = None
            return

        self._plain_screenshot = screenshot.copy()
        ox, oy = screen["x"], screen["y"]

        draw = ImageDraw.Draw(screenshot)

        # Load font
        font = None
        font_size = 11
        for font_path in ("/System/Library/Fonts/Helvetica.ttc",
                          "/System/Library/Fonts/SFNSMono.ttf",
                          "/System/Library/Fonts/Menlo.ttc"):
            try:
                font = ImageFont.truetype(font_path, int(font_size * scale))
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        # Draw each bounding box with index labels
        for item in self.elements_to_draw:
            rect = item["rect"]
            index = str(item["index"])

            # Convert from CG coordinates to pixel coordinates
            box = (
                int((rect.left - ox) * scale),
                int((rect.top - oy) * scale),
                int((rect.right - ox) * scale),
                int((rect.bottom - oy) * scale),
            )

            draw.rectangle(box, outline=BOX_COLOR, width=2)

            label = f"[{index}]"
            if font:
                bbox = draw.textbbox((0, 0), label, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width = len(label) * 8
                text_height = 15

            # Position label at top-left inside box
            text_x = box[0] + 4
            text_y = box[1] + 3

            # White outline for readability
            outline_color = (255, 255, 255)
            for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                draw.text((text_x + dx, text_y + dy), label, fill=outline_color, font=font)
            draw.text((text_x, text_y), label, fill=NUMBER_COLOR, font=font)

        # Resize if too large
        max_dimension = 1920
        width, height = screenshot.size
        if width > max_dimension or height > max_dimension:
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            screenshot = screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Convert to RGB for JPEG
        if screenshot.mode in ('RGBA', 'LA', 'P'):
            rgb = Image.new('RGB', screenshot.size, (255, 255, 255))
            rgb.paste(screenshot, mask=screenshot.split()[-1] if screenshot.mode == 'RGBA' else None)
            screenshot = rgb
        elif screenshot.mode != 'RGB':
            screenshot = screenshot.convert('RGB')

        # Encode as JPEG base64
        buffered = io.BytesIO()
        screenshot.save(buffered, format="JPEG", quality=100, optimize=True)
        self._annotated_image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        # Save debug files
        if DEBUG:
            debug_dir = f"debug/iteration_{self._debug_iteration}"
            os.makedirs(debug_dir, exist_ok=True)
            screenshot.save(f"{debug_dir}/annotated_screenshot.jpg",
                            format="JPEG", quality=100, optimize=True)

        # Send to frontend
        if FRONTEND and self.frontend_callback:
            if DEBUG:
                self.frontend_callback(self._annotated_image_base64)
            else:
                # Send plain screenshot for production frontend
                plain = self._plain_screenshot
                w, h = plain.size
                if w > max_dimension or h > max_dimension:
                    if w > h:
                        nw = max_dimension
                        nh = int(h * (max_dimension / w))
                    else:
                        nh = max_dimension
                        nw = int(w * (max_dimension / h))
                    plain = plain.resize((nw, nh), Image.Resampling.LANCZOS)

                if plain.mode in ('RGBA', 'LA', 'P'):
                    rgb_plain = Image.new('RGB', plain.size, (255, 255, 255))
                    rgb_plain.paste(plain, mask=plain.split()[-1] if plain.mode == 'RGBA' else None)
                    plain = rgb_plain
                elif plain.mode != 'RGB':
                    plain = plain.convert('RGB')

                buf = io.BytesIO()
                plain.save(buf, format="JPEG", quality=100, optimize=True)
                self.frontend_callback(base64.b64encode(buf.getvalue()).decode('utf-8'))

    def get_scan_data(self):
        """Get scan data for use by AgentService.
        
        Returns:
            tuple: (element_tree_text, annotated_image_base64, uac_detected)
                   uac_detected is always False on macOS (no UAC).
        """
        element_tree_text = ""

        # Write menu bar section
        if self.menu_bar_tree:
            element_tree_text += "<menu_bar>\n"
            element_tree_text += self._get_tree_text_recursive(self.menu_bar_tree, 1)
            element_tree_text += "</menu_bar>\n\n"

        # Write top layer
        element_tree_text += "<top_layer>\n"
        if self.top_layer_info:
            layer_name = _xml_escape(self.top_layer_info["name"])
            layer_type = self.top_layer_info["type"]
            element_tree_text += f'  <application name="{layer_name}" type="{layer_type}" />\n'
        else:
            element_tree_text += '  <application name="Desktop" type="app" />\n'
        element_tree_text += self._get_tree_text_recursive(self.element_tree, 1)
        element_tree_text += "</top_layer>\n"

        # Get annotated image
        annotated_image_base64 = getattr(self, '_annotated_image_base64', None)

        return element_tree_text, annotated_image_base64, False  # uac_detected = False

    def _get_tree_text_recursive(self, tree_list, depth):
        """Generate tree text recursively — matches Windows format."""
        result = ""
        indent = "  " * depth

        for item in tree_list:
            name = _xml_escape(item['name'])
            visibility = item.get('visibility', 'full')

            # Get clipped_by — only include if visibility is not full
            clipped_by = item.get('clipped_by', None)
            clipped_by_attr = ""
            if clipped_by and visibility != "full":
                clipped_by_attr = f', clipped_by="{_xml_escape(clipped_by)}"'

            # Get aria_role
            aria_role = _xml_escape(item.get('aria_role', ''))

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

            # Recurse into children
            if item.get("children"):
                result += self._get_tree_text_recursive(item["children"], depth + 1)

        return result

    def get_elements_mapping(self):
        """Get the elements mapping for controller.
        
        Returns:
            dict: mapping index (str) → element info dict
        """
        return self.elements_mapping

    def print_summary(self):
        """Print summary of found elements — silent (matches Windows behavior)."""
        pass

    def save_to_file(self):
        """Save element tree to file when DEBUG is True."""
        if DEBUG:
            debug_dir = f"debug/iteration_{self._debug_iteration}"
            os.makedirs(debug_dir, exist_ok=True)
            filename = f"{debug_dir}/tree.txt"
            with open(filename, "w", encoding="utf-8") as f:
                # Write menu bar
                if self.menu_bar_tree:
                    f.write("<menu_bar>\n")
                    self._write_tree_recursive(f, self.menu_bar_tree, 1)
                    f.write("</menu_bar>\n\n")

                # Write top layer
                f.write("<top_layer>\n")
                if self.top_layer_info:
                    layer_name = _xml_escape(self.top_layer_info["name"])
                    layer_type = self.top_layer_info["type"]
                    f.write(f'  <application name="{layer_name}" type="{layer_type}" />\n')
                else:
                    f.write('  <application name="Desktop" type="app" />\n')
                self._write_tree_recursive(f, self.element_tree, 1)
                f.write("</top_layer>\n")

    def _write_tree_recursive(self, file, tree_list, depth):
        """Write tree recursively to file — same format as get_tree_text."""
        indent = "  " * depth

        for item in tree_list:
            name = _xml_escape(item['name'])
            visibility = item.get('visibility', 'full')

            clipped_by = item.get('clipped_by', None)
            clipped_by_attr = ""
            if clipped_by and visibility != "full":
                clipped_by_attr = f', clipped_by="{_xml_escape(clipped_by)}"'

            aria_role = _xml_escape(item.get('aria_role', ''))

            if item.get("value") and item["value"]:
                value = _xml_escape(item["value"])
                if aria_role:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n')
                else:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", valuePattern.value="{value}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n')
            else:
                if aria_role:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", AriaRole="{aria_role}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n')
                else:
                    file.write(f'{indent}[{item["index"]}]<element name="{name}", type="{item["type"]}", active="{item["active"]}", visibility="{visibility}"{clipped_by_attr} />\n')

            if item.get("children"):
                self._write_tree_recursive(file, item["children"], depth + 1)


# ========== MAIN PROGRAM ==========

def main():
    print("macOS UI Element Scanner")
    print(f"DEBUG = {DEBUG}")
    print(f"SCREENSHOT = {SCREENSHOT}")

    if not AXIsProcessTrusted():
        print("\nAccessibility permission required.")
        print("Grant in: System Settings > Privacy & Security > Accessibility")
        sys.exit(1)

    # Create scanner with configuration
    scanner = UIElementScanner(ELEMENT_CONFIG)

    # Countdown
    for i in range(5, 0, -1):
        print(f"  Scanning in {i}...")
        time.sleep(1)

    print("Scanning now!\n")
    scanner.scan_elements()

    # Print results
    element_tree_text, annotated_image_base64, _ = scanner.get_scan_data()
    mapping = scanner.get_elements_mapping()

    print(f"Application: {scanner.application_name}")
    print(f"Elements found: {len(mapping)}")
    print(f"Image captured: {annotated_image_base64 is not None}")

    if DEBUG:
        scanner.save_to_file()
        print("\nElement tree text:")
        print(element_tree_text)
        print("Scan complete. Check debug/ for files.")
    else:
        print("Scan complete. Data ready for LLM.")


if __name__ == "__main__":
    main()