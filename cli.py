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

# this cli.py directly starts the CLI agent (skipping the main agent layer).
# For the full main agent terminal interface refer to main.py, for UI refer to app.py.
import platform

if platform.system() == "Darwin":
    from Auto_Use.macOS_use.agent.cli import AgentService
elif platform.system() == "Windows":
    from Auto_Use.windows_use.agent.cli import AgentService
else:
    raise RuntimeError(f"Unsupported OS: {platform.system()}")

# Configuration
PROVIDER = "openrouter"
MODEL = "gemini-3.1-pro"  # refer to the model name correctly from model_list.txt.

# Your task here
task = """

ask minion to check what all things are there in mac download directory.
"""

# Control conversation saving
conversation = True  # Set to False to disable conversation.txt
# Control thinking/reasoning
thinking = True  # Set to True to enable reasoning for supported models

# Run the CLI agent directly
agent = AgentService(
    provider=PROVIDER,
    model=MODEL,
    save_conversation=conversation,
    thinking=thinking,
)
agent.process_request(task)

# Response is displayed inside process_request
