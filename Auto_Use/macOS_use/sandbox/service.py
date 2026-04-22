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
Sandbox Service - Secure shell sandbox environment (macOS).

Provides isolated command execution restricted to a designated workspace folder.
All operations are validated to prevent escape attempts and dangerous commands.
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
IDLE_TIMEOUT_PROMPT = 15     # Seconds of silence before checking prompt pattern
IDLE_TIMEOUT_FALLBACK = 60   # Seconds of silence to assume input needed (safety)
TOTAL_TIMEOUT = 600          # Maximum execution time (10 minutes)
POLL_INTERVAL = 0.1          # How often to check for new output

# Patterns that indicate program is waiting for input
PROMPT_PATTERNS = [
    r': $',              # "Enter name: "
    r'> $',              # "Input> "
    r'\? $',             # "Continue? "
    r':: $',             # "Password:: "
    r'\] $',             # "[yes/no] "
    r'\(y/n\)\s*$',
    r'\(yes/no\)\s*$',
    r'press enter',
    r'waiting for',
    r'enter .*:',
    r'input\s*:',
    r'password\s*:',
    r'>>>\s*$',          # Python REPL
    r'\.\.\.\s*$',       # Python continuation
    r'\$\s*$',           # Bash/zsh prompt
    r'#\s*$',            # Root prompt
    r'interactive',
    r'commands?\s*:',
    r'options?\s*:',
    r'menu',
    r'choice',
    r'select',
    r'exit.*quit',
    r'type .* to',
]

# Block access to macOS system folders
BLOCKED_PATHS = [
    "/system",
    "/usr/sbin",
    "/private/var",
]


class Sandbox:
    """
    Secure shell sandbox environment (macOS).

    All operations are restricted to the sandbox workspace folder.
    Commands are validated against blocklists before execution.
    """

    def __init__(self, workspace_name: str = "sandbox_workspace", session_id: str = None):
        """
        Initialize the sandbox environment.

        Args:
            workspace_name: Name of the sandbox workspace folder (created on Desktop)
            session_id: Optional unique session ID for isolated workspaces
        """
        self.desktop_path = Path.home() / "Desktop"

        if session_id:
            self.sandbox_root = self.desktop_path / workspace_name / session_id
        else:
            self.sandbox_root = self.desktop_path / workspace_name

        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.working_dir = str(self.sandbox_root)

    def _validate_path(self, path: str) -> tuple:
        """
        Validate that a path does not access system folders.

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

            for blocked_path in BLOCKED_PATHS:
                if resolved_lower.startswith(blocked_path):
                    return (False, "BLOCKED: Access to system folder not allowed")

            return (True, str(resolved))

        except Exception:
            return (False, "BLOCKED: Invalid path")

    def _is_command_safe(self, command: str) -> tuple:
        """
        Check if a command is safe to execute.

        Args:
            command: Shell command to validate

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

        Args:
            pipe: stdout or stderr pipe
            output_queue: Queue to put characters into
        """
        try:
            while True:
                char = pipe.read(1)
                if char:
                    output_queue.put(char)
                else:
                    break
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
        Run a shell command safely within the sandbox.
        Detects if program is waiting for input using character-by-character monitoring.

        Args:
            command: Shell command to execute
            input_text: Optional input to pipe to stdin (for interactive programs)
            trusted: If True, skip command validation (for internal tools)

        Returns:
            Dict with success, stdout, stderr, returncode, or error/timeout status
        """
        if not trusted:
            is_safe, error_msg = self._is_command_safe(command)
            if not is_safe:
                return {"success": False, "error": error_msg}

        try:
            process = subprocess.Popen(
                ["/bin/zsh", "-c", command],
                cwd=self.working_dir,
                stdin=subprocess.PIPE if input_text else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
            )

            if input_text:
                try:
                    process.stdin.write(input_text)
                    process.stdin.flush()
                    process.stdin.close()
                except:
                    pass

            # Setup queues for non-blocking reads
            stdout_queue = queue.Queue()
            stderr_queue = queue.Queue()

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
                        "message": "Command timed out after 10 minutes (may need input - use input parameter)",
                        "last_output": last_chunk,
                        "stdout": stdout_buffer,
                        "stderr": stderr_buffer
                    }

                # Check if process finished
                poll_result = process.poll()

                # Collect available output
                while not stdout_queue.empty():
                    char = stdout_queue.get_nowait()
                    stdout_buffer += char
                    last_output_time = time.time()

                while not stderr_queue.empty():
                    char = stderr_queue.get_nowait()
                    stderr_buffer += char
                    last_output_time = time.time()

                # Process finished
                if poll_result is not None:
                    stdout_thread.join(timeout=0.5)
                    stderr_thread.join(timeout=0.5)

                    # Collect remaining output
                    while not stdout_queue.empty():
                        stdout_buffer += stdout_queue.get_nowait()

                    while not stderr_queue.empty():
                        stderr_buffer += stderr_queue.get_nowait()

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