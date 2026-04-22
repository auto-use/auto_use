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

#this main.py give terminal interface to the user to interact with the agent for ui refer app.py
import platform

if platform.system() == "Darwin":
    from Auto_Use.macOS_use.agent.service import AgentService
elif platform.system() == "Windows":
    from Auto_Use.windows_use.agent.service import AgentService
else:
    raise RuntimeError(f"Unsupported OS: {platform.system()}")

# Configuration
PROVIDER = "perplexity"
MODEL = "gemini-3-flash" #refer to the model name correctly from the view.py from llm provider folder.
# Your task here
task = """

write hello in milestone

"""

# Control conversation saving
conversation = False  # Set to False to disable conversation.txt
# Control thinking/reasoning
thinking = True  # Set to True to enable reasoning for supported models

# Run the agent
agent = AgentService(provider=PROVIDER, model=MODEL, save_conversation=conversation)
agent.process_request(task)

# Response is displayed inside process_request