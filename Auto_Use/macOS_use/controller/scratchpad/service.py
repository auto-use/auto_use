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
import logging

# Configure logger
logger = logging.getLogger(__name__)

class ScratchpadService:
    def __init__(self, cli_mode: bool = False, session_id: str = None, minion_mode: bool = False):
        """Initialize the Scratchpad Service

        Args:
            cli_mode: If True, uses cli_milestone folder for isolation from main agent
            session_id: Optional unique session ID for isolated scratchpad folders (cli_mode only)
            minion_mode: If True, uses cli_minion folder so minion sub-agent sessions don't
                pollute the parent CLI agent's cli_milestone folder. Requires cli_mode=True.
        """
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up two levels from Auto_Use/macOS_use/controller/scratchpad/ to reach macOS_use/
        macos_use_dir = os.path.dirname(os.path.dirname(current_dir))

        # On-disk storage paths kept as "milestone/milestone.md" to preserve existing data
        # and avoid the scratchpad/scratchpad/scratchpad.md collision with the parent dir.
        if cli_mode and minion_mode:
            subdir = "cli_minion"
        elif cli_mode:
            subdir = "cli_milestone"
        else:
            subdir = "milestone"

        if cli_mode and session_id:
            self.scratchpad_dir = os.path.join(macos_use_dir, "scratchpad", subdir, session_id)
        else:
            self.scratchpad_dir = os.path.join(macos_use_dir, "scratchpad", subdir)

        self.scratchpad_file = os.path.join(self.scratchpad_dir, "milestone.md")

        # Create scratchpad directory if it doesn't exist
        self._ensure_scratchpad_directory()

    def _ensure_scratchpad_directory(self):
        """Create scratchpad directory if it doesn't exist"""
        try:
            os.makedirs(self.scratchpad_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating scratchpad directory: {str(e)}")
            raise

    def append_scratchpad(self, scratchpad_content):
        """Append a scratchpad entry with sequential numbering"""
        try:
            existing_count = 0
            if os.path.exists(self.scratchpad_file):
                with open(self.scratchpad_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            existing_count += 1

            next_number = existing_count + 1

            with open(self.scratchpad_file, "a", encoding="utf-8") as f:
                f.write(f"{next_number}. {scratchpad_content}\n")

            return True

        except Exception as e:
            logger.error(f"Error appending scratchpad entry: {str(e)}")
            return False

    def read_scratchpad(self):
        """Read current scratchpad content"""
        try:
            if os.path.exists(self.scratchpad_file):
                with open(self.scratchpad_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return ""
        except Exception as e:
            logger.error(f"Error reading scratchpad: {str(e)}")
            return ""

    def clear_scratchpad(self):
        """Clear the scratchpad file"""
        try:
            if os.path.exists(self.scratchpad_file):
                os.remove(self.scratchpad_file)
            return True
        except Exception as e:
            logger.error(f"Error clearing scratchpad: {str(e)}")
            return False
