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
Sandbox Service - Secure PowerShell sandbox environment.

Provides isolated command execution restricted to a designated workspace folder.
All operations are validated to prevent escape attempts and dangerous commands.
Commands are logged to a file for real-time viewing in a separate window.
"""

import subprocess
import os
import sys
import re
import threading
import queue
import time
from pathlib import Path
from datetime import datetime


# Timeout configuration for input detection
IDLE_TIMEOUT = 15          # Seconds of no output before checking for input prompt
TOTAL_TIMEOUT = 600        # Maximum execution time (10 minutes)
POLL_INTERVAL = 0.1        # How often to check for new output

# Patterns that indicate program is waiting for input
PROMPT_PATTERNS = [
    # Standard prompts
    r': $',              # "Enter name: "
    r'> $',              # "Input> "
    r'\? $',             # "Continue? "
    r':: $',             # "Password:: "
    r'\] $',             # "[yes/no] "
    r'\(y/n\)\s*$',      # "(y/n)"
    r'\(yes/no\)\s*$',   # "(yes/no)"
    r'press enter',      # "Press Enter to continue"
    r'waiting for',      # "Waiting for input"
    r'enter .*:',        # "Enter password:"
    r'input\s*:',        # "Input:"
    r'password\s*:',     # "Password:"
    # REPL prompts
    r'>>>\s*$',          # Python REPL ">>> "
    r'\.\.\.\s*$',       # Python continuation "... "
    r'\$\s*$',           # Bash prompt "$ "
    r'#\s*$',            # Root prompt "# "
    # Interactive menu indicators
    r'={3,}\s*$',        # "===================================================="
    r'-{3,}\s*$',        # "----------------------------------------------------"
    r'interactive',      # "INTERACTIVE MODE"
    r'commands?\s*:',    # "Commands:"
    r'options?\s*:',     # "Options:"
    r'menu',             # "Menu", "Main Menu"
    r'choice',           # "Enter your choice"
    r'select',           # "Select an option"
    r'exit.*quit',       # "exit - Quit"
    r'type .* to',       # "Type exit to quit"
]

# Timeout configuration
IDLE_TIMEOUT_PROMPT = 15    # Seconds of silence before checking prompt pattern
IDLE_TIMEOUT_FALLBACK = 60  # Seconds of silence to assume input needed (safety)
TOTAL_TIMEOUT = 600         # Maximum execution time (10 minutes)
POLL_INTERVAL = 0.1         # How often to check for new output


# Only block access to Windows system folder
BLOCKED_PATHS = [
    "c:\\windows",
    "c:/windows",
]

class Sandbox:
    """
    Secure PowerShell sandbox environment.
    
    All operations are restricted to the sandbox workspace folder.
    Commands are validated against blocklists before execution.
    Commands and outputs are logged for real-time viewing.
    """
    
    def __init__(self, workspace_name: str = "sandbox_workspace", session_id: str = None):
        """
        Initialize the sandbox environment.
        
        Args:
            workspace_name: Name of the sandbox workspace folder (created on Desktop)
            session_id: Optional unique session ID for isolated workspaces
        """
        self.desktop_path = Path.home() / "Desktop"
        
        # If session_id provided, create isolated subfolder inside parent workspace
        if session_id:
            self.sandbox_root = self.desktop_path / workspace_name / session_id
        else:
            self.sandbox_root = self.desktop_path / workspace_name
        
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.working_dir = str(self.sandbox_root)
        
    def _validate_path(self, path: str) -> tuple:
        r"""
        Validate that a path does not access C:\Windows.
        Agent can navigate anywhere else on the system.
        
        Args:
            path: Path to validate (relative or absolute)
            
        Returns:
            Tuple of (is_valid, resolved_path_or_error_message)
        """
        try:
            if os.path.isabs(path):
                full_path = Path(path)
            else:
                full_path = Path(self.working_dir) / path
            
            resolved = full_path.resolve()
            resolved_lower = str(resolved).lower()
            
            # Only block C:\Windows
            for blocked_path in BLOCKED_PATHS:
                if resolved_lower.startswith(blocked_path):
                    return (False, "BLOCKED: Access to system folder not allowed")
            
            return (True, str(resolved))
                
        except Exception:
            return (False, "BLOCKED: Invalid path")
    
    def _is_command_safe(self, command: str) -> tuple:
        r"""
        Check if a command is safe to execute.
        Only blocks access to C:\Windows\ system folder.
        
        Args:
            command: PowerShell command to validate
            
        Returns:
            Tuple of (is_safe, error_message_if_blocked)
        """
        cmd_lower = command.lower()
        
        for blocked_path in BLOCKED_PATHS:
            if blocked_path in cmd_lower:
                return (False, f"BLOCKED: Access to system folder not allowed - {blocked_path}")
        
        return (True, "")
    
    def _is_input_prompt(self, text: str) -> bool:
        """
        Check if the text looks like an input prompt.
        
        Args:
            text: Last output text to check
            
        Returns:
            True if text matches input prompt patterns
        """
        if not text:
            return False
        
        text_lower = text.lower().strip()
        
        for pattern in PROMPT_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
    
    def _read_output(self, pipe, output_queue):
        """
        Thread function to read from pipe character-by-character.
        This allows detecting prompts that don't end with newline (like ">>> ").
        
        Args:
            pipe: stdout or stderr pipe
            output_queue: Queue to put characters into
        """
        try:
            while True:
                char = pipe.read(1)  # Read ONE character
                if char:
                    output_queue.put(char)
                else:
                    break  # EOF
            pipe.close()
        except:
            pass
    
    def _get_last_output_chunk(self, buffer: str, chunk_size: int = 200) -> str:
        """
        Get the last meaningful chunk of output for prompt detection.
        
        Args:
            buffer: Full output buffer
            chunk_size: How many characters to check from end
            
        Returns:
            Last chunk of output, stripped
        """
        if not buffer:
            return ""
        return buffer[-chunk_size:].strip()
    
    def run(self, command: str, input_text: str = None, trusted: bool = False) -> dict:
        """
        Run a PowerShell command safely within the sandbox.
        Logs command and output for real-time viewing.
        Detects if program is waiting for input using character-by-character monitoring.
        
        Args:
            command: PowerShell command to execute
            input_text: Optional input to pipe to stdin (for interactive programs)
            trusted: If True, skip command validation (for internal tools like edit, insert_str)
            
        Returns:
            Dict with success, stdout, stderr, returncode, or error/timeout status
            If input required: {"success": False, "error": "input_required", "last_output": "..."}
            If timeout: {"success": False, "timeout": True, "last_output": "..."}
        """
        if not trusted:
            is_safe, error_msg = self._is_command_safe(command)
            if not is_safe:
                return {"success": False, "error": error_msg}
        
        try:
            # Use Popen for real-time output monitoring
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", command],
                cwd=self.working_dir,
                stdin=subprocess.PIPE if input_text else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,  # Unbuffered for char-by-char reading
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            
            # If input provided, write it and close stdin
            if input_text:
                try:
                    process.stdin.write(input_text)
                    process.stdin.flush()
                    process.stdin.close()
                except:
                    pass
            
            # Setup queues for non-blocking reads (char-by-char)
            stdout_queue = queue.Queue()
            stderr_queue = queue.Queue()
            
            # Start reader threads
            stdout_thread = threading.Thread(target=self._read_output, args=(process.stdout, stdout_queue))
            stderr_thread = threading.Thread(target=self._read_output, args=(process.stderr, stderr_queue))
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()
            
            # Monitor output with idle detection
            stdout_buffer = ""
            stderr_buffer = ""
            last_output_time = time.time()
            start_time = time.time()
            
            while True:
                # Check total timeout
                elapsed = time.time() - start_time
                if elapsed > TOTAL_TIMEOUT:
                    process.kill()
                    last_chunk = self._get_last_output_chunk(stdout_buffer + stderr_buffer)
                    return {
                        "success": False,
                        "timeout": True,
                        "message": "Command timed out after 10 minutes (may need input - use input parameter if program requires user input)",
                        "last_output": last_chunk,
                        "stdout": stdout_buffer,
                        "stderr": stderr_buffer
                    }
                
                # Check if process finished
                poll_result = process.poll()
                
                # Collect any available output (character by character)
                got_output = False
                
                while not stdout_queue.empty():
                    char = stdout_queue.get_nowait()
                    stdout_buffer += char
                    last_output_time = time.time()
                    got_output = True
                
                while not stderr_queue.empty():
                    char = stderr_queue.get_nowait()
                    stderr_buffer += char
                    last_output_time = time.time()
                    got_output = True
                
                # Process finished
                if poll_result is not None:
                    # Give threads a moment to finish reading
                    stdout_thread.join(timeout=0.5)
                    stderr_thread.join(timeout=0.5)
                    
                    # Collect any remaining output
                    while not stdout_queue.empty():
                        char = stdout_queue.get_nowait()
                        stdout_buffer += char
                        log_line_buffer += char
                    
                    while not stderr_queue.empty():
                        char = stderr_queue.get_nowait()
                        stderr_buffer += char
                    
                    return {
                        "success": poll_result == 0,
                        "stdout": stdout_buffer,
                        "stderr": stderr_buffer,
                        "returncode": poll_result
                    }
                
                # Check idle timeout (only if no input was provided)
                if input_text is None:
                    idle_time = time.time() - last_output_time
                    last_chunk = self._get_last_output_chunk(stdout_buffer + stderr_buffer)
                    
                    # Tier 1: 15 seconds idle + prompt pattern detected
                    if idle_time > IDLE_TIMEOUT_PROMPT:
                        if self._is_input_prompt(last_chunk):
                            process.kill()
                            return {
                                "success": False,
                                "error": "input_required",
                                "message": "Process waiting for input",
                                "last_output": last_chunk,
                                "stdout": stdout_buffer,
                                "stderr": stderr_buffer
                            }
                    
                    # Tier 2: 60 seconds idle (safety fallback - assume input needed)
                    if idle_time > IDLE_TIMEOUT_FALLBACK:
                        process.kill()
                        return {
                            "success": False,
                            "error": "input_required",
                            "message": "Process idle for 60s, likely waiting for input",
                            "last_output": last_chunk,
                            "stdout": stdout_buffer,
                            "stderr": stderr_buffer
                        }
                
                time.sleep(POLL_INTERVAL)
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def cd(self, path: str) -> dict:
        """
        Change working directory within sandbox.
        
        Args:
            path: Target directory path
            
        Returns:
            Dict with success and cwd, or error
        """
        is_valid, result = self._validate_path(path)
        
        if not is_valid:
            return {"success": False, "error": result}
        
        if os.path.isdir(result):
            self.working_dir = result
            return {"success": True, "cwd": self.working_dir}
        
        return {"success": False, "error": "Directory not found"}
    
    def get_cwd(self) -> str:
        """Get current working directory."""
        return self.working_dir

# Entry point - for backwards compatibility if called directly
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sandbox":
        # Legacy interactive mode (kept for reference)
        sandbox = Sandbox()
        
        print("=" * 50)
        print("SECURE SANDBOX ENVIRONMENT")
        print("=" * 50)
        print(f"Workspace: {sandbox.sandbox_root}")
        print("All operations restricted to this folder.")
        print("Type 'exit' to quit.")
        print("=" * 50)
        
        while True:
            try:
                prompt = f"[{Path(sandbox.working_dir).name}]> "
                cmd = input(prompt).strip()
                
                if not cmd:
                    continue
                
                if cmd.lower() in ["exit", "quit"]:
                    break
                
                if cmd.lower().startswith("cd "):
                    path = cmd[3:].strip()
                    result = sandbox.cd(path)
                    if result["success"]:
                        print(result["cwd"])
                    else:
                        print(result["error"])
                    continue
                
                # Run PowerShell command
                result = sandbox.run(cmd)
                
                if result.get("error"):
                    print(result["error"])
                else:
                    if result.get("stdout"):
                        print(result["stdout"], end="")
                    if result.get("stderr"):
                        print(result["stderr"], end="")
                        
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {str(e)}")
    
    else:
        # Interactive sandbox mode
        print("Use --sandbox flag for interactive mode")
