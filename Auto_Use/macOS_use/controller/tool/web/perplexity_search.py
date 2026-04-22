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
import requests
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, api_key=None):
    """
    Perform web search using Perplexity Sonar via Agent API

    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        key = api_key or os.getenv('PERPLEXITY_API_KEY')

        response = requests.post(
            "https://api.perplexity.ai/v1/agent",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "perplexity/sonar",
                "instructions": system_prompt,
                "input": query,
                "tools": [{"type": "web_search"}],
                "max_output_tokens": 4096,
            }
        )
        response.raise_for_status()
        result = response.json()

        # Extract text from Agent API response
        for output_item in result.get("output", []):
            if output_item.get("type") == "message":
                for block in output_item.get("content", []):
                    if block.get("type") == "output_text":
                        return block.get("text", "")

        return str(result)
    except Exception as e:
        raise Exception(f"Error in web search: {str(e)}")


if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))