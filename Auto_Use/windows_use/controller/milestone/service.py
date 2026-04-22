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

class MilestoneService:
    def __init__(self, cli_mode: bool = False, session_id: str = None):
        """Initialize the Milestone Service
        
        Args:
            cli_mode: If True, uses cli_milestone folder for isolation from main agent
            session_id: Optional unique session ID for isolated milestone folders (cli_mode only)
        """
        # Walk up two levels (controller/milestone -> windows_use) to locate the package root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        windows_use_dir = os.path.dirname(os.path.dirname(current_dir))

        if cli_mode:
            if session_id:
                self.milestone_dir = os.path.join(windows_use_dir, "scratchpad", "cli_milestone", session_id)
            else:
                self.milestone_dir = os.path.join(windows_use_dir, "scratchpad", "cli_milestone")
        else:
            self.milestone_dir = os.path.join(windows_use_dir, "scratchpad", "milestone")
        
        self.milestone_file = os.path.join(self.milestone_dir, "milestone.md")
        
        # Create milestone directory if it doesn't exist
        self._ensure_milestone_directory()
    
    def _ensure_milestone_directory(self):
        """Create milestone directory if it doesn't exist"""
        try:
            os.makedirs(self.milestone_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating milestone directory: {str(e)}")
            raise
    
    def append_milestone(self, milestone_content):
        """Append milestone content to milestone.md file with sequential numbering"""
        try:
            # Count existing milestones
            existing_count = 0
            if os.path.exists(self.milestone_file):
                with open(self.milestone_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():  # Count non-empty lines
                            existing_count += 1
            
            # Next milestone number
            next_number = existing_count + 1
            
            # Append with number prefix
            with open(self.milestone_file, "a", encoding="utf-8") as f:
                f.write(f"{next_number}. {milestone_content}\n")
            
            return True
            
        except Exception as e:
            logger.error(f"Error appending milestone: {str(e)}")
            return False
    
    def read_milestones(self):
        """Read current milestones content"""
        try:
            if os.path.exists(self.milestone_file):
                with open(self.milestone_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return ""
        except Exception as e:
            logger.error(f"Error reading milestones: {str(e)}")
            return ""
    
    def clear_milestones(self):
        """Clear the milestones file"""
        try:
            if os.path.exists(self.milestone_file):
                os.remove(self.milestone_file)
            return True
        except Exception as e:
            logger.error(f"Error clearing milestones: {str(e)}")
            return False