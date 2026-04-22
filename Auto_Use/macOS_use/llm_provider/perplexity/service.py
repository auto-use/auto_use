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
from typing import Dict, Any, Optional

from .view import get_model_info


class PerplexityProvider:
    """Perplexity Agent API provider for LLM interactions"""
    
    def __init__(self, api_key: str, cli_agent: bool = False, schema: dict = None, model_info: dict = None):
        self.api_key = api_key
        self.api_url = "https://api.perplexity.ai/v1/agent"
        self.cli_agent = cli_agent
        self.schema = schema
        self.model_info = model_info or {}
        
    def send_request(self, messages: list, model: str, annotated_screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Send request to Perplexity Agent API"""
        
        # Separate system prompt from conversation messages
        instructions = None
        input_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            instructions = item.get("text", "")
                            break
                else:
                    instructions = content
            elif msg["role"] == "assistant":
                text = self._extract_text(msg["content"])
                input_messages.append({"role": "assistant", "content": [{"type": "output_text", "text": text}]})
            elif msg["role"] == "user":
                text = self._extract_text(msg["content"])
                input_messages.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        
        # Add screenshot to last user message if provided and NOT cli_agent
        if annotated_screenshot_base64 and not self.cli_agent and len(input_messages) > 0:
            last = input_messages[-1]
            if last["role"] == "user":
                last["content"].append({
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{annotated_screenshot_base64}"
                })
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "input": input_messages,
            "max_output_tokens": 10000,
        }
        
        if instructions:
            data["instructions"] = instructions
        
        # Reasoning effort (low/medium/high) if model supports it
        if self.model_info.get("reasoning_support", False):
            data["reasoning"] = {
                "effort": self.model_info.get("reasoning_effort", "low")
            }
        
        # Structured output via response_format
        if self.schema:
            data["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.schema.get("name", "response"),
                    "schema": self.schema.get("schema", {})
                }
            }
        
        try:
            response = requests.post(self.api_url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            # Normalize to choices[0].message.content format
            text_content = ""
            for output_item in result.get("output", []):
                if output_item.get("type") == "message":
                    for content_block in output_item.get("content", []):
                        if content_block.get("type") == "output_text":
                            text_content = content_block.get("text", "")
                            break
                    if text_content:
                        break
            
            return {
                "choices": [{
                    "message": {
                        "content": text_content
                    }
                }]
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Perplexity API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f"\nResponse Body: {e.response.text}"
            raise Exception(error_msg)
    
    @staticmethod
    def _extract_text(content) -> str:
        """Extract text from message content (string or list format with cache_control)"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    return item.get("text", "")
            return str(content)
        return str(content)