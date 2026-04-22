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
import time
from pathlib import Path

from .openrouter import web_search as openrouter_web_search
from .groq_search import web_search as groq_web_search
from .chatgpt import web_search as chatgpt_web_search
from .anthropic import web_search as anthropic_web_search
from .google_search import web_search as google_web_search
from .perplexity_search import web_search as perplexity_web_search
from ....llm_provider.openrouter.view import get_model_info as get_openrouter_model_info


class WebService:
    """Web service to route queries to appropriate provider"""
    
    def __init__(self, provider: str, model: str, api_key: str = None, vertex: bool = False, vertex_project_id: str = None, vertex_location: str = None):
        self.provider = provider.lower()
        self.api_key = api_key  # Runtime key from frontend (priority over .env)
        # Auto-detect Vertex from model name (e.g. "gemini-3.1-pro-vertex")
        self.vertex = vertex or (self.provider == "google" and model and model.endswith("-vertex"))
        self.vertex_project_id = vertex_project_id
        self.vertex_location = vertex_location
        
        # Resolve short model name to full API name for OpenRouter
        if self.provider == "openrouter":
            model_info = get_openrouter_model_info(model)
            self.model = model_info["api_name"]
        else:
            self.model = model
        
    def search(self, query: str) -> str:
        """Route web search to appropriate provider and format response as JSON object"""
        # Retry up to 3 times with 1 second delay
        for attempt in range(3):
            try:
                if self.provider == "openrouter":
                    result = openrouter_web_search(query, self.model, self.api_key)
                elif self.provider == "groq":
                    result = groq_web_search(query, self.api_key)  # Groq always uses compound
                elif self.provider == "openai":
                    result = chatgpt_web_search(query, self.api_key)  # OpenAI always uses gpt-5.1
                elif self.provider == "anthropic":
                    result = anthropic_web_search(query, self.api_key)  # Anthropic uses Haiku 4.5 with native web_search
                elif self.provider == "google":
                    result = google_web_search(query, self.api_key, self.vertex, self.vertex_project_id, self.vertex_location)  # Google uses Gemini 3 Flash with grounding
                elif self.provider == "perplexity":
                    result = perplexity_web_search(query, self.api_key)  # Perplexity uses Sonar with native web search
                else:
                    result = f"Unsupported provider: {self.provider}"
                
                # Format as JSON object (no wrapper tags - agent adds <tool> wrapper)
                formatted_response = f'''{{\ntool: web,\nstatus: success,\nquery: "{query}",\nInformation: "{result}"\n}}'''
                return formatted_response
                
            except Exception as e:
                if attempt < 2:  # If not the last attempt
                    print(f"⚠️ Web search failed (attempt {attempt + 1}/3), retrying in 1 second...")
                    time.sleep(1)
                    continue
                else:
                    # Last attempt failed, return error
                    error_msg = f"Web service error: {str(e)}"
                    return f'''{{\ntool: web,\nstatus: error,\nquery: "{query}",\nNote: Search failed after 3 attempts,\nInformation: "{error_msg}"\n}}'''
