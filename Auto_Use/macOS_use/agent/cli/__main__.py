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
CLI Agent Entry Point
======================
This module allows the CLI agent to be run as a subprocess.

Usage:
    python -m Auto_Use.macOS_use.agent.cli --task "your task here"
    
    Options:
        --task      : Required. The task for CLI agent to execute
        --provider  : LLM provider (default: openrouter)
        --model     : LLM model (default: gemini-3-flash)
        --result    : Path to write result JSON when complete (optional)

When called from main agent:
    - Main agent spawns this as subprocess
    - CLI agent runs with its own UI (pywebview on main thread)
    - Result is written to --result file when done

When called directly for testing:
    - Run: python -m Auto_Use.macOS_use.agent.cli --task "test task"
    - Or use cli.py at project root
"""

import argparse
import json
import sys
from pathlib import Path

# Import debug_log for error logging (fallback if app module not available)
try:
    from app import debug_log, debug_exception
except ImportError:
    def debug_log(msg, level="INFO"):
        pass
    def debug_exception(context):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="CLI Agent - Terminal-based coding assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m Auto_Use.macOS_use.agent.cli --task "fix the bug in test.py"
    python -m Auto_Use.macOS_use.agent.cli --task "create hello world" --provider openrouter --model gemini-3-flash
        """
    )
    
    parser.add_argument(
        "--task", 
        type=str, 
        required=True,
        help="Task description for the CLI agent"
    )
    parser.add_argument(
        "--provider", 
        type=str, 
        default="openrouter",
        help="LLM provider (default: openrouter)"
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default="gemini-3-flash",
        help="LLM model name (default: gemini-3-flash)"
    )
    parser.add_argument(
        "--result", 
        type=str, 
        default=None,
        help="Path to write result JSON when complete (for main agent integration)"
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        default=True,
        help="Enable thinking/reasoning mode (default: True)"
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="Runtime API key for LLM provider (optional, falls back to .env)"
    )
    parser.add_argument(
        "--position",
        type=int,
        default=0,
        help="Window corner position index (0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right, cycles)"
    )
    
    args = parser.parse_args()
    
    # Import here to avoid circular imports at module load
    from .service import AgentService
    
    # Callback to write result when CLI agent exits
    def on_complete(result: dict):
        if args.result:
            result_path = Path(args.result)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            try:
                print(f"Result written to: {args.result}")
            except (ValueError, OSError):
                pass  # stdout closed in compiled mode
    
    # Create and run CLI agent
    agent = AgentService(
        provider=args.provider,
        model=args.model,
        save_conversation=False,
        thinking=args.thinking,
        api_key=args.api_key,
        task=args.task,
        on_complete=on_complete if args.result else None,
        position=args.position
    )
    
    # Run the agent (this will show the pywebview UI)
    agent.process_request(args.task)


if __name__ == "__main__":
    main()
