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

import os
import sys
import subprocess
import shutil
import json
from pathlib import Path
from difflib import SequenceMatcher

def normalize(s: str) -> str:
    s = s.lower().strip()
    for ch in ("'", '"', ".", "_", "-", "(", ")", "[", "]", "{", "}", "®", "™", "&"):
        s = s.replace(ch, " ")
    return " ".join(s.split())

def best_match(query, candidates):
    """candidates: list of (display_name, target, norm_name)
       target is either a filesystem path or 'appx:<AppID>'"""
    qn = normalize(query)

    # exact
    for name, target, nn in candidates:
        if nn == qn:
            return name, target

    # contains
    cont = [(name, target) for name, target, nn in candidates if qn in nn or nn in qn]
    if cont:
        cont.sort(key=lambda x: len(x[0]))
        return cont[0]

    # fuzzy
    scored = []
    for name, target, nn in candidates:
        scored.append((SequenceMatcher(None, qn, nn).ratio(), name, target))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.6:
        return scored[0][1], scored[0][2]

    return None, None

def index_windows_start_menu():
    entries = []
    start_dirs = []
    if "ProgramData" in os.environ:
        start_dirs.append(Path(os.environ["ProgramData"]) / r"Microsoft\Windows\Start Menu\Programs")
    if "AppData" in os.environ:
        start_dirs.append(Path(os.environ["AppData"]) / r"Microsoft\Windows\Start Menu\Programs")

    exts = {".lnk", ".url", ".appref-ms"}
    seen = set()
    for root in start_dirs:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                name = p.stem
                nn = normalize(name)
                key = (nn, str(p))
                if key in seen:
                    continue
                seen.add(key)
                entries.append((name, str(p), nn))
    return entries

def index_windows_startapps():
    """Use PowerShell Get-StartApps to include UWP/Store apps (e.g., Spotify)."""
    try:
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Depth 2 -Compress"
        ]
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if cp.returncode != 0 or not cp.stdout.strip():
            return []
        data = json.loads(cp.stdout)
        if isinstance(data, dict):
            data = [data]
        entries = []
        for item in data:
            name = str(item.get("Name", "")).strip()
            appid = str(item.get("AppID", "")).strip()
            if name and appid:
                entries.append((name, f"appx:{appid}", normalize(name)))
        return entries
    except Exception:
        return []

def _ps_quote(s: str) -> str:
    # PowerShell single-quote escape
    return "'" + s.replace("'", "''") + "'"

def launch_windows_target(name: str, target: str) -> bool:
    """Launch (maximized where possible) with accessibility flags."""
    # Universal accessibility flag for better UI automation
    accessibility_flag = "--force-renderer-accessibility"
    
    try:
        if target.startswith("appx:"):
            appid = target[5:]
            # UWP / Store app - can't add custom flags
            cmd = [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f"Start-Process {_ps_quote('shell:AppsFolder\\' + appid)} -WindowStyle Maximized"
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return r.returncode == 0
        else:
            # For .lnk shortcuts, we need to resolve the actual exe first
            if target.endswith('.lnk'):
                # Use PowerShell to resolve the shortcut target
                resolve_cmd = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    f"(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(target)}).TargetPath"
                ]
                result = subprocess.run(resolve_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                if result.returncode == 0 and result.stdout.strip():
                    # Got the actual exe path
                    exe_path = result.stdout.strip()
                    # Launch with accessibility flag
                    cmd = [
                        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        f"Start-Process -FilePath {_ps_quote(exe_path)} -ArgumentList {_ps_quote(accessibility_flag)} -WindowStyle Maximized"
                    ]
                else:
                    # Fallback to launching the shortcut directly (no flag)
                    cmd = [
                        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                        f"Start-Process -FilePath {_ps_quote(target)} -WindowStyle Maximized"
                    ]
            else:
                # Direct exe/executable path - add accessibility flag
                cmd = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    f"Start-Process -FilePath {_ps_quote(target)} -ArgumentList {_ps_quote(accessibility_flag)} -WindowStyle Maximized"
                ]
            
            r = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return r.returncode == 0
    except Exception:
        return False

def open_on_windows(app_name: str) -> bool:
    # Build candidate list from Start Menu + StartApps
    candidates = index_windows_start_menu() + index_windows_startapps()

    # Add PATH executables as lightweight candidates
    exe = shutil.which(app_name)
    if exe:
        candidates.append((app_name, exe, normalize(app_name)))
    for token in app_name.split():
        exe = shutil.which(token)
        if exe:
            candidates.append((token, exe, normalize(token)))

    # De-duplicate by (norm_name, target)
    dedup = {}
    for name, target, nn in candidates:
        dedup[(nn, target)] = (name, target, nn)
    candidates = list(dedup.values())

    name, target = best_match(app_name, candidates)
    if not target:
        return False
    return launch_windows_target(name, target)