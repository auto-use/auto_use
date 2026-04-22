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

import requests
import copy
from typing import Dict, Any, Optional

from .view import get_model_info

class AnthropicProvider:
    """Anthropic API provider for LLM interactions"""
    
    def __init__(self, api_key: str, cli_agent: bool = False, schema: dict = None):
        self.api_key = api_key
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.cli_agent = cli_agent
        self.schema = schema
        
    @staticmethod
    def _strip_unsupported_keywords(obj):
        """Recursively strip JSON Schema keywords not supported by Anthropic structured outputs"""
        unsupported = {"maxItems", "minItems", "strict"}
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key in unsupported:
                    del obj[key]
                else:
                    AnthropicProvider._strip_unsupported_keywords(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                AnthropicProvider._strip_unsupported_keywords(item)
    
    def send_request(self, messages: list, model: str, annotated_screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Send request to Anthropic API"""
        
        # Extract system prompt from messages (Anthropic uses top-level 'system' field)
        system_content = None
        api_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})
        
        # If screenshot is provided and NOT cli_agent, modify the last user message to include the annotated image
        if annotated_screenshot_base64 and not self.cli_agent and len(api_messages) > 0:
            last_msg = api_messages[-1]
            if last_msg["role"] == "user":
                user_text = last_msg["content"]
                
                # Handle case where content is already a list
                if isinstance(user_text, list):
                    text_content = ""
                    for item in user_text:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_content = item.get("text", "")
                            break
                    user_text = text_content
                
                # Anthropic uses source-based image format (not image_url)
                api_messages[-1]["content"] = [
                    {
                        "type": "text",
                        "text": user_text
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": annotated_screenshot_base64
                        }
                    }
                ]
        
        # Build system as list with cache_control for prompt caching
        system_param = None
        if system_content:
            system_param = [
                {
                    "type": "text",
                    "text": system_content,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 4000,
            "temperature": 0.2
        }
        
        if system_param:
            data["system"] = system_param
        
        # Structured outputs via output_config.format
        if self.schema:
            # Deep copy schema and strip unsupported properties (Anthropic doesn't support maxItems, minItems)
            import json as _json
            clean_schema = _json.loads(_json.dumps(self.schema.get("schema", {})))
            self._strip_unsupported_keywords(clean_schema)
            
            data["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": clean_schema
                }
            }
        
        try:
            response = requests.post(self.api_url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            # Normalize response to match OpenAI-style format (choices[0].message.content)
            # Anthropic returns: content: [{type: "thinking", ...}, {type: "text", text: "..."}]
            text_content = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text_content = block.get("text", "")
                    break
            
            return {
                "choices": [{
                    "message": {
                        "content": text_content
                    }
                }]
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Anthropic API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f"\nResponse Body: {e.response.text}"
            raise Exception(error_msg)