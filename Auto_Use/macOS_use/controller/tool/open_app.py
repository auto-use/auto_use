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

# Auto_Use/macOS_use/controller/tool/open_app.py
# macOS version — open or bring-to-front any .app bundle

import os
import subprocess
import logging
import time
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    s = s.lower().strip()
    for ch in (".", "_", "-", "(", ")", "[", "]", "{", "}", "®", "™", "&", "'", '"'):
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _index_applications():
    """Scan /Applications and ~/Applications for .app bundles."""
    entries = []
    app_dirs = ["/Applications", os.path.expanduser("~/Applications")]

    seen = set()
    for root in app_dirs:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if not name.endswith(".app"):
                continue
            display = name[:-4]  # strip .app
            nn = _normalize(display)
            if nn in seen:
                continue
            seen.add(nn)
            entries.append((display, os.path.join(root, name), nn))

        # One level deep for grouped apps (e.g. /Applications/Utilities/*.app)
        for subdir in os.listdir(root):
            subpath = os.path.join(root, subdir)
            if not os.path.isdir(subpath) or subdir.endswith(".app"):
                continue
            for name in os.listdir(subpath):
                if not name.endswith(".app"):
                    continue
                display = name[:-4]
                nn = _normalize(display)
                if nn in seen:
                    continue
                seen.add(nn)
                entries.append((display, os.path.join(subpath, name), nn))

    return entries


def _best_match(query, candidates):
    """Find best matching app from candidates list."""
    qn = _normalize(query)

    # Exact match
    for display, path, nn in candidates:
        if nn == qn:
            return display, path

    # Contains (either direction)
    cont = [(display, path) for display, path, nn in candidates if qn in nn or nn in qn]
    if cont:
        cont.sort(key=lambda x: len(x[0]))
        return cont[0]

    # Fuzzy
    scored = []
    for display, path, nn in candidates:
        scored.append((SequenceMatcher(None, qn, nn).ratio(), display, path))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.6:
        return scored[0][1], scored[0][2]

    return None, None


def _move_to_main_screen():
    """Move the frontmost app's window onto the main display (above the Dock)."""
    try:
        from Cocoa import NSScreen
        full = NSScreen.mainScreen().frame()
        screen_h = int(full.size.height)
        screen_w = int(full.size.width)
        screen_x = int(full.origin.x)

        # Get Dock position to avoid overlapping it
        dock_y = screen_h  # default: no dock
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to tell process "Dock" to get the position of list 1'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(",")
                if len(parts) == 2:
                    dock_y = int(parts[1].strip())
        except Exception:
            pass

        # Derive menu bar height dynamically: full height - visibleFrame height - visibleFrame origin.y
        visible = NSScreen.mainScreen().visibleFrame()
        menu_bar_h = int(screen_h - visible.origin.y - visible.size.height)
        y_top = menu_bar_h
        w = screen_w
        h = dock_y - menu_bar_h

        script = f'''
            tell application "System Events"
                tell (first process whose frontmost is true)
                    if exists window 1 then
                        set position of window 1 to {{{screen_x}, {y_top}}}
                        set size of window 1 to {{{w}, {h}}}
                    end if
                end tell
            end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        logger.info(f"Moved frontmost window to visible area ({screen_x}, {y_top}, {w}x{h})")
    except Exception as e:
        logger.warning(f"Could not move window to main screen: {e}")


def _is_app_running(app_name: str) -> bool:
    """Check if an application is currently running via System Events."""
    script = f'''
        tell application "System Events"
            return (name of processes) contains "{app_name}"
        end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def _bring_to_front(app_name: str):
    """Bring an already-running app to the front using System Events (no new windows)."""
    script = f'''
        tell application "System Events"
            set frontmost of process "{app_name}" to true
        end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        logger.info(f"Brought {app_name} to front via System Events")
    except Exception as e:
        logger.warning(f"Could not bring {app_name} to front: {e}")


def open_app(app_name: str) -> bool:
    """
    Open an application on macOS (or bring to front if already running).
    Always moves the window to the main display so the agent can detect it.

    Args:
        app_name: Application name (e.g., "Google Chrome", "safari", "vscode")

    Returns:
        True if launched successfully, False otherwise.
    """
    # Special case: Finder is always running, not in /Applications
    if _normalize(app_name) == "finder":
        try:
            script = '''
                tell application "Finder"
                    activate
                    if (count of Finder windows) = 0 then
                        make new Finder window
                    end if
                end tell
            '''
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            logger.info("Opened Finder via AppleScript")
            time.sleep(1.0)
            _move_to_main_screen()
            return True
        except Exception as e:
            logger.error(f"Failed to open Finder: {e}")
            return False

    candidates = _index_applications()
    display, path = _best_match(app_name, candidates)

    if not path:
        logger.error(f"App not installed: {app_name}")
        return False

    try:
        subprocess.run(["open", "-a", path], check=True, capture_output=True)
        logger.info(f"Opened app: {display} ({path})")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to open {display}: {e}")
        return False

    # Give the app time to launch and become frontmost
    time.sleep(1.0)

    # Move its window onto the main display
    _move_to_main_screen()

    return True