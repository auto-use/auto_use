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
import time
import json
import re
import sys
import io
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional
import threading

import webview
import win32gui
import win32con

from ...llm_provider.llm_manager import LLMManager
from ...controller.view import ControllerView
from .view import CLIAgentResponseFormatter

# Import debug_log and IS_COMPILED for safe logging in compiled mode
try:
    from app import debug_log, IS_COMPILED
except ImportError:
    def debug_log(msg, level="INFO"):
        pass
    IS_COMPILED = False

# =============================================================================
# FIX FOR COMPILED CLI SUBPROCESS: Ensure stdout/stderr are valid
# In compiled Windows apps with CREATE_NO_WINDOW, these can be None/closed
# =============================================================================
if sys.stdout is None or (hasattr(sys.stdout, 'closed') and sys.stdout.closed):
    sys.stdout = io.StringIO()

if sys.stderr is None or (hasattr(sys.stderr, 'closed') and sys.stderr.closed):
    sys.stderr = io.StringIO()

# Safe print function that won't crash on closed stdout
def safe_print(*args, **kwargs):
    """Print that won't crash if stdout is unavailable"""
    try:
        print(*args, **kwargs)
    except (ValueError, OSError, AttributeError):
        # I/O operation on closed file or similar - just log instead
        msg = ' '.join(str(a) for a in args)
        debug_log(f"[PRINT] {msg}")

# Actions that execute PowerShell commands (show in terminal UI)
TERMINAL_ACTIONS = {"shell", "replace", "write", "view"}

# Maximum iterations before CLI agent auto-exits (prevents infinite loops)
MAX_CLI_ITERATIONS = 50


