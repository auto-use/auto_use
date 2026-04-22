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


class ShellService:
    """Lightweight shell for main agent - quick commands via sandboxed Desktop environment"""
    
    def __init__(self):
        """Initialize ShellService with Sandbox pointing to existing sandbox_workspace"""
        self.sandbox = Sandbox()
    
    def run(self, command: str, input_text: str = None) -> dict:
        """
        Execute a shell command and return formatted result.
        
        Args:
            command: shell command to execute
            input_text: Optional stdin input for interactive commands
            
        Returns:
            dict with agent_location, shell, status, output
        """
        try:
            result = self.sandbox.run(command, input_text)
            
            agent_location = self.sandbox.get_cwd()
            
            # Handle input_required
            if result.get("error") == "input_required":
                output = ""
                if result.get("stdout"):
                    output += result["stdout"]
                if result.get("stderr"):
                    output += result["stderr"]
                
                response = {
                    "status": "input_required",
                    "action": "shell",
                    "agent_location": agent_location,
                    "shell": command,
                    "message": f"Process waiting for input. Last output: '{result.get('last_output', '')}'. Use input parameter."
                }
                if output.strip():
                    response["output"] = output.strip()
                return response
            
            # Handle timeout
            if result.get("timeout"):
                output = ""
                if result.get("stdout"):
                    output += result["stdout"]
                if result.get("stderr"):
                    output += result["stderr"]
                
                response = {
                    "status": "timeout",
                    "action": "shell",
                    "agent_location": agent_location,
                    "shell": command,
                    "message": result.get("message", "Command timed out")
                }
                if output.strip():
                    response["output"] = output.strip()
                return response
            
            # Normal result
            output = ""
            if result.get("stdout"):
                output += result["stdout"]
            if result.get("stderr"):
                output += result["stderr"]
            
            response = {
                "status": "success" if result.get("success") else "failed",
                "action": "shell",
                "agent_location": agent_location,
                "shell": command,
            }
            
            if output.strip():
                response["output"] = output.strip()
            
            error = result.get("error", "")
            if error:
                response["error"] = error
            
            return response
            
        except Exception as e:
            logger.error(f"ShellService error: {str(e)}")
            return {
                "status": "failed",
                "action": "shell",
                "agent_location": self.sandbox.get_cwd(),
                "shell": command,
                "error": str(e)
            }