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
import base64
from typing import Dict, Any, Optional
from .view import get_model_info

class OpenRouterProvider:
    """OpenRouter API provider for LLM interactions"""
    
    def __init__(self, api_key: str, thinking: bool = True, cli_agent: bool = False, schema: dict = None, model_info: dict = None):
        self.api_key = api_key
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.thinking = thinking
        self.cli_agent = cli_agent
        self.schema = schema
        self.model_info = model_info or {}
        
    def send_request(self, messages: list, model: str, annotated_screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Send request to OpenRouter API"""
        
        # If screenshot is provided and NOT cli_agent, modify the user message to include the annotated image
        if annotated_screenshot_base64 and not self.cli_agent and len(messages) > 1:
            user_message = messages[-1]["content"]
            messages[-1]["content"] = [
                {
                    "type": "text",
                    "text": user_message
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{annotated_screenshot_base64}"
                    }
                }
            ]
        

        if self.schema:
            response_format = {
                "type": "json_schema",
                "json_schema": self.schema
            }
        else:
            response_format = {"type": "json_object"}
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 10000,
            "route": "fallback",
            "seed": 42,
            "response_format": response_format
        }

        # Add reasoning if thinking is enabled and model supports it
        if self.thinking:
            model_info = get_model_info(model.split('/')[-1] if '/' in model else model)
            
            if model_info.get("reasoning_support", False):
                data["reasoning"] = {
                    "enabled": True,
                    "effort": self.model_info.get("reasoning_effort", "medium")
                }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(self.api_url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"OpenRouter API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f"\nResponse Body: {e.response.text}"
            raise Exception(error_msg)