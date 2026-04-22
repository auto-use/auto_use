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
import anthropic
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, api_key=None):
    """
    Perform web search using Anthropic Claude Haiku 4.5 with native web_search tool

    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        key = api_key or os.getenv('ANTHROPIC_API_KEY')

        client = anthropic.Anthropic(api_key=key)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": query}
            ],
            tools=[
                {"type": "web_search_20250305", "name": "web_search"}
            ],
        )

        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        return "\n".join(text_parts) if text_parts else str(response)
    except Exception as e:
        raise Exception(f"Error in web search: {str(e)}")


if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))
