# Copyright 2026 Ashish Yadav (Autouse AI)
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

from Auto_Use.macOS_use.agent.service import AgentService

# Configuration
PROVIDER = "perplexity"
MODEL = "gemini-3.1-pro" #refer to the model name correctly from the Auto_Use/OS_use/llm_provider/view.py from llm provider folder.
# Your task here
task = """

open youtube and playy something

"""

# Control conversation saving
conversation = False  # Set to False to disable conversation.txt
# Control thinking/reasoning
thinking = True  # Set to True to enable reasoning for supported models

# Run the agent
agent = AgentService(provider=PROVIDER, model=MODEL, save_conversation=conversation)
agent.process_request(task)

# Response is displayed inside process_request