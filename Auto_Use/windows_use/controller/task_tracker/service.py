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
import json
import logging
from datetime import datetime

# Configure logger
logger = logging.getLogger(__name__)

class TaskTrackerService:
    def __init__(self, cli_mode: bool = False, session_id: str = None):
        """Initialize the Task Tracker Service
        
        Args:
            cli_mode: If True, uses cli_todo folder for isolation from main agent
            session_id: Optional unique session ID for isolated todo folders (cli_mode only)
        """
        # Walk up two levels (controller/task_tracker -> windows_use) to locate the package root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        windows_use_dir = os.path.dirname(os.path.dirname(current_dir))

        if cli_mode:
            if session_id:
                self.todo_dir = os.path.join(windows_use_dir, "scratchpad", "cli_todo", session_id)
            else:
                self.todo_dir = os.path.join(windows_use_dir, "scratchpad", "cli_todo")
        else:
            self.todo_dir = os.path.join(windows_use_dir, "scratchpad", "todo")
        
        self.todo_file = os.path.join(self.todo_dir, "todo.md")
        
        # Create todo directory if it doesn't exist
        self._ensure_todo_directory()
    
    def _ensure_todo_directory(self):
        """Create todo directory if it doesn't exist"""
        try:
            os.makedirs(self.todo_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating todo directory: {str(e)}")
            raise
    
    def save_todo(self, todo_content):
        """Save todo list content to markdown file with auto-numbering"""
        try:
            # Check if file is new
            is_new_file = not os.path.exists(self.todo_file)
            
            # Auto-number the tasks
            numbered_content = self._add_task_numbers(todo_content)
            
            # Write to file (overwrite mode)
            with open(self.todo_file, "w", encoding="utf-8") as f:
                f.write(numbered_content)
            
            # Silent save - no terminal output
            return True
            
        except Exception as e:
            logger.error(f"Error saving todo list: {str(e)}")
            return False
    
    def _add_task_numbers(self, todo_content):
        """Add #1., #2., etc. numbering to each task line"""
        lines = todo_content.split('\n')
        numbered_lines = []
        task_number = 1
        
        for line in lines:
            # Check if line is a task (starts with - [ ] or - [x])
            stripped = line.strip()
            if stripped.startswith('- [ ]') or stripped.startswith('- [x]'):
                # Add number prefix
                numbered_lines.append(f"#{task_number}. {stripped}")
                task_number += 1
            else:
                # Keep non-task lines as-is (like Objective:)
                numbered_lines.append(line)
        
        return '\n'.join(numbered_lines)
    
    def update_task(self, task_number):
        """Update a task in the todo list by marking task #number as complete"""
        try:
            # Read current todo content
            if not os.path.exists(self.todo_file):
                logger.warning("Todo file doesn't exist")
                return False
            
            with open(self.todo_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Convert task_number to int if it's a string
            try:
                task_num = int(task_number)
            except (ValueError, TypeError):
                logger.warning(f"Invalid task number: {task_number}")
                return False
            
            # Find and update the line with matching #number
            lines = content.split('\n')
            updated = False
            
            for i, line in enumerate(lines):
                # Check if line starts with the task number (e.g., "#1. - [ ]")
                if line.strip().startswith(f"#{task_num}."):
                    # Check if already marked complete
                    if "- [x]" in line:
                        logger.info(f"Task #{task_num} already completed")
                        return True
                    
                    # Mark as complete: replace [ ] with [x]
                    lines[i] = line.replace("- [ ]", "- [x]", 1)
                    updated = True
                    logger.info(f"Marked task #{task_num} as complete")
                    break
            
            if updated:
                # Write back to file
                with open(self.todo_file, "w", encoding="utf-8") as f:
                    f.write('\n'.join(lines))
                return True
            else:
                logger.warning(f"Task #{task_num} not found in todo list")
                # Return True anyway to avoid blocking the workflow
                return True
                
        except Exception as e:
            logger.error(f"Error updating task: {str(e)}")
            return False