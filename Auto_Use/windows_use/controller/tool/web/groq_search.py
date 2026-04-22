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
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Get the directory where this file is located
current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()

def web_search(query, api_key=None):
    try:
        # Priority: frontend key > .env fallback
        key = api_key or os.getenv('GROQ_API_KEY')
        
        client = Groq(
            api_key=key,
            default_headers={
                "Groq-Model-Version": "latest"
            }
        )
        completion = client.chat.completions.create(
            model="groq/compound",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            temperature=0.2,
            max_completion_tokens=8192,
            top_p=1,
            stream=False,
            stop=None,
            seed=42,
            compound_custom={"tools":{"enabled_tools":["visit_website","web_search","browser_automation"]}}
        )
        
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error in web search: {str(e)}"

if __name__ == "__main__":
    query = input("Search: ")
    web_search(query)
