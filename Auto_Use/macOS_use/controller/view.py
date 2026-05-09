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

import json
import logging
import time
import sys
import os
import shlex
import threading
import subprocess
import uuid
from pathlib import Path

from .service import ControllerService
from .task_tracker.service import TaskTrackerService
from .scratchpad.service import ScratchpadService
from .tool import open_app, ShellService, AppleScriptService
from .key_combo.service import KeyComboService
from .tool.web.service import WebService
from .tool.screenshot import ScreenshotService
from .cli.service import CLIService
try:
    from app import debug_log, IS_COMPILED, app_data_dir
except ImportError:
    IS_COMPILED = False
    def debug_log(message, level="INFO"):
        pass
    def app_data_dir():
        return Path(".")

# Configure logger
logger = logging.getLogger(__name__)


class ControllerView:
    def __init__(self, provider: str = None, model: str = None, cli_mode: bool = False, session_id: str = None, web_callback=None, shell_callback=None, cli_callback=None, api_key: str = None, stop_event=None, external_terminal: bool = False, minion_mode: bool = False):
        """Initialize the Controller View - central router for all actions

        Args:
            provider: LLM provider name for web search
            model: LLM model name for web search
            cli_mode: If True, uses cli_todo folder for parallel isolation
            session_id: Optional unique session ID for isolated folders (cli_mode only)
            web_callback: Optional callback for web search status (start/end)
            shell_callback: Optional callback for shell execution status (start/result/end)
            cli_callback: Optional callback for CLI agent streaming (await_start/task_start/task_line/task_end/await_end)
            api_key: Optional runtime API key for LLM providers (passed to CLI agent)
            stop_event: Optional threading.Event for stopping actions mid-execution
            external_terminal: If True, dispatched CLI sub-agents are launched in their own visible OS terminal window (Terminal.app on macOS) instead of having their stdout/stderr piped back. Used by main.py headless mode so the user can watch sub-agent progress live.
            minion_mode: If True, this ControllerView belongs to a minion sub-agent run.
                The scratchpad redirects to scratchpad/cli_minion/{session_id}/ so
                the parent CLI agent's cli_milestone/ stays untouched.
        """
        self.cli_mode = cli_mode
        self.session_id = session_id
        self.api_key = api_key
        self.stop_event = stop_event
        self.external_terminal = external_terminal
        self.minion_mode = minion_mode
        self.controller_service = ControllerService(stop_event=stop_event)
        self.task_tracker = TaskTrackerService(cli_mode=cli_mode, session_id=session_id)
        self.scratchpad_service = ScratchpadService(cli_mode=cli_mode, session_id=session_id, minion_mode=minion_mode)
        self.key_combo_service = KeyComboService(stop_event=stop_event)
        self.cli_service = CLIService(session_id=session_id) if cli_mode else None
        self.shell_service = ShellService()
        self.applescript_service = AppleScriptService()
        self.screenshot_service = ScreenshotService(self.controller_service, sandbox_workspace=str(self.shell_service.sandbox.sandbox_root))
        self.provider = provider
        self.model = model
        self.web_callback = web_callback
        self.shell_callback = shell_callback
        self.cli_callback = cli_callback
        self._stop_loading = False

        # CLI Agent tracking - multi-task support
        self._cli_tasks = []          # Active: [{"task": str, "subprocess": Popen, "result_file": Path}]
        self._cli_completed = []      # Done: [{"task": str, "summary": str, "status": str}]
        self._cli_agent_lock = threading.Lock()
        self._cli_await_active = False  # Whether an await_start has been emitted but not yet matched by await_end

        # Minion tracking — parallel to CLI agent but with implicit-blocking semantics:
        # the action loop dispatches all minions, then blocks at the end until every
        # spawned minion has written its result. Reuses _cli_agent_lock for thread safety.
        self._minion_tasks = []       # Active: [{"query": str, "subprocess": Popen, "result_file": Path, "session_id": str}]
        self._minion_completed = []   # Done: [{"query": str, "session_id": str, "summary": str, "status": str}]
    
    def _web_loading_animation(self):
        """Display animated loading indicator for web search.

        Skipped when stdout is NOT a TTY (i.e. piped subprocess) — the `\r`
        carriage-return overwrite trick only works in a real terminal; in a pipe
        all the partial writes accumulate and stream into the parent's reader as
        ugly text like "🌐 Web 🌐 Web. 🌐 Web..." which then floods the pill.
        In pipe mode the UI gets a clean web-loading visual via the
        web_loading_start/end events emitted from the web action handler.
        """
        if not sys.stdout.isatty():
            return
        dots = ["", ".", "..", "..."]
        idx = 0
        while not self._stop_loading:
            sys.stdout.write(f"\r🌐 Web{dots[idx % len(dots)]}   ")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.5)
    
    def _safe_cli_emit(self, event_type: str, *args):
        """Invoke self.cli_callback safely; never let a callback exception bubble up.

        Subprocess fallback: when there's no direct callback (CLI agent running as
        a piped subprocess of the main agent in app.py UI mode) and stdout is NOT
        a TTY, emit the event as a tagged JSON marker on stdout. The main agent's
        reader thread picks the marker up and re-emits it through ITS callback so
        UI events from the CLI subprocess (like minion lifecycle) reach the pill.
        Skipped in cli.py terminal mode (stdout is a TTY) — keeps the user's
        terminal output clean of internal protocol lines.
        """
        if self.cli_callback:
            try:
                self.cli_callback(event_type, *args)
            except Exception as e:
                logger.error(f"cli_callback({event_type}) failed: {e}")
            return
        if self.cli_mode and not sys.stdout.isatty():
            try:
                payload = json.dumps({"event": event_type, "args": list(args)}, ensure_ascii=False)
                sys.stdout.write(f"__MINION_UI_EVENT__:{payload}\n")
                sys.stdout.flush()
            except Exception:
                pass

    def _spawn_cli_external_terminal(self, cli_cmd: list, task_description: str):
        """Spawn the CLI sub-agent in a new visible Terminal.app window on macOS.

        Uses osascript to open Terminal.app and run the same `cli_cmd` the
        piped path would run. The user sees the sub-agent's live output in
        its own window. Completion is still detected via the result-file
        watcher, so we don't need a Popen handle here. Returns None.
        """
        repo_root = os.getcwd()
        inner = " ".join(shlex.quote(arg) for arg in cli_cmd)
        shell_line = f"cd {shlex.quote(repo_root)} && {inner}"
        # Escape for the AppleScript string literal: backslashes then double-quotes.
        escaped = shell_line.replace("\\", "\\\\").replace('"', '\\"')
        title = task_description[:60].replace('"', "'")
        apple_script = (
            f'tell application "Terminal"\n'
            f'  activate\n'
            f'  do script "{escaped}"\n'
            f'  set custom title of front window to "CLI Agent: {title}"\n'
            f'end tell'
        )
        try:
            subprocess.Popen(["osascript", "-e", apple_script])
            debug_log(f"CLI sub-agent launched in external Terminal.app window: {task_description[:80]}")
        except Exception as e:
            debug_log(f"Failed to spawn external Terminal for CLI sub-agent: {e}", "ERROR")
        return None

    def _read_cli_stream(self, pipe, task_id: str, stream: str):
        """Reader thread: forwards each line from a subprocess pipe to the frontend.

        Loops until the pipe closes (subprocess exit). Each line emits a 'task_line'
        event tagged with task_id and stream ("out" or "err").

        Marker lines (`__MINION_UI_EVENT__:<json>`) are intercepted: they're internal
        protocol from a piped CLI subprocess forwarding minion lifecycle. Re-emit
        them as proper `minion_start` / `minion_end` events through this controller's
        own callback (which has the bridge to the frontend). Marker lines never
        leak into the parent pill's streaming output.
        """
        if pipe is None:
            logger.warning(f"_read_cli_stream({task_id}, {stream}): pipe is None")
            return
        logger.info(f"_read_cli_stream alive ({task_id}, {stream})")
        line_count = 0
        try:
            for raw in iter(pipe.readline, b""):
                if not raw:
                    break
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    line = str(raw)
                if line == "" and stream == "err":
                    # don't spam empty stderr lines
                    continue
                if line.startswith("__MINION_UI_EVENT__:"):
                    self._handle_minion_marker(line, parent_task_id=task_id)
                    continue
                line_count += 1
                if line_count <= 3 or line_count % 50 == 0:
                    logger.info(f"_read_cli_stream({task_id}, {stream}) line #{line_count}: {line[:120]}")
                self._safe_cli_emit("task_line", task_id, line, stream)
        except Exception as e:
            logger.error(f"_read_cli_stream({task_id}, {stream}) error: {e}")
        finally:
            logger.info(f"_read_cli_stream done ({task_id}, {stream}, total={line_count} lines)")
            try:
                pipe.close()
            except Exception:
                pass

    def _handle_minion_marker(self, line: str, parent_task_id: str):
        """Parse a `__MINION_UI_EVENT__:<json>` marker line emitted by a piped CLI
        subprocess and re-emit it through this controller's own callback as a
        proper `minion_start` / `minion_end` event.

        `parent_task_id` is the spawning CLI subprocess's task_id (the result-file
        stem from the cli_agent dispatch) — used so the frontend can attach the
        new minion pill below the correct parent pill.
        """
        try:
            payload = json.loads(line[len("__MINION_UI_EVENT__:"):].strip())
        except Exception as e:
            logger.error(f"Failed to parse minion marker: {e} | line={line!r}")
            return
        inner_event = payload.get("event")
        inner_args = payload.get("args", [])
        if inner_event == "task_start":
            minion_task_id = inner_args[0] if len(inner_args) > 0 else ""
            minion_desc = inner_args[1] if len(inner_args) > 1 else ""
            if isinstance(minion_desc, str) and minion_desc.startswith("[minion] "):
                minion_desc = minion_desc[len("[minion] "):]
            self._safe_cli_emit("minion_start", parent_task_id, minion_task_id, minion_desc)
        elif inner_event == "task_end":
            minion_task_id = inner_args[0] if len(inner_args) > 0 else ""
            status = inner_args[1] if len(inner_args) > 1 else "complete"
            summary = inner_args[2] if len(inner_args) > 2 else ""
            self._safe_cli_emit("minion_end", minion_task_id, status, summary)
        elif inner_event == "task_line":
            # Minion's stdout/stderr lines — stream into the minion pill body so
            # the user sees live progress (mirrors how parent CLI pills stream).
            minion_task_id = inner_args[0] if len(inner_args) > 0 else ""
            line_text = inner_args[1] if len(inner_args) > 1 else ""
            line_stream = inner_args[2] if len(inner_args) > 2 else "out"
            self._safe_cli_emit("minion_line", minion_task_id, line_text, line_stream)
        elif inner_event == "web_loading_start":
            # Web tool started inside the piped CLI subprocess — flip the parent
            # CLI pill into web-loading visual state. parent_task_id IS the pill.
            self._safe_cli_emit("pill_web_loading_start", parent_task_id)
        elif inner_event == "web_loading_end":
            self._safe_cli_emit("pill_web_loading_end", parent_task_id)

    def _cli_agent_complete_callback(self, result: dict, result_file: Path):
        """Callback when CLI agent finishes execution"""
        task_id = result_file.stem
        with self._cli_agent_lock:
            # Move from active to completed
            self._cli_tasks = [t for t in self._cli_tasks if t["result_file"] != result_file]
            self._cli_completed.append({
                "task": result.get("task", "Unknown task"),
                "summary": result.get("summary", "Completed"),
                "status": result.get("status", "complete")
            })
            logger.info(f"CLI Agent completed: {result.get('summary', 'No summary')}")

        # Notify frontend that this task ended (before scratchpad write, so the pill flips first)
        self._safe_cli_emit("task_end", task_id, result.get("status", "complete"), result.get("summary", ""))

    def _minion_complete_callback(self, result: dict, result_file: Path, query: str, session_id: str):
        """Callback when a minion subprocess writes its result file.

        Unlike CLI agents, minion summaries do NOT auto-append to the parent's scratchpad —
        the structured exit summary is the entire deliverable and surfaces directly as a
        <minion_completed> tool response on the parent's next iteration.
        """
        task_id = result_file.stem
        with self._cli_agent_lock:
            self._minion_tasks = [t for t in self._minion_tasks if t["result_file"] != result_file]
            self._minion_completed.append({
                "query": query,
                "session_id": session_id,
                "summary": result.get("summary", ""),
                "status": result.get("status", "complete"),
            })
            logger.info(f"Minion completed (session {session_id}): {result.get('status', 'complete')}")

        self._safe_cli_emit("task_end", task_id, result.get("status", "complete"), result.get("summary", ""))

        # Update scratchpad with completion status
        cli_task = result.get("task", "Unknown task")
        cli_summary = result.get("summary", "Completed")
        self.scratchpad_service.append_scratchpad(f"CLI Agent finished, task: {cli_task}, status: complete, summary: {cli_summary}")
    
    def get_cli_agent_status(self) -> dict:
        """Get current CLI agent status for main agent to check"""
        with self._cli_agent_lock:
            return {
                "pending": len(self._cli_tasks) > 0,
                "pending_count": len(self._cli_tasks),
                "completed": list(self._cli_completed)
            }
    
    def clear_cli_agent_results(self):
        """Clear all CLI agent results after main agent has consumed them"""
        with self._cli_agent_lock:
            self._cli_completed.clear()
    
    def stop_cli_agent(self):
        """Terminate all CLI agent subprocesses if running"""
        terminated_ids = []
        with self._cli_agent_lock:
            for task_entry in self._cli_tasks:
                proc = task_entry.get("subprocess")
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        logger.info(f"CLI Agent subprocess terminated: {task_entry.get('task', 'unknown')}")
                    except Exception as e:
                        logger.error(f"Error terminating CLI subprocess: {e}")
                rf = task_entry.get("result_file")
                if rf is not None:
                    terminated_ids.append(rf.stem)
            self._cli_tasks.clear()
            self._cli_completed.clear()

        # Notify frontend that any pills for these tasks are done (stopped)
        for task_id in terminated_ids:
            self._safe_cli_emit("task_end", task_id, "stopped", "Stopped by user")
        if self._cli_await_active:
            self._safe_cli_emit("await_end")
            self._cli_await_active = False
        
    def route_action(self, action_data):
        """
        Route actions to appropriate service based on action type
        
        Supports two formats:
        - New flat format (main agent): [{"type": "click", "id": 8}, {"type": "wait", "value": "2"}, ...]
        - Old nested format (CLI agent): [{"shell": {"command": "..."}}, {"click": 8}, ...]
        
        Args:
            action_data (list): The action list from LLM response
            
        Returns:
            dict: Result of the action execution
        """
        try:
            results = []
            
            for action_item in action_data:
                # Check stop before every action
                if self.stop_event and self.stop_event.is_set():
                    self.controller_service.release_all_inputs()
                    return {"status": "stopped", "action": "stop", "message": "Stopped by user"}
                
                # Detect format: new flat format has "type" key, old nested format doesn't
                if "type" in action_item:
                    # New flat format: {"type": "action_type", "id": ..., "value": ..., "text": ..., etc.}
                    action_type = action_item.get("type")
                else:
                    # Old nested format: {"action_key": action_value}
                    # Extract the action key and route to legacy handler
                    result = self._route_legacy_action(action_item)
                    if result:
                        results.append(result)
                        if result.get("status") == "stopped":
                            self.controller_service.release_all_inputs()
                            return result
                        if result.get("status") == "error":
                            return result
                    continue
                
                if not action_type:
                    logger.warning(f"Action item missing 'type' field: {action_item}")
                    continue
                
                if action_type == "left_click":
                    element_id = action_item.get("id")
                    clicks = action_item.get("clicks", 1)
                    if clicks == 3:
                        result = self.controller_service.triple_click(element_id)
                    elif clicks == 2:
                        result = self.controller_service.double_click(element_id)
                    else:
                        result = self.controller_service.click(element_id)
                    results.append(result)
                    if result.get("status") == "error":
                        return result
                
                elif action_type == "input":
                    element_id = action_item.get("id")
                    text_value = action_item.get("value")
                    result = self.controller_service.input(element_id, text_value)
                    results.append(result)
                    if result.get("status") == "error":
                        return {
                            "status": "error",
                            "action": "input",
                            "results": results,
                            "message": f"Input insertion in element {element_id} failed"
                        }
                
                elif action_type == "scroll":
                    element_id = action_item.get("id")
                    direction = action_item.get("direction")
                    result = self.controller_service.scroll(element_id, direction)
                    results.append(result)
                    if result.get("status") == "error":
                        return {
                            "status": "error",
                            "action": "scroll",
                            "results": results,
                            "message": f"Scroll on element {element_id} failed"
                        }
                
                elif action_type == "canvas_input":
                    text_value = action_item.get("value")
                    result = self.controller_service.canvas_input(text_value)
                    results.append(result)
                    if result.get("status") == "error":
                        return result
                        
                        
                elif action_type == "right_click":
                    element_id = action_item.get("id")
                    result = self.controller_service.right_click(element_id)
                    results.append(result)
                    if result.get("status") == "error":
                        return result

                elif action_type == "shortcut_combo":
                    combo_value = action_item.get("value")
                    result = self.key_combo_service.send(combo_value)
                    results.append(result)
                    if result.get("status") == "error":
                        return result
                        
                elif action_type == "screenshot":
                    element_id = str(action_item.get("id"))
                    logger.info(f"Taking screenshot of element: {element_id}")
                    
                    if element_id not in self.controller_service.elements_mapping:
                        return {
                            "status": "error",
                            "action": "screenshot",
                            "index": element_id,
                            "message": f"Element index {element_id} not found"
                        }
                    
                    element_info = self.controller_service.elements_mapping[element_id]
                    rect = element_info.get('visible_rect') or element_info['rect']
                    
                    result = self.screenshot_service.capture_element(rect, element_id)
                    result["index"] = element_id
                    results.append(result)
                    if result.get("status") == "error":
                        return result

                elif action_type == "drag_drop":
                    raw_value = action_item.get("value", "")
                    parts = raw_value.split(" to ")
                    if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                        return {
                            "status": "error",
                            "action": "drag_drop",
                            "message": f"Invalid drag_drop format: '{raw_value}'. Expected: '<from_id> to <to_id>' (e.g. '8 to 15')"
                        }
                    from_id = parts[0].strip()
                    to_id = parts[1].strip()
                    result = self.controller_service.drag_drop(from_id, to_id)
                    results.append(result)
                    if result.get("status") == "error":
                        return result

                elif action_type == "open_app":
                    app_name = action_item.get("value")
                    logger.info(f"Opening application: {app_name}")
                    
                    success = open_app(app_name)
                    
                    if success:
                        logger.info(f"Successfully opened {app_name}")
                        result = {"status": "success", "action": "tool", "tool": "open_app", "app": app_name}
                        results.append(result)
                    else:
                        logger.error(f"Failed to open {app_name}")
                        return {
                            "status": "error",
                            "action": "tool",
                            "tool": "open_app",
                            "app": app_name,
                            "message": "No application found. Verify by typing the application name in the taskbar search. If still not visible then download it or find an alternative."
                        }
                
                elif action_type == "wait":
                    wait_time = float(action_item.get("value", "1"))
                    logger.info(f"Waiting for {wait_time} seconds...")
                    elapsed = 0.0
                    while elapsed < wait_time:
                        if self.stop_event and self.stop_event.is_set():
                            self.controller_service.release_all_inputs()
                            return {"status": "stopped", "action": "stop", "message": "Stopped by user"}
                        time.sleep(min(0.5, wait_time - elapsed))
                        elapsed += 0.5
                    logger.info(f"Wait completed")
                    result = {"status": "success", "action": "tool", "tool": "wait", "duration": wait_time}
                    results.append(result)
                        
                elif action_type == "web":
                    query = action_item.get("value")
                    logger.info(f"Performing web search: {query}")

                    if self.web_callback:
                        self.web_callback("start")
                    # In CLI subprocess (no web_callback), this fires the marker bridge
                    # so the parent CLI pill flips into web-loading visual on the frontend.
                    self._safe_cli_emit("web_loading_start")

                    self._stop_loading = False
                    loading_thread = threading.Thread(target=self._web_loading_animation)
                    loading_thread.daemon = True
                    loading_thread.start()

                    try:
                        web_service = WebService(self.provider, self.model, self.api_key)
                        web_result = web_service.search(query)
                    finally:
                        self._stop_loading = True
                        loading_thread.join(timeout=1)
                        # Clear the in-place text only in TTY mode — in piped subprocess
                        # this would just dump 50 spaces + carriage returns into the
                        # parent's reader buffer.
                        if sys.stdout.isatty():
                            sys.stdout.write("\r" + " " * 50 + "\r")
                            sys.stdout.flush()

                        if self.web_callback:
                            self.web_callback("end")
                            # Wait for CSS fade-out to complete before next action
                            time.sleep(0.7)
                        self._safe_cli_emit("web_loading_end")

                    result = {
                        "status": "success",
                        "action": "tool",
                        "tool": "web",
                        "query": query,
                        "result": web_result
                    }
                    results.append(result)

                elif action_type == "cli_await":
                    # AWAIT MODE: freeze pipeline until all CLI tasks complete
                    reason = action_item.get("value", "")
                    logger.info(f"CLI Agent await triggered: {reason}")

                    # Notify frontend only if there's actual work in flight,
                    # so an empty cli_await doesn't flash the streaming UI.
                    with self._cli_agent_lock:
                        had_pending = len(self._cli_tasks) > 0
                    if had_pending:
                        self._cli_await_active = True
                        self._safe_cli_emit("await_start", reason)

                    # Block until all pending CLI tasks finish
                    while True:
                        if self.stop_event and self.stop_event.is_set():
                            self.stop_cli_agent()
                            self.controller_service.release_all_inputs()
                            return {"status": "stopped", "action": "stop", "message": "Stopped by user"}
                        with self._cli_agent_lock:
                            if len(self._cli_tasks) == 0:
                                break
                        time.sleep(1)

                    # Collect all completed results
                    with self._cli_agent_lock:
                        completed = list(self._cli_completed)

                    logger.info(f"CLI Agent await complete: {len(completed)} tasks finished")

                    if self._cli_await_active:
                        self._safe_cli_emit("await_end")
                        self._cli_await_active = False

                    result = {
                        "status": "success",
                        "action": "cli_await",
                        "reason": reason,
                        "completed": completed
                    }
                    results.append(result)

                elif action_type == "cli_agent":
                    # DISPATCH MODE: spawn CLI agent
                    task_description = action_item.get("value", "")
                    logger.info(f"Starting CLI Agent for task: {task_description}")
                    
                    result_file = app_data_dir() / "cli_agent_result" / f"result_{int(time.time() * 1000)}.json"
                    result_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Build CLI command based on compiled vs dev mode
                    if IS_COMPILED:
                        exe_dir = os.path.dirname(sys.executable)
                        # sys.executable points to embedded 'python' runtime,
                        # not the actual compiled binary. Use 'AutoUse' on macOS,
                        # 'AutoUse.exe' on Windows.
                        if sys.platform == "darwin":
                            main_exe = os.path.join(exe_dir, "AutoUse")
                        else:
                            main_exe = os.path.join(exe_dir, "AutoUse.exe")
                        cli_cmd = [
                            main_exe, "--cli-mode",
                            "--task", task_description,
                            "--provider", self.provider or "openrouter",
                            "--model", self.model or "gemini-3-flash",
                            "--result", str(result_file)
                        ]
                    else:
                        cli_cmd = [
                            sys.executable, "-m", "Auto_Use.macOS_use.agent.cli",
                            "--task", task_description,
                            "--provider", self.provider or "openrouter",
                            "--model", self.model or "gemini-3-flash",
                            "--result", str(result_file)
                        ]
                    
                    if self.api_key:
                        cli_cmd.extend(["--api_key", self.api_key])

                    # Propagate external_terminal to the CLI subprocess. In app.py UI mode
                    # main agent has external_terminal=False; pass --no_external_terminal so
                    # the spawned CLI keeps its own minions on PIPE (required for the
                    # __MINION_UI_EVENT__ marker bridge to reach the frontend).
                    if not self.external_terminal:
                        cli_cmd.append("--no_external_terminal")

                    cli_env = os.environ.copy()
                    cli_env["PYTHONUNBUFFERED"] = "1"
                    cli_proc = None

                    if self.external_terminal:
                        # Headless main.py mode: open Terminal.app so the user
                        # can watch the sub-agent live. Completion still flows
                        # through the result-file watcher below.
                        self._spawn_cli_external_terminal(cli_cmd, task_description)
                    else:
                        # Start subprocess. Force unbuffered stdout/stderr in the
                        # child so our reader thread sees lines as they're printed
                        # — without this, Python block-buffers when not connected
                        # to a TTY and the streaming UI feels frozen.
                        try:
                            cli_proc = subprocess.Popen(
                                cli_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                env=cli_env
                            )
                            debug_log(f"CLI subprocess started (PID: {cli_proc.pid})")
                        except Exception as e:
                            debug_log(f"CLI subprocess failed to start: {e}", "ERROR")

                    # Track in active list
                    task_id = result_file.stem
                    with self._cli_agent_lock:
                        self._cli_tasks.append({
                            "task": task_description,
                            "subprocess": cli_proc,
                            "result_file": result_file
                        })

                    # Notify frontend a new task has started, then begin
                    # streaming its stdout/stderr line-by-line.
                    self._safe_cli_emit("task_start", task_id, task_description)
                    if cli_proc is not None:
                        for pipe, stream_name in (
                            (cli_proc.stdout, "out"),
                            (cli_proc.stderr, "err"),
                        ):
                            t = threading.Thread(
                                target=self._read_cli_stream,
                                args=(pipe, task_id, stream_name),
                                daemon=True,
                            )
                            t.start()
                    
                    # Watcher thread (bind result_file via default arg to avoid closure issue)
                    def watch_cli_result(rf=result_file):
                        while True:
                            if rf.exists():
                                try:
                                    with open(rf, 'r', encoding='utf-8') as f:
                                        result_data = json.load(f)
                                    rf.unlink()
                                    self._cli_agent_complete_callback(result_data, rf)
                                except Exception as e:
                                    logger.error(f"Error reading CLI agent result: {e}")
                                break
                            time.sleep(2)
                    
                    watcher_thread = threading.Thread(target=watch_cli_result)
                    watcher_thread.daemon = True
                    watcher_thread.start()
                    
                    self.scratchpad_service.append_scratchpad(f"CLI Agent started, task: {task_description}, status: pending")

                    result = {
                        "status": "success",
                        "action": "tool",
                        "tool": "cli_task",
                        "task": task_description,
                        "message": "CLI Agent started in parallel. Continue with other tasks."
                    }
                    results.append(result)

                elif action_type == "minion":
                    # DISPATCH MODE: spawn a read-only minion sub-agent.
                    # Multiple minions in one action_list spawn in parallel; the
                    # implicit-await block at the end of this action loop blocks
                    # until ALL spawned minions have written their result file.
                    minion_query = action_item.get("value", "")
                    logger.info(f"Starting Minion for query: {minion_query}")

                    result_file = app_data_dir() / "cli_minion_result" / f"result_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.json"
                    result_file.parent.mkdir(parents=True, exist_ok=True)
                    minion_session_id = uuid.uuid4().hex[:8]

                    if IS_COMPILED:
                        exe_dir = os.path.dirname(sys.executable)
                        if sys.platform == "darwin":
                            main_exe = os.path.join(exe_dir, "AutoUse")
                        else:
                            main_exe = os.path.join(exe_dir, "AutoUse.exe")
                        cli_cmd = [
                            main_exe, "--minion-mode",
                            "--task", minion_query,
                            "--provider", self.provider or "openrouter",
                            "--model", self.model or "gemini-3-flash",
                            "--result", str(result_file),
                        ]
                    else:
                        cli_cmd = [
                            sys.executable, "-m", "Auto_Use.macOS_use.agent.cli.minions",
                            "--task", minion_query,
                            "--provider", self.provider or "openrouter",
                            "--model", self.model or "gemini-3-flash",
                            "--result", str(result_file),
                        ]

                    if self.api_key:
                        cli_cmd.extend(["--api_key", self.api_key])

                    cli_env = os.environ.copy()
                    cli_env["PYTHONUNBUFFERED"] = "1"
                    minion_proc = None

                    if self.external_terminal:
                        self._spawn_cli_external_terminal(cli_cmd, f"[minion] {minion_query}")
                    else:
                        try:
                            minion_proc = subprocess.Popen(
                                cli_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                env=cli_env,
                            )
                            debug_log(f"Minion subprocess started (PID: {minion_proc.pid})")
                        except Exception as e:
                            debug_log(f"Minion subprocess failed to start: {e}", "ERROR")

                    task_id = result_file.stem
                    with self._cli_agent_lock:
                        self._minion_tasks.append({
                            "query": minion_query,
                            "subprocess": minion_proc,
                            "result_file": result_file,
                            "session_id": minion_session_id,
                        })

                    self._safe_cli_emit("task_start", task_id, f"[minion] {minion_query}")
                    if minion_proc is not None:
                        for pipe, stream_name in (
                            (minion_proc.stdout, "out"),
                            (minion_proc.stderr, "err"),
                        ):
                            t = threading.Thread(
                                target=self._read_cli_stream,
                                args=(pipe, task_id, stream_name),
                                daemon=True,
                            )
                            t.start()

                    def watch_minion_result(rf=result_file, q=minion_query, sid=minion_session_id):
                        while True:
                            if rf.exists():
                                try:
                                    with open(rf, 'r', encoding='utf-8') as f:
                                        result_data = json.load(f)
                                    rf.unlink()
                                    self._minion_complete_callback(result_data, rf, q, sid)
                                except Exception as e:
                                    logger.error(f"Error reading minion result: {e}")
                                break
                            time.sleep(1)

                    watcher_thread = threading.Thread(target=watch_minion_result)
                    watcher_thread.daemon = True
                    watcher_thread.start()

                    # Placeholder — patched after the implicit-await at end of action loop.
                    results.append({
                        "_pending_minion": True,
                        "query": minion_query,
                        "session_id": minion_session_id,
                    })

                elif action_type == "todo_list":
                    todo_value = action_item.get("value")
                    self.task_tracker.save_todo(todo_value)
                    result = {"status": "success", "action": "todo_created"}
                    results.append(result)
                
                elif action_type == "update_todo":
                    task_number = int(action_item.get("value", "0"))
                    success = self.task_tracker.update_task(task_number)
                    if success:
                        result = {"status": "success", "action": "todo_updated", "task": task_number}
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "todo_update_failed",
                            "message": "Could not update task"
                        }
                
                elif action_type == "scratchpad":
                    scratchpad_value = action_item.get("value")
                    success = self.scratchpad_service.append_scratchpad(scratchpad_value)
                    if success:
                        result = {"status": "success", "action": "scratchpad_added", "scratchpad": scratchpad_value}
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "scratchpad_failed",
                            "message": "Could not add scratchpad entry"
                        }
                        
                elif action_type == "applescript":
                    app_name = action_item.get("app", "")
                    script_value = action_item.get("value", "")
                    logger.info(f"Executing AppleScript on {app_name}: {script_value[:80]}")

                    # Signal frontend: terminal card appears with "AppleScript" label
                    if self.shell_callback:
                        display_cmd = f"{app_name}: {script_value[:80]}" if app_name else script_value[:80]
                        self.shell_callback("start", display_cmd, "AppleScript")

                    result = self.applescript_service.execute(app_name, script_value)

                    # Signal frontend: show success/fail result
                    if self.shell_callback:
                        as_status = result.get("status", "error")
                        as_output = result.get("output", result.get("message", ""))
                        self.shell_callback("result", {"status": as_status, "output": as_output or ""})
                        time.sleep(2)
                        self.shell_callback("end")
                        time.sleep(0.7)

                    results.append(result)
                    if result.get("status") == "error":
                        return result

                elif action_type == "done":
                    summary = action_item.get("value")
                    
                    # Block if any CLI agents are still pending
                    with self._cli_agent_lock:
                        if len(self._cli_tasks) > 0:
                            logger.info(f"Done requested but {len(self._cli_tasks)} CLI Agent(s) still pending. Waiting...")
                    
                    # Wait for all CLI agents to complete (blocking)
                    while True:
                        if self.stop_event and self.stop_event.is_set():
                            self.stop_cli_agent()
                            self.controller_service.release_all_inputs()
                            return {"status": "stopped", "action": "stop", "message": "Stopped by user"}
                        with self._cli_agent_lock:
                            if len(self._cli_tasks) == 0:
                                break
                        time.sleep(1)
                    
                    logger.info(f"Task Complete: {summary}")
                    return {"status": "success", "action": "done", "summary": summary}

                # Shell command execution (new flat format)
                elif action_type == "shell":
                    if self.cli_service:
                        # CLI agent mode — command + input fields
                        command = action_item.get("command", "")
                        input_text = action_item.get("input", None)
                        result = self.cli_service.shell(command, input_text)
                    else:
                        # Main agent mode — value field only, with frontend animation
                        command = action_item.get("value", "")
                        
                        # Signal frontend: terminal card appears, screenshot slides down
                        if self.shell_callback:
                            self.shell_callback("start", command)
                        
                        result = self.shell_service.run(command)
                        
                        # Signal frontend: show success/fail result
                        if self.shell_callback:
                            shell_status = result.get("status", "failed")
                            shell_output = result.get("output", result.get("error", ""))
                            self.shell_callback("result", {"status": shell_status, "output": shell_output or ""})
                            # Hold result on screen for 2 seconds
                            time.sleep(2)
                            # Signal frontend: terminal card fades out, screenshot slides up
                            self.shell_callback("end")
                            # Wait for CSS fade-out to complete before next action
                            time.sleep(0.7)
                        
                    results.append(result)
                    if result.get("status") == "error" and result.get("error"):
                        return result
                
                elif action_type == "view":
                    if self.cli_service:
                        result = self.cli_service.view(
                            path=action_item.get("path", ""),
                            start=action_item.get("start", 0),
                            end=action_item.get("end", 0),
                        )
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "view",
                            "message": "CLI service not initialized (cli_mode=False)"
                        }

                elif action_type == "grep":
                    if self.cli_service:
                        result = self.cli_service.grep(
                            pattern=action_item.get("pattern", ""),
                            path=action_item.get("path", ""),
                            glob_filter=action_item.get("glob", ""),
                            output_mode=action_item.get("output_mode", "content"),
                            case_insensitive=action_item.get("case_insensitive", False),
                            head_limit=action_item.get("head_limit", 50),
                            context=action_item.get("context", 0),
                        )
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "grep",
                            "message": "CLI service not initialized (cli_mode=False)"
                        }

                elif action_type == "glob":
                    if self.cli_service:
                        result = self.cli_service.glob(
                            pattern=action_item.get("pattern", ""),
                            path=action_item.get("path", ""),
                            head_limit=action_item.get("head_limit", 100),
                        )
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "glob",
                            "message": "CLI service not initialized (cli_mode=False)"
                        }

                elif action_type == "write":
                    if self.cli_service:
                        path = action_item.get("path", "")
                        line = action_item.get("line", 1)
                        content = action_item.get("content", "")
                        result = self.cli_service.write(path, line, content)
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "write",
                            "message": "CLI service not initialized (cli_mode=False)"
                        }
                
                elif action_type == "replace":
                    if self.cli_service:
                        path = action_item.get("path", "")
                        line = action_item.get("line", 0)
                        old_block = action_item.get("old_block", "")
                        new_block = action_item.get("new_block", "")
                        result = self.cli_service.replace(path, line, old_block, new_block)
                        results.append(result)
                    else:
                        return {
                            "status": "error",
                            "action": "replace",
                            "message": "CLI service not initialized (cli_mode=False)"
                        }
                
                elif action_type == "exit":
                    summary = action_item.get("value")
                    logger.info(f"CLI Agent Exit: {summary}")
                    return {"status": "success", "action": "exit", "summary": summary}

                # Check if last action was stopped
                if results and results[-1].get("status") == "stopped":
                    self.controller_service.release_all_inputs()
                    return results[-1]

            # Implicit await: if any minions were dispatched in this action, block
            # until all of them have written their result files, then patch each
            # placeholder in `results` with the structured tool response. Single
            # minion → wait for that one. N minions → wait for all N (parallel).
            with self._cli_agent_lock:
                pending_minion_count = len(self._minion_tasks)
            if pending_minion_count > 0:
                while True:
                    if self.stop_event is not None and self.stop_event.is_set():
                        with self._cli_agent_lock:
                            for t in self._minion_tasks:
                                proc = t.get("subprocess")
                                if proc and proc.poll() is None:
                                    try:
                                        proc.terminate()
                                    except Exception:
                                        pass
                            self._minion_tasks.clear()
                        break
                    with self._cli_agent_lock:
                        if not self._minion_tasks:
                            break
                    time.sleep(0.5)

                with self._cli_agent_lock:
                    completed_by_sid = {c["session_id"]: c for c in self._minion_completed}
                for i, r in enumerate(results):
                    if isinstance(r, dict) and r.get("_pending_minion"):
                        sid = r.get("session_id")
                        completion = completed_by_sid.get(sid)
                        if completion is None:
                            results[i] = {
                                "status": "error",
                                "action": "minion_completed",
                                "query": r.get("query", ""),
                                "output": "Minion did not return a result (subprocess crashed or was terminated).",
                            }
                        else:
                            results[i] = {
                                "status": "success" if completion.get("status") == "complete" else "error",
                                "action": "minion_completed",
                                "query": r.get("query", ""),
                                "output": completion.get("summary", ""),
                            }
                with self._cli_agent_lock:
                    self._minion_completed = [c for c in self._minion_completed
                                              if c["session_id"] not in completed_by_sid]

            if len(results) == 0:
                return {"status": "error", "message": "No valid action found"}
            elif len(results) == 1:
                return results[0]
            else:
                return {"status": "success", "action": "multiple", "results": results}
                
        except Exception as e:
            logger.error(f"Error routing action: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _route_legacy_action(self, action_item):
        """
        Handle old nested action format used by CLI agent
        Format: {"action_key": action_value}
        
        Args:
            action_item (dict): Single action in old nested format
            
        Returns:
            dict: Result of the action execution, or None if not handled
        """
        for action_key, action_value in action_item.items():
            
            if action_key == "click":
                return self.controller_service.click(action_value)
            
            elif action_key == "input":
                if isinstance(action_value, dict):
                    element_idx = action_value.get("id")
                    text_value = action_value.get("value")
                    return self.controller_service.input(element_idx, text_value)
            
            elif action_key == "scroll":
                if isinstance(action_value, dict):
                    element_idx = action_value.get("id")
                    direction = action_value.get("direction")
                    return self.controller_service.scroll(element_idx, direction)
            
            elif action_key == "canvas_input":
                return self.controller_service.canvas_input(action_value)
                    
            elif action_key == "double_click":
                return self.controller_service.double_click(action_value)
                    
            elif action_key == "right_click":
                return self.controller_service.right_click(action_value)

            elif action_key == "shortcut_combo":
                return self.key_combo_service.send(action_value)
            
            elif action_key == "wait":
                wait_time = float(action_value)
                logger.info(f"Waiting for {wait_time} seconds...")
                time.sleep(wait_time)
                logger.info(f"Wait completed")
                return {"status": "success", "action": "tool", "tool": "wait", "duration": wait_time}
            
            elif action_key == "shell":
                if self.cli_service:
                    if isinstance(action_value, str):
                        command = action_value
                        input_text = None
                    else:
                        command = action_value.get("command", "")
                        input_text = action_value.get("input", None)
                    return self.cli_service.shell(command, input_text)
                else:
                    return {
                        "status": "error",
                        "action": "shell",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }
            
            elif action_key == "view":
                if self.cli_service:
                    if isinstance(action_value, dict):
                        return self.cli_service.view(
                            path=action_value.get("path", ""),
                            start=action_value.get("start", 0),
                            end=action_value.get("end", 0),
                        )
                    return self.cli_service.view(action_value)
                else:
                    return {
                        "status": "error",
                        "action": "view",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }

            elif action_key == "grep":
                if self.cli_service:
                    if isinstance(action_value, dict):
                        return self.cli_service.grep(
                            pattern=action_value.get("pattern", ""),
                            path=action_value.get("path", ""),
                            glob_filter=action_value.get("glob", ""),
                            output_mode=action_value.get("output_mode", "content"),
                            case_insensitive=action_value.get("case_insensitive", False),
                            head_limit=action_value.get("head_limit", 50),
                            context=action_value.get("context", 0),
                        )
                    return self.cli_service.grep(pattern=str(action_value))
                else:
                    return {
                        "status": "error",
                        "action": "grep",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }

            elif action_key == "glob":
                if self.cli_service:
                    if isinstance(action_value, dict):
                        return self.cli_service.glob(
                            pattern=action_value.get("pattern", ""),
                            path=action_value.get("path", ""),
                            head_limit=action_value.get("head_limit", 100),
                        )
                    return self.cli_service.glob(pattern=str(action_value))
                else:
                    return {
                        "status": "error",
                        "action": "glob",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }

            elif action_key == "write":
                if self.cli_service:
                    path = action_value.get("path", "")
                    line = action_value.get("line", 1)
                    content = action_value.get("content", "")
                    return self.cli_service.write(path, line, content)
                else:
                    return {
                        "status": "error",
                        "action": "write",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }
            
            elif action_key == "replace":
                if self.cli_service:
                    path = action_value.get("path", "")
                    line = action_value.get("line", 0)
                    old_block = action_value.get("old_block", "")
                    new_block = action_value.get("new_block", "")
                    return self.cli_service.replace(path, line, old_block, new_block)
                else:
                    return {
                        "status": "error",
                        "action": "replace",
                        "message": "CLI service not initialized (cli_mode=False)"
                    }
                    
            elif action_key == "web":
                query = action_value
                logger.info(f"Performing web search: {query}")

                if self.web_callback:
                    self.web_callback("start")
                self._safe_cli_emit("web_loading_start")

                self._stop_loading = False
                loading_thread = threading.Thread(target=self._web_loading_animation)
                loading_thread.daemon = True
                loading_thread.start()

                try:
                    web_service = WebService(self.provider, self.model, self.api_key)
                    web_result = web_service.search(query)
                finally:
                    self._stop_loading = True
                    loading_thread.join(timeout=1)
                    if sys.stdout.isatty():
                        sys.stdout.write("\r" + " " * 50 + "\r")
                        sys.stdout.flush()

                    if self.web_callback:
                        self.web_callback("end")
                    self._safe_cli_emit("web_loading_end")

                return {
                    "status": "success",
                    "action": "tool",
                    "tool": "web",
                    "query": query,
                    "result": web_result
                }
            
            elif action_key == "todo_list":
                self.task_tracker.save_todo(action_value)
                return {"status": "success", "action": "todo_created"}
            
            elif action_key == "update_todo":
                success = self.task_tracker.update_task(action_value)
                if success:
                    return {"status": "success", "action": "todo_updated", "task": action_value}
                else:
                    return {
                        "status": "error",
                        "action": "todo_update_failed",
                        "message": "Could not update task"
                    }
            
            elif action_key == "scratchpad":
                success = self.scratchpad_service.append_scratchpad(action_value)
                if success:
                    return {"status": "success", "action": "scratchpad_added", "scratchpad": action_value}
                else:
                    return {
                        "status": "error",
                        "action": "scratchpad_failed",
                        "message": "Could not add scratchpad entry"
                    }

            elif action_key == "exit":
                summary = action_value
                logger.info(f"CLI Agent Exit: {summary}")
                return {"status": "success", "action": "exit", "summary": summary}

        return None
    
    def set_elements(self, elements_mapping, application_name=""):
        """Set the elements mapping in controller service"""
        self.controller_service.set_elements(elements_mapping, application_name)
