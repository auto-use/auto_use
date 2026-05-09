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
Minion Sub-Agent Service — read-only scout sub-agent loop.

Mirror of cli/service.py with three intentional differences:
  1. Loads minions/system_prompt.md (read-only scout prompt, next_goal blocks).
  2. Uses MINION_SCHEMA via LLMManager(mode="minion"); no write/replace/web/wait/todo.
  3. user_message injects <scratchpad> (per the minion prompt's <input> contract)
     instead of <todo_list> (which the CLI agent uses).

Everything else — the agent-loop shape, history threading, prompt caching, JSON
extraction, action routing through ControllerView, exit semantics — mirrors the
CLI agent so future maintenance can be done by reference.
"""

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

from ....llm_provider.llm_manager import LLMManager
from ....controller.view import ControllerView
from .view import MinionResponseFormatter

try:
    from app import debug_log, IS_COMPILED
except ImportError:
    def debug_log(msg, level="INFO"):
        pass
    IS_COMPILED = False


def _ensure_real_stdio_or_fallback():
    for name, fd in (('stdout', 1), ('stderr', 2)):
        stream = getattr(sys, name, None)
        if stream is not None and not (hasattr(stream, 'closed') and stream.closed):
            continue
        try:
            raw = os.fdopen(fd, 'wb', buffering=0, closefd=False)
            wrapped = io.TextIOWrapper(
                raw,
                encoding='utf-8',
                errors='replace',
                write_through=True,
                line_buffering=False,
            )
            setattr(sys, name, wrapped)
        except OSError:
            setattr(sys, name, io.StringIO())

_ensure_real_stdio_or_fallback()


def safe_print(*args, **kwargs):
    """Print that won't crash if stdout is unavailable."""
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except (ValueError, OSError, AttributeError):
        msg = ' '.join(str(a) for a in args)
        debug_log(f"[PRINT] {msg}")


# Minion runs are bounded — its job is location-finding, not multi-step coding.
MAX_MINION_ITERATIONS = 30


class AgentService:
    """Minion Agent Service - read-only scout sub-agent loop."""

    def __init__(self, provider: str, model: str, save_conversation: bool = False,
                 thinking: bool = True, api_key: str = None, stop_event=None,
                 task: str = None, on_complete: callable = None):

        self.provider = provider
        self.model = model
        self.save_conversation = save_conversation
        self.stop_event = stop_event
        self.task = task
        self.on_complete = on_complete

        # Generate unique session ID for complete isolation (cli_minion/{sid}/...)
        self.session_id = uuid.uuid4().hex[:8]

        # Initialize LLM Manager in minion mode → MINION_SCHEMA (no write/replace/web/todo).
        self.llm = LLMManager(
            provider=provider,
            model=model,
            thinking=thinking,
            api_key=api_key,
            cli_agent=True,
            mode="minion",
        )

        # Initialize Controller in cli_mode + minion_mode so scratchpad routes to
        # scratchpad/cli_minion/{session_id}/ and never touches the parent CLI agent's
        # cli_milestone/ folder.
        self.controller = ControllerView(
            provider=provider, model=model,
            cli_mode=True, session_id=self.session_id,
            api_key=api_key,
            minion_mode=True,
        )

        # Response formatter — minion-specific (validates next_goal-shape responses).
        self.formatter = MinionResponseFormatter

        # Load minion system prompt (sibling system_prompt.md inside this minions/ package).
        self.system_prompt = self._load_system_prompt()

        if self.save_conversation:
            self.conversation_dir = Path("cli_minion_conversation") / self.session_id
            self.conversation_dir.mkdir(parents=True, exist_ok=True)
            self.raw_reasoning_dir = self.conversation_dir / "raw_reasoning"
            self.raw_reasoning_dir.mkdir(parents=True, exist_ok=True)

        self.interaction_count = 0

    def _save_conversation_snapshot(self, messages: list, current_assistant_response: str, interaction_count: int):
        """Save TRUE agent memory — exactly what LLM receives at each step."""
        if not self.save_conversation:
            return

        conversation_file = self.conversation_dir / f"conversation_{interaction_count}.txt"

        with open(conversation_file, 'w', encoding='utf-8') as f:
            f.write("=== MINION MEMORY SNAPSHOT ===\n")
            f.write(f"Step: {interaction_count}\n")
            f.write(f"Time: {datetime.now()}\n")
            f.write("=" * 60 + "\n\n")

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

            f.write(f"=== CURRENT ASSISTANT RESPONSE (role='assistant') ===\n")
            f.write(current_assistant_response)
            f.write("\n")

    def _save_raw_response(self, raw_response: str, step_number: int):
        """Save raw LLM response before any parsing/normalization (for debugging)."""
        if self.save_conversation:
            try:
                raw_file = self.raw_reasoning_dir / f"raw_response_{step_number}.txt"
                with open(raw_file, 'w', encoding='utf-8') as f:
                    f.write(raw_response)
            except Exception as e:
                safe_print(f"⚠ Error saving raw response: {str(e)}")

    def _load_system_prompt(self) -> str:
        """Load minion system prompt from sibling system_prompt.md."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(current_dir, "system_prompt.md")

        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _remove_thinking_from_response(self, response_json: str) -> str:
        """Remove 'thinking' field from assistant response to save tokens in history."""
        try:
            response_data = json.loads(response_json)
            if "thinking" in response_data:
                del response_data["thinking"]
            return json.dumps(response_data, indent=2, ensure_ascii=False)
        except Exception:
            return response_json

    def _remove_agent_sitting_from_user_message(self, user_message: str) -> str:
        """Remove <agent_sitting> block from user message to save tokens in history."""
        try:
            cleaned = re.sub(r'<agent_sitting>.*?</agent_sitting>', '', user_message, flags=re.DOTALL)
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            return cleaned.strip()
        except Exception:
            return user_message

    def _read_scratchpad_from_file(self) -> str:
        """Read the minion's scratchpad (cli_minion/{session_id}/milestone.md)."""
        try:
            return self.controller.scratchpad_service.read_scratchpad()
        except Exception:
            return ""

    def _get_agent_sitting(self) -> str:
        """Get agent workspace and current directory info."""
        workspace = str(self.controller.cli_service.sandbox.sandbox_root)
        current = self.controller.cli_service.sandbox.get_cwd()
        return f"your_workspace: {workspace}\ncurrent_sitting: {current}"

    def process_request(self, task: str) -> str:
        """Run the minion loop synchronously."""
        return self._run_agent_loop(task)

    def _run_agent_loop(self, task: str) -> str:
        """Main agentic loop — mirrors cli/service.py with scratchpad-in-user-message."""

        step_number = 0
        last_response = None
        is_first = True
        history = []
        json_fail_count = 0

        while True:
            if self.stop_event and self.stop_event.is_set():
                safe_print("Minion stopped.")
                break

            step_number += 1

            if step_number > MAX_MINION_ITERATIONS:
                safe_print(f"Minion reached max iterations ({MAX_MINION_ITERATIONS})")

                scratchpad_status = self._read_scratchpad_from_file()
                summary = f"Max iterations ({MAX_MINION_ITERATIONS}) reached. Findings so far:\n{scratchpad_status}"

                if self.on_complete:
                    self.on_complete({
                        "task": self.task,
                        "summary": summary,
                        "status": "partial"
                    })

                return "Max iterations reached"

            safe_print(f"minion running step {step_number}")

            agent_sitting = self._get_agent_sitting()

            # Read fresh scratchpad — minion's prompt expects <scratchpad> in <input>,
            # NOT <todo_list> like the CLI agent.
            scratchpad_content = self._read_scratchpad_from_file()

            if is_first:
                user_message = f"<user_request>\n{task}\n</user_request>\n\n<agent_sitting>\n{agent_sitting}\n</agent_sitting>"
            else:
                scratchpad_block = scratchpad_content if scratchpad_content else "none"
                user_message = (
                    f"<user_request>\n{task}\n</user_request>\n\n"
                    f"<scratchpad>\n{scratchpad_block}\n</scratchpad>\n\n"
                    f"<agent_sitting>\n{agent_sitting}\n</agent_sitting>"
                )

            # Build messages with proper history (assistant + tool_response pairs)
            messages = [{"role": "system", "content": self.system_prompt}]

            if len(history) > 0 and not is_first:
                step1_msg = history[0][0]
                messages.append({"role": "assistant", "content": f"<User_Task>\n{task}\n</User_Task>\n\n{step1_msg}"})

                if len(history) == 1:
                    if history[0][1]:
                        user_message = f"{history[0][1]}\n\n{user_message}"
                else:
                    if history[0][1]:
                        messages.append({"role": "user", "content": history[0][1]})

                    for assistant_msg, tool_response in history[1:-1]:
                        messages.append({"role": "assistant", "content": assistant_msg})
                        if tool_response:
                            messages.append({"role": "user", "content": tool_response})

                    last_assistant, last_tool_response = history[-1]
                    messages.append({"role": "assistant", "content": last_assistant})
                    if last_tool_response:
                        user_message = f"{last_tool_response}\n\n{user_message}"

            messages.append({"role": "user", "content": user_message})

            # Prompt caching for OpenRouter / Anthropic — same as CLI agent.
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
                raw_response = self.llm.send_request(messages)

                if raw_response:
                    safe_print(raw_response)

                if self.stop_event and self.stop_event.is_set():
                    break

                self._save_raw_response(raw_response, step_number)

                success, normalized, failed_raw = self.formatter.normalize_response(raw_response)

                if not success:
                    json_fail_count += 1
                    safe_print(f"⚠️ JSON parse failed ({json_fail_count}/3). Discarding and retrying...")

                    if json_fail_count >= 3:
                        break

                    step_number -= 1
                    continue

                json_fail_count = 0

                self._save_conversation_snapshot(messages, normalized, step_number)

                normalized_without_thinking = self._remove_thinking_from_response(normalized)

                action_block = self.formatter.get_action_block(normalized)

                action_result = self.controller.route_action(action_block)

                # Minion exit — deliver structured summary back to caller (parent
                # controller writes the result file via on_complete).
                if action_result.get("action") == "exit":
                    summary = action_result.get("summary", "Findings ready.")

                    if self.on_complete:
                        self.on_complete({
                            "task": self.task,
                            "summary": summary,
                            "status": "complete"
                        })

                    return "Exit"

                # Format result block for next iteration's <Tool_response>.
                # Minion only emits shell/view/grep/glob/scratchpad/exit — keep just
                # those branches; defensive `else` handles unexpected shapes.
                if action_result.get("action") == "shell":
                    status = action_result.get("status", "success")
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

                elif action_result.get("action") == "view":
                    last_response = f"""<Tool_response>
<view>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output:
{action_result.get("output", "")}
</view>
</Tool_response>"""

                elif action_result.get("action") == "grep":
                    last_response = f"""<Tool_response>
<grep>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output:
{action_result.get("output", "")}
</grep>
</Tool_response>"""

                elif action_result.get("action") == "glob":
                    last_response = f"""<Tool_response>
<glob>
command: {action_result.get("command", "")}
status: {action_result.get("status", "")}
output:
{action_result.get("output", "")}
</glob>
</Tool_response>"""

                elif action_result.get("action") == "multiple":
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
                        elif result.get("action") == "grep":
                            formatted_results.append(f"""<grep>
command: {result.get("command", "")}
status: {result.get("status", "")}
output:
{result.get("output", "")}
</grep>""")
                        elif result.get("action") == "glob":
                            formatted_results.append(f"""<glob>
command: {result.get("command", "")}
status: {result.get("status", "")}
output:
{result.get("output", "")}
</glob>""")
                        elif result.get("action") == "scratchpad_added":
                            formatted_results.append(f"""<scratchpad_added>
scratchpad: {result.get("scratchpad", "")}
</scratchpad_added>""")
                        else:
                            action_name = result.get("action", "result")
                            formatted_results.append(f"<{action_name}>\nstatus: {result.get('status', 'success')}\n</{action_name}>")

                    last_response = f"<Tool_response>\n" + "\n\n".join(formatted_results) + "\n</Tool_response>"

                else:
                    last_response = f"<Tool_response>\n{json.dumps(action_result, indent=2)}\n</Tool_response>"

                history.append((normalized_without_thinking, last_response))

                is_first = False

            except Exception as e:
                safe_print(f"Error: {str(e)}")
                debug_log(f"Minion loop error: {str(e)}", "ERROR")
                import traceback
                debug_log(f"Minion traceback: {traceback.format_exc()}", "ERROR")
                break

        return "Agent loop ended"
