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
from pathlib import Path

from ...sandbox import Sandbox

logger = logging.getLogger(__name__)


class CLIService:
    """Service for CLI agent actions - executes commands via sandbox"""
    
    def __init__(self, session_id: str = None):
        """Initialize CLI Service with sandbox connection
        
        Args:
            session_id: Optional unique session ID for isolated sandbox workspace
        """
        self.sandbox = Sandbox(session_id=session_id)
    
    def write(self, path: str, line: int, content: str) -> dict:
        """
        Write content into a file at a specific line.
        If file doesn't exist, creates it. Existing lines from the insertion
        point onward are shifted down.
        
        Args:
            path: File path (relative to sandbox)
            line: Line number to insert at (1-indexed)
            content: Content to write (can be multi-line with \n)
            
        Returns:
            dict: Formatted response for agent with last_line
        """
        command_str = f'write path="{path}", line={line}'
        
        try:
            full_path = Path(self.sandbox.working_dir) / path
            
            # Create parent directory if needed
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Read existing content if file exists
            existing_lines = []
            if full_path.exists():
                read_cmd = f"Get-Content -Path '{path}' -Encoding UTF8"
                result = self.sandbox.run(read_cmd, trusted=True)
                if result.get("success"):
                    raw_content = result.get("stdout", "")
                    if raw_content.strip():
                        existing_lines = raw_content.rstrip('\n').split('\n')
            
            # Split new content into lines
            new_lines = content.split('\n')
            # Remove trailing empty string from split if content ends with \n
            if new_lines and new_lines[-1] == '':
                new_lines.pop()
            
            # Insert new lines at the specified position
            insert_index = max(0, line - 1)  # Convert to 0-indexed
            for i, new_line in enumerate(new_lines):
                existing_lines.insert(insert_index + i, new_line)
            
            # Write back
            final_content = '\n'.join(existing_lines)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            # Verify and get final line count
            if full_path.exists():
                verify_content = full_path.read_text(encoding='utf-8')
                final_lines = verify_content.rstrip('\n').split('\n') if verify_content.strip() else ['']
                last_line = len(final_lines) + 1  # +1 for the extra blank line (matches view behavior)
                
                return {
                    "status": "success",
                    "action": "write",
                    "command": command_str,
                    "output": f"Written {len(final_lines)} lines at line {line}. Last empty line: {last_line}",
                    "last_line": last_line
                }
            else:
                return {
                    "status": "failed",
                    "action": "write",
                    "command": command_str,
                    "output": "Write failed - file does not exist after write"
                }
                
        except Exception as e:
            return {
                "status": "failed",
                "action": "write",
                "command": command_str,
                "output": str(e)
            }
    
    def shell(self, command: str, input_text: str = None) -> dict:
        """
        Execute a PowerShell command in the sandbox
        
        Args:
            command: PowerShell command to execute
            input_text: Optional input to pipe to stdin (for interactive programs)
            
        Returns:
            dict: Result with cwd, command, output (only if present)
            Status can be: "success", "error", "timeout", "input_required"
        """
        try:
            result = self.sandbox.run(command, input_text)
            
            # Handle input_required error specially
            if result.get("error") == "input_required":
                last_output = result.get("last_output", "")
                output = ""
                if result.get("stdout"):
                    output += result["stdout"]
                if result.get("stderr"):
                    output += result["stderr"]
                
                response = {
                    "status": "input_required",
                    "action": "shell",
                    "cwd": self.sandbox.get_cwd(),
                    "command": command,
                    "message": f"Process waiting for input. Last output: '{last_output}'. Use input parameter with shell command."
                }
                
                if output.strip():
                    response["output"] = output.strip()
                
                return response
            
            # Handle timeout specially
            if result.get("timeout"):
                last_output = result.get("last_output", "")
                output = ""
                if result.get("stdout"):
                    output += result["stdout"]
                if result.get("stderr"):
                    output += result["stderr"]
                
                response = {
                    "status": "timeout",
                    "action": "shell",
                    "cwd": self.sandbox.get_cwd(),
                    "command": command,
                    "message": result.get("message", "Command timed out (may need input - use input parameter if program requires user input)")
                }
                
                if output.strip():
                    response["output"] = output.strip()
                
                return response
            
            output = ""
            if result.get("stdout"):
                output += result["stdout"]
            if result.get("stderr"):
                output += result["stderr"]
            
            response = {
                "status": "success" if result.get("success") else "error",
                "action": "shell",
                "cwd": self.sandbox.get_cwd(),
                "command": command
            }
            
            # Only include output if there's actual content
            if output.strip():
                response["output"] = output.strip()
            
            # Only include error if there's actual content
            error = result.get("error", "")
            if error:
                response["error"] = error
            
            return response
            
        except Exception as e:
            logger.error(f"Shell execution error: {str(e)}")
            return {
                "status": "error",
                "action": "shell",
                "cwd": self.sandbox.get_cwd(),
                "command": command,
                "error": str(e)
            }
    
    def replace(self, path: str, line: int, old_block: str, new_block: str) -> dict:
        """
        Replace a block of lines in a file starting at a specific line.
        
        Reads N lines from `line` downward (where N = lines in old_block),
        verifies exact match, then swaps in new_block (any number of lines).
        
        Args:
            path: File path (relative to sandbox)
            line: Starting line number (1-indexed)
            old_block: Expected block at that position (multi-line with \\n)
            new_block: New block to replace with (multi-line with \\n)
            
        Returns:
            dict: Formatted response for agent with last_line
        """
        command_str = f'replace path="{path}", line={line}'
        
        try:
            # PRE-CHECK: Read file
            read_cmd = f"Get-Content -Path '{path}' -Encoding UTF8"
            result = self.sandbox.run(read_cmd, trusted=True)
            
            if not result.get("success"):
                error_output = result.get("stderr", "") or result.get("error", "File not found")
                return {
                    "status": "failed",
                    "action": "replace",
                    "command": command_str,
                    "output": error_output
                }
            
            # Parse file lines
            raw_content = result.get("stdout", "")
            file_lines = raw_content.rstrip('\n').split('\n')
            
            # Split old_block into lines
            old_lines = old_block.split('\n')
            if old_lines and old_lines[-1] == '':
                old_lines.pop()
            old_count = len(old_lines)
            
            # Range check
            if line < 1 or line > len(file_lines):
                return {
                    "status": "failed",
                    "action": "replace",
                    "command": command_str,
                    "output": f"line {line} out of range (file has {len(file_lines)} lines)"
                }
            
            end_line = line - 1 + old_count  # 0-indexed end (exclusive)
            if end_line > len(file_lines):
                return {
                    "status": "failed",
                    "action": "replace",
                    "command": command_str,
                    "output": f"old_block has {old_count} lines but only {len(file_lines) - (line - 1)} lines remain from line {line}"
                }
            
            # Extract actual block from file and compare
            actual_lines = file_lines[line - 1 : end_line]
            
            if actual_lines != old_lines:
                # Show first mismatched line to help LLM correct
                for i, (actual, expected) in enumerate(zip(actual_lines, old_lines)):
                    if actual != expected:
                        mismatch_line = line + i
                        return {
                            "status": "failed",
                            "action": "replace",
                            "command": command_str,
                            "output": f'mismatch at line {mismatch_line}: found "{actual}" expected "{expected}"'
                        }
                # Length mismatch
                return {
                    "status": "failed",
                    "action": "replace",
                    "command": command_str,
                    "output": f"block length mismatch: file has {len(actual_lines)} lines, old_block has {old_count} lines"
                }
            
            # REPLACE: Swap old block with new block
            new_lines = new_block.split('\n')
            if new_lines and new_lines[-1] == '':
                new_lines.pop()
            
            file_lines[line - 1 : end_line] = new_lines
            new_content = '\n'.join(file_lines)
            
            # Write back
            full_path = Path(self.sandbox.working_dir) / path
            try:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
            except Exception as write_error:
                return {
                    "status": "failed",
                    "action": "replace",
                    "command": command_str,
                    "output": str(write_error)
                }
            
            # POST-CHECK: Verify new_block is at that position
            verify_result = self.sandbox.run(read_cmd, trusted=True)
            
            if verify_result.get("success"):
                verify_content = verify_result.get("stdout", "")
                verify_lines = verify_content.rstrip('\n').split('\n')
                new_count = len(new_lines)
                
                verify_slice = verify_lines[line - 1 : line - 1 + new_count]
                if verify_slice == new_lines:
                    last_line = len(verify_lines) + 1
                    return {
                        "status": "success",
                        "action": "replace",
                        "command": command_str,
                        "output": f"replaced {old_count} lines with {new_count} lines at line {line}. Last empty line: {last_line}",
                        "last_line": last_line
                    }
            
            return {
                "status": "failed",
                "action": "replace",
                "command": command_str,
                "output": "replace verification failed after write"
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "action": "replace",
                "command": command_str,
                "output": str(e)
            }
    
    def view(self, path: str) -> dict:
        """
        View file contents with line numbers.
        Always appends an extra blank line at the end so the agent has a valid
        line number to target for appending. Empty files show [1] (blank).
        
        Args:
            path: File path (relative to sandbox)
            
        Returns:
            dict: Formatted response for agent with indexed lines
        """
        try:
            full_path = Path(self.sandbox.working_dir) / path
            
            # If file doesn't exist, return empty file with [1]
            if not full_path.exists():
                return {
                    "status": "success",
                    "action": "view",
                    "command": f'view path="{path}"',
                    "output": "[1] ",
                    "last_line": 1
                }
            
            # Read file
            command = f"Get-Content -Path '{path}' -Encoding UTF8"
            result = self.sandbox.run(command, trusted=True)
            
            if result.get("success"):
                raw_content = result.get("stdout", "")
                
                if not raw_content.strip():
                    # Empty file — show single blank line
                    return {
                        "status": "success",
                        "action": "view",
                        "command": f'view path="{path}"',
                        "output": "[1] ",
                        "last_line": 1
                    }
                
                # Add line numbers [1], [2], etc. + extra blank line at end
                lines = raw_content.rstrip('\n').split('\n')
                lines.append("")  # Extra blank line for append target
                indexed_lines = [f"[{i+1}] {line}" for i, line in enumerate(lines)]
                indexed_output = '\n'.join(indexed_lines)
                
                return {
                    "status": "success",
                    "action": "view",
                    "command": f'view path="{path}"',
                    "output": indexed_output,
                    "last_line": len(lines)
                }
            else:
                error_output = result.get("stderr", "") or result.get("error", "Unknown error")
                return {
                    "status": "failed",
                    "action": "view",
                    "command": f'view path="{path}"',
                    "output": error_output
                }
                
        except Exception as e:
            return {
                "status": "failed",
                "action": "view",
                "command": f'view path="{path}"',
                "output": str(e)
            }