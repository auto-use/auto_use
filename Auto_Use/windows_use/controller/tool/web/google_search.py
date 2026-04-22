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
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, api_key=None, vertex=False, vertex_project_id=None, vertex_location=None):
    """
    Perform web search using Google Gemini 3 Flash with grounding via Google Search + thinking

    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
        vertex: Whether to use Vertex AI endpoint
        vertex_project_id: GCP project ID (priority over .env)
        vertex_location: GCP region (priority over .env)
    """
    try:
        if vertex:
            project = vertex_project_id or os.getenv('VERTEX_PROJECT_ID')
            location = vertex_location or os.getenv('VERTEX_LOCATION', 'global')
            client = genai.Client(vertexai=True, project=project, location=location)
        else:
            key = api_key or os.getenv('GOOGLE_API_KEY')
            client = genai.Client(api_key=key)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            thinking_config=types.ThinkingConfig(thinking_level="MEDIUM"),
            max_output_tokens=8192,
            seed=42,
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=query,
            config=config,
        )

        return response.text
    except Exception as e:
        return f"Error in web search: {str(e)}"


if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))