class AgentService:
    """CLI Agent Service - Agentic loop only"""
    
    def __init__(self, provider: str, model: str, save_conversation: bool = False,
                 thinking: bool = True, api_key: str = None, stop_event=None,
                 task: str = None, on_complete: callable = None, position: int = 0):
        
        self.provider = provider
        self.model = model
        self.save_conversation = save_conversation
        self.stop_event = stop_event
        self.task = task  # Task description (for tracking when called as service)
        self.on_complete = on_complete  # Callback when CLI agent exits
        self.position = position % 4  # Corner index: 0=TL, 1=TR, 2=BL, 3=BR
        
        # Generate unique session ID for complete isolation
        self.session_id = uuid.uuid4().hex[:8]
        
        # Initialize LLM Manager
        self.llm = LLMManager(
            provider=provider, 
            model=model, 
            thinking=thinking,
            api_key=api_key,
            cli_agent=True
        )
        
        # Initialize Controller with cli_mode and session_id for complete isolation
        self.controller = ControllerView(provider=provider, model=model, cli_mode=True, session_id=self.session_id, api_key=api_key)
        
        # Stream buffer for terminal UI
        self._stream_buffer = []
        self._stream_lock = threading.Lock()
        self._webview_window = None
        self._ui_started = False
        
        # Load system prompt
        self.system_prompt = self._load_system_prompt()
        
        # Setup session-specific conversation directory (subfolder inside cli_conversation)
        if self.save_conversation:
            self.conversation_dir = Path("cli_conversation") / self.session_id
            self.conversation_dir.mkdir(parents=True, exist_ok=True)
            
            # Create raw_reasoning directory for storing raw LLM outputs (for debugging)
            self.raw_reasoning_dir = self.conversation_dir / "raw_reasoning"
            self.raw_reasoning_dir.mkdir(parents=True, exist_ok=True)
        
        self.interaction_count = 0
        self._pending_web_response = ""  # Store web response for next iteration
    
    def _save_conversation_snapshot(self, messages: list, current_assistant_response: str, interaction_count: int):
        """Save TRUE agent memory - exactly what LLM receives at each step
        
        Dumps the actual messages list sent to the API. One source of truth.
        """
        if not self.save_conversation:
            return
        
        conversation_file = self.conversation_dir / f"conversation_{interaction_count}.txt"
        
        with open(conversation_file, 'w', encoding='utf-8') as f:
            # Header
            f.write("=== CLI AGENT MEMORY SNAPSHOT ===\n")
            f.write(f"Step: {interaction_count}\n")
            f.write(f"Time: {datetime.now()}\n")
            f.write("=" * 60 + "\n\n")
            
            # Dump every message exactly as sent to the API
            for i, msg in enumerate(messages):
                role = msg["role"]
                content = msg["content"]
                f.write(f"=== MESSAGE {i} (role='{role}') ===\n")
                if isinstance(content, list):
                    text = content[0]["text"] if content and isinstance(content[0], dict) and "text" in content[0] else str(content)
                    f.write(text)
                else:
                    f.write(content)
                f.write("\n\n" + "=" * 60 + "\n\n")
            
            # Current assistant response (not yet in messages list)
            f.write(f"=== CURRENT ASSISTANT RESPONSE (role='assistant') ===\n")
            f.write(current_assistant_response)
            f.write("\n")
    
    def _save_raw_response(self, raw_response: str, step_number: int):
        """Save raw LLM response before any parsing/normalization (for debugging)"""
        if self.save_conversation:
            try:
                raw_file = self.raw_reasoning_dir / f"raw_response_{step_number}.txt"
                with open(raw_file, 'w', encoding='utf-8') as f:
                    f.write(raw_response)
            except Exception as e:
                safe_print(f"⚠ Error saving raw response: {str(e)}")
    
    def _push_stream(self, msg_type: str, content):
        """Push message to stream buffer for terminal UI
        
        Args:
            msg_type: 'thinking', 'current_goal', 'memory', 'shell_command', 'error', 'exit'
            content: Message content (str or dict for shell_command)
        """
        with self._stream_lock:
            self._stream_buffer.append({
                "type": msg_type,
                "content": content
            })
    
    def _stream_terminal_action(self, action_result: dict):
        """Stream terminal action results as PowerShell commands
        
        Args:
            action_result: Result from controller.route_action()
        """
        action_type = action_result.get("action")
        
        # Handle single terminal action
        if action_type in TERMINAL_ACTIONS:
            cwd = action_result.get("cwd", self.controller.cli_service.sandbox.get_cwd())
            command = action_result.get("command", "")
            output = action_result.get("output", "")
            status = action_result.get("status", "success")
            
            self._push_stream("shell_command", {
                "cwd": cwd,
                "command": command,
                "output": output,
                "status": status
            })
        
        # Handle multiple actions
        elif action_type == "multiple":
            results = action_result.get("results", [])
            for result in results:
                if result.get("action") in TERMINAL_ACTIONS:
                    cwd = result.get("cwd", self.controller.cli_service.sandbox.get_cwd())
                    command = result.get("command", "")
                    output = result.get("output", "")
                    status = result.get("status", "success")
                    
                    self._push_stream("shell_command", {
                        "cwd": cwd,
                        "command": command,
                        "output": output,
                        "status": status
                    })
    
    def get_stream_messages(self):
        """Get and clear stream buffer (called by JS via pywebview API)"""
        with self._stream_lock:
            messages = self._stream_buffer.copy()
            self._stream_buffer.clear()
            return messages
    
    def _send_window_to_back(self):
        """Send the pywebview terminal window to back of z-order"""
        try:
            # Small delay to ensure window is fully created
            time.sleep(0.3)
            
            # Find window by title
            hwnd = win32gui.FindWindow(None, 'Auto_use_CLI')
            if hwnd:
                # Send to bottom of z-order without changing size/position
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_BOTTOM,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                )
        except Exception as e:
            safe_print(f"Could not send window to back: {e}")
    
    @staticmethod
    def _get_terminal_position(corner: int = 0, win_width: int = 550, win_height: int = 600):
        """Calculate dynamic window position based on screen geometry, DPI scaling, and corner index.
        
        Queries:
        - System DPI scaling (100%, 125%, 150%, etc.)
        - Primary monitor work area (excludes taskbar)
        
        Args:
            corner: 0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right
            win_width: Window width in pixels
            win_height: Window height in pixels
        
        Returns:
            tuple: (x, y) for positioning with consistent visual gap
        """
        try:
            import ctypes
            import ctypes.wintypes
            
            # Query system DPI (96=100%, 120=125%, 144=150%, 192=200%)
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
            except AttributeError:
                dpi = 96
            scale = dpi / 96.0
            
            # Get primary monitor work area (usable rect excluding taskbar)
            work_area = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(work_area), 0  # SPI_GETWORKAREA
            )
            
            # ~10 device-independent pixels gap
            gap = max(5, round(10 / scale))
            
            area_width = work_area.right - work_area.left
            area_height = work_area.bottom - work_area.top
            
            if corner == 0:      # Top-left
                x = work_area.left + gap
                y = work_area.top + gap
            elif corner == 1:    # Top-right
                x = work_area.left + area_width - win_width - gap
                y = work_area.top + gap
            elif corner == 2:    # Bottom-left
                x = work_area.left + gap
                y = work_area.top + area_height - win_height - gap
            else:                # Bottom-right
                x = work_area.left + area_width - win_width - gap
                y = work_area.top + area_height - win_height - gap
            
            return x, y
            
        except Exception:
            return 30, 30  # Fallback to original

    def _create_terminal_window(self):
        """Create PyWebView terminal window (start happens on main thread)"""
        if IS_COMPILED:
            # Compiled mode - serve from main Flask server (embedded resources)
            terminal_url = 'http://127.0.0.1:5000/terminal/index.html'
        else:
            # Dev mode - use file path directly
            terminal_url = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', '..', 'sandbox', 'terminal', 'index.html'
            ))
        
        agent_ref = self

        class API:
            def get_messages(api_self):
                return agent_ref.get_stream_messages()
        
        win_x, win_y = self._get_terminal_position(corner=self.position)
        
        self._webview_window = webview.create_window(
            title='Auto_use_CLI',
            url=terminal_url,
            width=550,
            height=600,
            x=win_x,
            y=win_y,
            resizable=True,
            background_color='#FFFFFF',
            js_api=API()
        )
    
    def _load_system_prompt(self) -> str:
        """Load system prompt from file"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(current_dir, "system_prompt.md")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _remove_thinking_from_response(self, response_json: str) -> str:
        """Remove 'thinking' field from assistant response to save tokens in history"""
        try:
            response_data = json.loads(response_json)
            
            # Remove thinking field if it exists
            if "thinking" in response_data:
                del response_data["thinking"]
            
            return json.dumps(response_data, indent=2, ensure_ascii=False)
        except Exception:
            return response_json
    
    def _remove_agent_sitting_from_user_message(self, user_message: str) -> str:
        """Remove <agent_sitting> block from user message to save tokens in history"""
        try:
            # Remove <agent_sitting>...</agent_sitting> block
            cleaned = re.sub(r'<agent_sitting>.*?</agent_sitting>', '', user_message, flags=re.DOTALL)
            # Clean up extra whitespace
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            return cleaned.strip()
        except Exception:
            return user_message
    
    def _read_todo_from_file(self) -> str:
        """Read the current todo list from cli_todo/todo.md file"""
        try:
            todo_file = Path(self.controller.task_tracker.todo_file)
            if todo_file.exists():
                with open(todo_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            else:
                return ""
        except Exception as e:
            return ""
    
    def _get_agent_sitting(self) -> str:
        """Get agent workspace and current directory info"""
        workspace = str(self.controller.cli_service.sandbox.sandbox_root)
        current = self.controller.cli_service.sandbox.get_cwd()
        return f"your_workspace: {workspace}\ncurrent_sitting: {current}"
    
    def process_request(self, task: str) -> str:
        """Start UI on main thread and run agent loop in background"""
        if not self._ui_started:
            self._ui_started = True
            self._create_terminal_window()
            
            def start_agent():
                # Send window to back after it's created
                threading.Thread(target=self._send_window_to_back, daemon=True).start()
                # Start the agent loop
                threading.Thread(target=self._run_agent_loop, args=(task,), daemon=True).start()
            
            webview.start(func=start_agent)
            return ""
        
        return self._run_agent_loop(task)
     
    def _run_agent_loop(self, task: str) -> str:
        """Main agentic loop"""
        
        step_number = 0
        last_response = None
        is_first = True
        history = []  # List of (assistant_response, tool_response) tuples
        json_fail_count = 0  # Track consecutive JSON parse failures (max 3 before exit)
        
        while True:
            # Check stop
            if self.stop_event and self.stop_event.is_set():
                safe_print("Agent stopped.")
                break
            
            step_number += 1
            
            # Check max iterations limit
            if step_number > MAX_CLI_ITERATIONS:
                safe_print(f"CLI Agent reached max iterations ({MAX_CLI_ITERATIONS})")
                
                # Read current todo to report what's done/pending
                todo_status = self._read_todo_from_file()
                summary = f"Max iterations ({MAX_CLI_ITERATIONS}) reached. Task incomplete. Todo status:\n{todo_status}"
                
                self._push_stream("exit", f"Max iterations reached ({MAX_CLI_ITERATIONS}). Returning to main agent.")
                
                # Notify main agent with partial status
                if self.on_complete:
                    self.on_complete({
                        "task": self.task,
                        "summary": summary,
                        "status": "partial"
                    })
                
                # Close the terminal window after a brief delay
                def close_window():
                    time.sleep(2)
                    if self._webview_window:
                        self._webview_window.destroy()
                threading.Thread(target=close_window, daemon=True).start()
                
                return "Max iterations reached"
            
            safe_print(f"cli agent running step {step_number}")
            
            # Get agent sitting info
            agent_sitting = self._get_agent_sitting()
            
            # Read fresh todo
            todo_list = self._read_todo_from_file()
            
            # Build user message (tool_response now in history, not here)
            if is_first:
                user_message = f"<user_request>\n{task}\n</user_request>\n\n<agent_sitting>\n{agent_sitting}\n</agent_sitting>"
            else:
                user_message = f"<user_request>\n{task}\n</user_request>\n\n<todo_list>\n{todo_list}\n</todo_list>\n\n<agent_sitting>\n{agent_sitting}\n</agent_sitting>"
                
                # Inject web tool response if pending from previous iteration (Note is already embedded in each result)
                if self._pending_web_response:
                    user_message += f"\n\n{self._pending_web_response}"
                    self._pending_web_response = ""  # Clear after injecting
            
            # Build messages with proper history (assistant + tool_response pairs)
            messages = [{"role": "system", "content": self.system_prompt}]
            
            if len(history) > 0 and not is_first:
                # Step 1: prepend user task (reinforces objective in context)
                step1_msg = history[0][0]
                messages.append({"role": "assistant", "content": f"<User_Task>\n{task}\n</User_Task>\n\n{step1_msg}"})
                
                if len(history) == 1:
                    # Only one history item - merge its tool_response with current user_message
                    if history[0][1]:
                        user_message = f"{history[0][1]}\n\n{user_message}"
                else:
                    # Multiple history items
                    # Step 1's tool response
                    if history[0][1]:
                        messages.append({"role": "user", "content": history[0][1]})
                    
                    # Middle items (history[1:-1])
                    for assistant_msg, tool_response in history[1:-1]:
                        messages.append({"role": "assistant", "content": assistant_msg})
                        if tool_response:
                            messages.append({"role": "user", "content": tool_response})
                    
                    # Last item - its tool_response combines with current user_message
                    last_assistant, last_tool_response = history[-1]
                    messages.append({"role": "assistant", "content": last_assistant})
                    if last_tool_response:
                        user_message = f"{last_tool_response}\n\n{user_message}"
            
            # Add current user message
            messages.append({"role": "user", "content": user_message})
            
            # Apply prompt caching for OpenRouter (Gemini/Claude need explicit cache_control)
            # Cache everything up to the last message before current user message
            # For Groq and OpenAI, caching is automatic - no changes needed
            if self.provider in ("openrouter", "anthropic") and len(messages) > 2:
                cache_idx = len(messages) - 2
                content = messages[cache_idx]["content"]
                if isinstance(content, str):
                    messages[cache_idx]["content"] = [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ]
            
            try:
                # Call LLM
                raw_response = self.llm.send_request(messages)
                
                # Check stop after LLM
                if self.stop_event and self.stop_event.is_set():
                    break
                
                # Save raw response before any parsing (for debugging)
                self._save_raw_response(raw_response, step_number)
                
                # Validate and normalize response
                success, normalized, failed_raw = CLIAgentResponseFormatter.normalize_response(raw_response)
                
                # If JSON parse failed, discard response and retry with fresh context
                if not success:
                    json_fail_count += 1
                    safe_print(f"⚠️ JSON parse failed ({json_fail_count}/3). Discarding and retrying...")
                    
                    if json_fail_count >= 3:
                        self._push_stream("error", "JSON parsing failed 3 consecutive times. Exiting.")
                        break
                    
                    step_number -= 1
                    continue
                
                # Stream agent blocks to terminal UI (thinking, current_goal, memory)
                try:
                    response_data = json.loads(normalized)
                    if "thinking" in response_data:
                        self._push_stream("thinking", response_data["thinking"])
                    if "current_goal" in response_data:
                        self._push_stream("current_goal", response_data["current_goal"])
                    if "memory" in response_data:
                        self._push_stream("memory", response_data["memory"])
                except:
                    pass
                    json_fail_count += 1
                    safe_print(f"⚠️ JSON parse failed ({json_fail_count}/3). Discarding and retrying...")
                    
                    if json_fail_count >= 3:
                        self._push_stream("error", "JSON parsing failed 3 consecutive times. Exiting.")
                        break
                    
                    step_number -= 1
                    continue
                
                # Reset consecutive JSON fail counter on success
                json_fail_count = 0
                
                # Stream assistant response to terminal UI
                self._push_stream("assistant", normalized)
                
                # Save TRUE agent memory snapshot
                self._save_conversation_snapshot(messages, normalized, step_number)
                
                # Remove thinking from response before adding to history (saves tokens)
                normalized_without_thinking = self._remove_thinking_from_response(normalized)
                
                # Get action block from validated response (view.py is source of truth)
                action_block = CLIAgentResponseFormatter.get_action_block(normalized)
                
                # Check if web tool is in action block - push web_start before execution
                web_query = None
                for action_item in action_block:
                    if isinstance(action_item, dict) and action_item.get("type") == "web":
                        web_query = action_item.get("value")
                        self._push_stream("web_start", web_query)
                        break
                
                # Route actions through controller
                action_result = self.controller.route_action(action_block)
                
                # If web tool was used, push web_end after execution
                if web_query is not None:
                    self._push_stream("web_end", "")
                
                # Check if exit (CLI agent termination)
                if action_result.get("action") == "exit":
                    summary = action_result.get("summary", "Task completed")
                    self._push_stream("exit", summary)
                    
                    # Notify caller (main agent) if callback provided
                    if self.on_complete:
                        self.on_complete({
                            "task": self.task,
                            "summary": summary,
                            "status": "complete"
                        })
                    
                    # Close the terminal window after a brief delay for exit message to display
                    def close_window():
                        time.sleep(2)  # Let user see the exit message
                        if self._webview_window:
                            self._webview_window.destroy()
                    threading.Thread(target=close_window, daemon=True).start()
                    
                    return "Exit"
                
                # Stream terminal actions as PowerShell commands
                self._stream_terminal_action(action_result)
                
                # Extract web tool response if present (before formatting last_response)
                web_tool_response = ""
                web_results_list = []
                if action_result.get("tool") == "web" and "result" in action_result:
                    web_results_list.append(action_result["result"])
                    del action_result["result"]  # Remove from action_result to avoid duplication
                elif action_result.get("action") == "multiple" and "results" in action_result:
                    for idx, result in enumerate(action_result["results"]):
                        if result.get("tool") == "web" and "result" in result:
                            web_results_list.append(result["result"])
                            del action_result["results"][idx]["result"]
                
                # Combine all web results with newlines, wrap in <tool> tag
                if web_results_list:
                    web_tool_response = "<tool>\n" + "\n".join(web_results_list) + "\n</tool>"
                
                # Store web response for next iteration
                self._pending_web_response = web_tool_response
                
                # Format result based on action type
                if action_result.get("action") == "shell":
                    status = action_result.get("status", "success")
                    
                    # Only show status line for timeout or error
                    if status == "timeout" or status == "input_required":
                        status_line = "status: timeout (may need input parameter)\n"
                    elif status == "error":
                        status_line = f"status: error\nerror: {action_result.get('error', '')}\n"
                    else:
                        status_line = ""
                    
                    last_response = f"""<Tool_response>
