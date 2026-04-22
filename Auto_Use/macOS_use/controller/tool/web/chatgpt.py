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
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Get the directory where this file is located
current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()

def web_search(query, api_key=None):
    """
    Perform web search using OpenAI gpt-5.1 with Responses API
    
    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        # Priority: frontend key > .env fallback
        key = api_key or os.getenv('OPENAI_API_KEY')
        
        client = OpenAI(api_key=key)
        
        response = client.responses.create(
            model="gpt-5.1",
            instructions=system_prompt,
            input=query,
            reasoning={"effort": "medium"},
            text={"verbosity": "medium"},
            store=True,
            tools=[
                {
                    "type": "web_search"
                }
            ]
        )
        
        # Extract text from response structure
        # Response is a list of items, we need to find the output message
        if hasattr(response, 'output'):
            output = response.output
            # output is a list, find the message with text
            for item in output:
                if hasattr(item, 'type') and item.type == 'message':
                    if hasattr(item, 'content') and item.content:
                        for content_item in item.content:
                            if hasattr(content_item, 'text'):
                                return content_item.text
        
        # Fallback: return string representation
        return str(response)
    except Exception as e:
        raise Exception(f"Error in web search: {str(e)}")

if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))