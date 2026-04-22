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

from typing import Dict, Any, Optional

from openai import OpenAI

from .view import get_model_info

class OpenAIProvider:
    """OpenAI API provider for LLM interactions"""
    
    def __init__(self, api_key: str, thinking: bool = False, cli_agent: bool = False, schema: dict = None):
        self.client = OpenAI(api_key=api_key)
        self.thinking = thinking
        self.cli_agent = cli_agent
        self.schema = schema
        
    def send_request(self, messages: list, model: str, annotated_screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Send request to OpenAI API"""
        
        # If screenshot is provided and NOT cli_agent, modify the user message to include the annotated image
        if annotated_screenshot_base64 and not self.cli_agent and len(messages) > 1:
            user_message = messages[-1]["content"]
            
            # Handle case where content might already be a list
            if isinstance(user_message, list):
                # Extract text from existing list structure
                text_content = ""
                for item in user_message:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_content = item.get("text", "")
                        break
                user_message = text_content
            
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
        
        # Prepare API call parameters
        params = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": 4000,
            "verbosity": "medium"  # Set verbosity to medium
        }
        
        # Use json_schema with strict: true (all OpenAI models support it)
        if self.schema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": self.schema
            }
        else:
            params["response_format"] = {"type": "json_object"}
        
        # Configure reasoning effort based on thinking setting
        # Get model info to check if it supports reasoning
        model_info = get_model_info(model.split('/')[-1] if '/' in model else model)
        
        # Set reasoning_effort based on thinking flag
        if model_info.get("reasoning_support", False):
            if self.thinking:
                params["reasoning_effort"] = "low"
            else:
                params["reasoning_effort"] = "none"
        
        try:
            response = self.client.chat.completions.create(**params)
            
            # Return in the same format as other providers
            return {
                "choices": [{
                    "message": {
                        "content": response.choices[0].message.content
                    }
                }]
            }
        except Exception as e:
            error_msg = f"OpenAI API request failed: {str(e)}"
            raise Exception(error_msg)