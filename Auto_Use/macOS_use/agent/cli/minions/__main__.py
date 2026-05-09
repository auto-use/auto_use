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
Minion Sub-Agent Entry Point (macOS)
====================================
Subprocess entry for the read-only scout minion.

Usage:
    python -m Auto_Use.macOS_use.agent.cli.minions --task "your question here"

    Options:
        --task      : Required. The question/objective for the minion to answer.
        --provider  : LLM provider (default: openrouter)
        --model     : LLM model (default: gemini-3-flash)
        --result    : Path to write result JSON when complete (optional)

When called from the parent CLI agent (via the `minion` action):
    - The CLI agent's controller spawns this as a subprocess.
    - The minion runs in its own session-isolated scratchpad (cli_minion/{sid}/).
    - On exit, the structured summary is written to --result and surfaced to the
      parent CLI agent as a <minion_completed> tool response.

When called directly for testing:
    python -m Auto_Use.macOS_use.agent.cli.minions --task "where is X defined?"
"""

import argparse
import json
from pathlib import Path

try:
    from app import debug_log, debug_exception
except ImportError:
    def debug_log(msg, level="INFO"):
        pass
    def debug_exception(context):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Minion Sub-Agent - Read-only scout for the parent CLI agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m Auto_Use.macOS_use.agent.cli.minions --task "where is _read_scratchpad_from_file defined and who calls it?"
    python -m Auto_Use.macOS_use.agent.cli.minions --task "list every file under src/ that imports requests"
        """
    )

    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="Question/objective for the minion to answer"
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
        help="Path to write result JSON when complete (for parent agent integration)"
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

    args = parser.parse_args()

    from .service import AgentService

    def on_complete(result: dict):
        if args.result:
            result_path = Path(args.result)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with open(result_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            try:
                print(f"Result written to: {args.result}")
            except (ValueError, OSError):
                pass

    agent = AgentService(
        provider=args.provider,
        model=args.model,
        save_conversation=False,
        thinking=args.thinking,
        api_key=args.api_key,
        task=args.task,
        on_complete=on_complete if args.result else None,
    )
    agent.process_request(args.task)


if __name__ == "__main__":
    main()
