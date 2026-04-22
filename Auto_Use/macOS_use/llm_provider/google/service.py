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
import base64
from typing import Dict, Any, Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

from .view import get_model_info, MODEL_MAPPINGS

load_dotenv()


def _clean_schema_for_google(schema):
    """Recursively remove 'additionalProperties' which Gemini API doesn't support."""
    if not isinstance(schema, dict):
        return schema
    cleaned = {k: _clean_schema_for_google(v) for k, v in schema.items() if k != "additionalProperties"}
    for k, v in cleaned.items():
        if isinstance(v, list):
            cleaned[k] = [_clean_schema_for_google(item) for item in v]
    return cleaned


class GoogleProvider:
    """Google Gemini API provider for LLM interactions"""
    
    def __init__(self, api_key: str = None, thinking: bool = True, cli_agent: bool = False, schema: dict = None, model: str = None, vertex_project_id: str = None, vertex_location: str = None):
        self.thinking = thinking
        self.cli_agent = cli_agent
        self.schema = schema
        
        # Check if model is vertex
        model_info = get_model_info(model) if model else {}
        self.is_vertex = model_info.get("vertex", False)
        
        if self.is_vertex:
            project = vertex_project_id or os.getenv("VERTEX_PROJECT_ID")
            location = vertex_location or os.getenv("VERTEX_LOCATION", "global")
            self.client = genai.Client(vertexai=True, project=project, location=location)
        else:
            key = api_key or os.getenv("GOOGLE_API_KEY")
            self.client = genai.Client(api_key=key)
    
    def _extract_text(self, content) -> str:
        """Extract text from message content (string or list format with cache_control)"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    return item.get("text", "")
            return str(content)
        return str(content)
    
    def send_request(self, messages: list, model: str, annotated_screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Send request to Google Gemini API"""
        
        # Convert OpenAI-style messages to Gemini format
        system_instruction = None
        contents = []
        
        for msg in messages:
            role = msg["role"]
            raw_content = msg["content"]
            
            if role == "system":
                system_instruction = self._extract_text(raw_content)
            elif role == "assistant":
                text = self._extract_text(raw_content)
                contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
            elif role == "user":
                text = self._extract_text(raw_content)
                contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        
        # Add screenshot to last user message if provided and NOT cli_agent
        if annotated_screenshot_base64 and not self.cli_agent and len(contents) > 0:
            last = contents[-1]
            if last.role == "user":
                image_bytes = base64.b64decode(annotated_screenshot_base64)
                last.parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        
        # Build generation config
        config_params = {
            "max_output_tokens": 10000,
            "seed": 42,
        }
        
        # System instruction
        if system_instruction:
            config_params["system_instruction"] = system_instruction
        
        # Thinking (always MEDIUM for both models)
        if self.thinking:
            config_params["thinking_config"] = types.ThinkingConfig(thinking_level="MEDIUM")
        
        # Structured output (response_mime_type + response_schema)
        config_params["response_mime_type"] = "application/json"
        if self.schema:
            config_params["response_schema"] = _clean_schema_for_google(self.schema.get("schema", {}))
        
        config = types.GenerateContentConfig(**config_params)
        
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            
            # Normalize to OpenAI-style format
            return {
                "choices": [{
                    "message": {
                        "content": response.text
                    }
                }]
            }
        except Exception as e:
            raise Exception(f"Google Gemini API request failed: {str(e)}")