<shell>
{status_line}cwd: {action_result.get("cwd", "")}
command: {action_result.get("command", "")}
output:
{action_result.get("output", "")}
</shell>
</Tool_response>"""
                
                elif action_result.get("action") == "write":
                    last_response = f"""<Tool_response>
<write>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output: {action_result.get("output", "")}
</write>
</Tool_response>"""
                
                elif action_result.get("action") == "view":
                    last_response = f"""<Tool_response>
<view>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output:
{action_result.get("output", "")}
</view>
</Tool_response>"""
                
                elif action_result.get("action") == "replace":
                    last_response = f"""<Tool_response>
<replace>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output: {action_result.get("output", "")}
</replace>
</Tool_response>"""
                
                elif action_result.get("action") == "multiple":
                    # Format multiple action results with proper newlines
                    formatted_results = []
                    for result in action_result.get("results", []):
                        if result.get("action") == "shell":
                            status = result.get("status", "success")
                            if status == "timeout" or status == "input_required":
                                status_line = "status: timeout (may need input parameter)\n"
                            elif status == "error":
                                status_line = f"status: error\nerror: {result.get('error', '')}\n"
                            else:
                                status_line = ""
                            formatted_results.append(f"""<shell>
{status_line}cwd: {result.get("cwd", "")}
command: {result.get("command", "")}
output:
{result.get("output", "")}
</shell>""")
                        elif result.get("action") == "view":
                            formatted_results.append(f"""<view>
