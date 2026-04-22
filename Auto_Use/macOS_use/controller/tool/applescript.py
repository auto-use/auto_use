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

# Auto_Use/macOS_use/controller/tool/applescript.py
# macOS AppleScript tool — generic handler for any app
# Uses open_app() for activation/launching/main screen positioning
# Agent writes the action lines, service wraps with tell application + activation

import logging
import subprocess

from .open_app import _move_to_main_screen, _is_app_running, _bring_to_front

logger = logging.getLogger(__name__)


class AppleScriptService:
    """Generic AppleScript executor for any macOS app"""

    def __init__(self):
        pass

    @staticmethod
    def _strip_activate(script: str) -> str:
        """Remove 'activate' lines from an AppleScript to prevent new window creation."""
        lines = script.split('\n')
        filtered = [line for line in lines if line.strip().lower() != 'activate']
        return '\n'.join(filtered)

    def execute(self, app_name: str, action: str) -> dict:
        """
        Execute AppleScript action on a macOS app.

        Args:
            app_name: Application name (e.g., "Safari", "Mail", "Finder")
            action: AppleScript action lines to run inside tell application block

        Returns:
            dict: {status, action, app, command, output/error}
        """
        app_name = app_name.strip()
        action = action.strip()

        if not app_name or not action:
            return {
                "status": "error",
                "action": "applescript",
                "message": "Both app name and action are required"
            }

        app_running = _is_app_running(app_name)

        # Check if agent already sent a full tell application block
        action_stripped = action.strip().lower()
        if action_stripped.startswith("tell application"):
            if app_running:
                # Strip activate to prevent new window creation
                script = self._strip_activate(action.strip())
            else:
                # Inject activate after the first line to launch the app
                lines = action.strip().split('\n', 1)
                if len(lines) > 1:
                    script = f'{lines[0]}\n    activate\n{lines[1]}'
                else:
                    script = action.strip()
        else:
            if app_running:
                # No activate — just run the action in existing session
                script = f'''tell application "{app_name}"
    {action}
end tell'''
            else:
                # App not running — activate to launch it
                script = f'''tell application "{app_name}"
    activate
    {action}
end tell'''

        # Bring to front BEFORE executing (for already-running apps)
        if app_running:
            _bring_to_front(app_name)
            import time
            time.sleep(0.3)

        # Execute
        result = self._run(script)

        # If app was just launched, bring to front after activation
        if not app_running:
            import time
            time.sleep(0.5)
            _bring_to_front(app_name)

        # Move window to main display
        if result.get("status") == "success":
            _move_to_main_screen()

        result["app"] = app_name
        result["command"] = action
        return result

    def _run(self, script: str) -> dict:
        """Execute AppleScript via osascript and return structured result"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip()
                logger.error(f"AppleScript error: {error_msg}")
                return {
                    "status": "error",
                    "action": "applescript",
                    "message": error_msg
                }

            output = result.stdout.strip()
            logger.info(f"AppleScript success: {output[:200]}")
            return {
                "status": "success",
                "action": "applescript",
                "output": output
            }

        except subprocess.TimeoutExpired:
            logger.error("AppleScript timed out (30s)")
            return {
                "status": "error",
                "action": "applescript",
                "message": "Script timed out (30s)"
            }
        except Exception as e:
            logger.error(f"AppleScript execution failed: {e}")
            return {
                "status": "error",
                "action": "applescript",
                "message": str(e)
            }