command: {result.get("command", "")}
status: {result.get("status", "")}
output:
{result.get("output", "")}
</view>""")
                        elif result.get("action") == "write":
                            formatted_results.append(f"""<write>
command: {result.get("command", "")}
status: {result.get("status", "")}
output: {result.get("output", "")}
</write>""")
                        elif result.get("action") == "replace":
                            formatted_results.append(f"""<replace>
command: {result.get("command", "")}
status: {result.get("status", "")}
output: {result.get("output", "")}
</replace>""")
                        elif result.get("action") == "todo_updated":
                            formatted_results.append(f"""<todo_updated>
task: {result.get("task", "")}
</todo_updated>""")
                        elif result.get("action") == "milestone_added":
                            formatted_results.append(f"""<milestone_added>
milestone: {result.get("milestone", "")}
</milestone_added>""")
                        else:
                            # For other actions, simple format
                            action_name = result.get("action", "result")
                            formatted_results.append(f"<{action_name}>\nstatus: {result.get('status', 'success')}\n</{action_name}>")
                    
                    last_response = f"<Tool_response>\n" + "\n\n".join(formatted_results) + "\n</Tool_response>"
                
                else:
                    last_response = f"<Tool_response>\n{json.dumps(action_result, indent=2)}\n</Tool_response>"
                
                # Add to history: (assistant_response, tool_response)
                history.append((normalized_without_thinking, last_response))
                
                is_first = False
                
            except Exception as e:
                safe_print(f"Error: {str(e)}")
                debug_log(f"CLI Agent loop error: {str(e)}", "ERROR")
                import traceback
                debug_log(f"CLI Agent traceback: {traceback.format_exc()}", "ERROR")
                break
        
        return "Agent loop ended"
