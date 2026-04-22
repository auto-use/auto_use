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
from typing import Optional

from dotenv import load_dotenv

from .openrouter.service import OpenRouterProvider
from .openrouter.view import get_model_info as get_openrouter_model_info
from .groq.service import GroqProvider
from .groq.view import get_model_info as get_groq_model_info
from .openai.service import OpenAIProvider
from .openai.view import get_model_info as get_openai_model_info
from .anthropic.service import AnthropicProvider
from .anthropic.view import get_model_info as get_anthropic_model_info
from .google.service import GoogleProvider
from .google.view import get_model_info as get_google_model_info
from .perplexity.service import PerplexityProvider
from .perplexity.view import get_model_info as get_perplexity_model_info

# Load environment variables
load_dotenv()

# CLI Agent Output Schema (simpler - text only, no vision)
# Uses anyOf discriminated union — each action type carries only its own fields
# Grouped by field signature to minimize anyOf branches (6 instead of 11)
CLI_AGENT_SCHEMA = {
    "name": "cli_agent_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "current_goal": {"type": "string"},
            "memory": {"type": "string"},
            "action": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "shell"},
                                "command": {"type": "string"},
                                "input": {"type": "string"}
                            },
                            "required": ["type", "command", "input"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "view"},
                                "path": {"type": "string"}
                            },
                            "required": ["type", "path"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "write"},
                                "path": {"type": "string"},
                                "line": {"type": "integer"},
                                "content": {"type": "string"}
                            },
                            "required": ["type", "path", "line", "content"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "replace"},
                                "path": {"type": "string"},
                                "line": {"type": "integer"},
                                "old_block": {"type": "string"},
                                "new_block": {"type": "string"}
                            },
                            "required": ["type", "path", "line", "old_block", "new_block"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["web", "todo_list", "update_todo", "wait", "milestone", "exit"]},
                                "value": {"type": "string"}
                            },
                            "required": ["type", "value"],
                            "additionalProperties": False
                        }
                    ]
                }
            }
        },
        "required": ["thinking", "current_goal", "memory", "action"],
        "additionalProperties": False
    }
}

# Main Agent Output Schema (with vision support)
# Uses anyOf discriminated union — each action type carries only its own fields (no nulls, no waste)
# Grouped by field signature to minimize anyOf branches (6 instead of 18)
AGENT_OUTPUT_SCHEMA = {
    "name": "agent_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "verdict_last_action": {"type": "string"},
            "decision": {"type": "string"},
            "current_goal": {"type": "string"},
            "memory": {"type": "string"},
            "action": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["left_click", "right_click", "screenshot"]},
                                "id": {"type": "integer"},
                                "clicks": {"type": "integer"}
                            },
                            "required": ["type", "id", "clicks"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "input"},
                                "id": {"type": "integer"},
                                "value": {"type": "string"}
                            },
                            "required": ["type", "id", "value"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "scroll"},
                                "id": {"type": "integer"},
                                "direction": {"type": "string"}
                            },
                            "required": ["type", "id", "direction"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["shortcut_combo", "open_app", "wait", "web", "shell", "cli_agent", "cli_await", "todo_list", "update_todo", "milestone", "drag_drop", "done", "canvas_input"]},
                                "value": {"type": "string"}
                            },
                            "required": ["type", "value"],
                            "additionalProperties": False
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "const": "applescript"},
                                "app": {"type": "string"},
                                "value": {"type": "string"}
                            },
                            "required": ["type", "app", "value"],
                            "additionalProperties": False
                        }
                    ]
                }
            }
        },
        "required": ["thinking", "verdict_last_action", "decision", "current_goal", "memory", "action"],
        "additionalProperties": False
    }
}

class LLMManager:
    """Manager to route requests to the correct LLM provider"""
    
    def __init__(self, provider: str, model: str, thinking: bool = True, api_key: str = None, cli_agent: bool = False):
        self.provider = provider.lower()
        self.model_short_name = model
        self.thinking = thinking
        self.runtime_api_key = api_key  # Runtime key from frontend (priority)
        self.cli_agent = cli_agent  # Flag for CLI agent (text-only, different schema)
        
        # CLI agent gets its own hardcoded model per provider (independent from main agent)
        if cli_agent:
            is_vertex = model.endswith("-vertex")
            _CLI_MODEL_MAP = {
                "groq": "gpt-oss-120b",           # GPT-OSS 120B
                "openai": "gpt-5.2",              # GPT-5.2
                "openrouter": "gemini-3.1-pro",        # gemini-3-pro
                "anthropic": "claude-sonnet-4.6",     # Sonnet 4.6
                "google": "gemini-3.1-pro-vertex" if is_vertex else "gemini-3.1-pro",
                "perplexity": "gemini-3.1-pro",       # Gemini 3.1 Pro via Perplexity
            }
            _CLI_FALLBACK_MAP = {
                "groq": "llama-4-scout",           # GPT-OSS fails → Scout
                "openai": "gpt-5.1",              # GPT-5.2 fails → GPT-5.1
                "openrouter": "gemini-3-flash",      # gemini-3-pro → gemini-3-flash
                "anthropic": "claude-sonnet-4.5",    # Sonnet 4.6 fails → Sonnet 4.5
                "google": "gemini-3-flash-vertex" if is_vertex else "gemini-3-flash",
                "perplexity": "claude-opus-4.6",      # Gemini 3.1 Pro fails → Claude Opus 4.6
            }
            self._cli_fallback_model = _CLI_FALLBACK_MAP.get(self.provider)
            model = _CLI_MODEL_MAP.get(self.provider, model)
        
        # Get model info based on provider
        if self.provider == "openrouter":
            model_info = get_openrouter_model_info(model)
        elif self.provider == "groq":
            model_info = get_groq_model_info(model)
        elif self.provider == "openai":
            model_info = get_openai_model_info(model)
        elif self.provider == "anthropic":
            model_info = get_anthropic_model_info(model)
        elif self.provider == "google":
            model_info = get_google_model_info(model)
        elif self.provider == "perplexity":
            model_info = get_perplexity_model_info(model)
        else:
            model_info = {"api_name": model, "vision": True, "display_name": model}
        
        self.model = model_info["api_name"]
        self.has_vision = model_info["vision"]
        self.display_name = model_info["display_name"]
        self.model_info = model_info  # Store full model info for schema support check
        
        # Select schema based on agent type
        self.schema = CLI_AGENT_SCHEMA if cli_agent else AGENT_OUTPUT_SCHEMA
        
        self.provider_instance = self._initialize_provider()
        
    def _initialize_provider(self):
        """Initialize the appropriate provider based on selection"""
        if self.provider == "openrouter":
            # Priority: Runtime key > .env fallback
            api_key = self.runtime_api_key or os.getenv('OPENROUTER_API_KEY')
            if not api_key:
                raise ValueError("OpenRouter API key not provided and not found in .env file")
            # Pass schema and model_info for json_schema_support check
            return OpenRouterProvider(api_key, self.thinking, self.cli_agent, self.schema, self.model_info)
        elif self.provider == "groq":
            # Priority: Runtime key > .env fallback
            api_key = self.runtime_api_key or os.getenv('GROQ_API_KEY')
            if not api_key:
                raise ValueError("Groq API key not provided and not found in .env file")
            # Pass schema (Groq uses strict: false for all models)
            return GroqProvider(api_key, self.cli_agent, self.schema, self.model_info)
        elif self.provider == "openai":
            # Priority: Runtime key > .env fallback
            api_key = self.runtime_api_key or os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OpenAI API key not provided and not found in .env file")
            # Pass schema (OpenAI supports strict: true for all models)
            return OpenAIProvider(api_key, self.thinking, self.cli_agent, self.schema)
        elif self.provider == "anthropic":
            # Priority: Runtime key > .env fallback
            api_key = self.runtime_api_key or os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("Anthropic API key not provided and not found in .env file")
            # Pass schema (Anthropic uses output_config.format for structured outputs)
            return AnthropicProvider(api_key, self.cli_agent, self.schema)
        elif self.provider == "google":
            # Check if this is a Vertex model
            from Auto_Use.macOS_use.llm_provider.google.view import get_model_info as get_google_info
            model_meta = get_google_info(self.model_short_name)
            is_vertex = model_meta.get("vertex", False)
            
            if is_vertex:
                # Read Vertex config from api_key.txt
                vertex_project_id = None
                vertex_location = None
                try:
                    from pathlib import Path
                    key_file = Path(__file__).parent.parent / "api_key" / "api_key.txt"
                    if key_file.exists():
                        with open(key_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith('VERTEX_PROJECT_ID='):
                                    vertex_project_id = line.partition('=')[2]
                                elif line.startswith('VERTEX_LOCATION='):
                                    vertex_location = line.partition('=')[2]
                except Exception:
                    pass
                return GoogleProvider(
                    api_key=None, thinking=self.thinking, cli_agent=self.cli_agent,
                    schema=self.schema, model=self.model_short_name,
                    vertex_project_id=vertex_project_id, vertex_location=vertex_location
                )
            else:
                # AI Studio — needs API key
                api_key = self.runtime_api_key or os.getenv('GOOGLE_API_KEY')
                if not api_key:
                    raise ValueError("Google API key not provided and not found in .env file")
                return GoogleProvider(api_key, self.thinking, self.cli_agent, self.schema, model=self.model_short_name)
        elif self.provider == "perplexity":
            api_key = self.runtime_api_key or os.getenv('PERPLEXITY_API_KEY')
            if not api_key:
                raise ValueError("Perplexity API key not provided and not found in .env file")
            return PerplexityProvider(api_key, self.cli_agent, self.schema, self.model_info)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def send_request(self, messages: list, annotated_screenshot_base64: Optional[str] = None):
        """Send request to the selected provider"""
        # Retry up to 3 times with 1 second delay
        for attempt in range(3):
            try:
                response = self.provider_instance.send_request(messages, self.model, annotated_screenshot_base64)
                
                # Extract the assistant's response
                return response['choices'][0]['message']['content']
            except Exception as e:
                if attempt < 2:  # If not the last attempt
                    print(f"⚠️ API request failed (attempt {attempt + 1}/3), retrying in 1 second...")
                    time.sleep(1)
                    continue
                else:
                    # CLI agent: seamless fallback to secondary model (never die)
                    if self.cli_agent and hasattr(self, '_cli_fallback_model') and self._cli_fallback_model:
                        print(f"⚠️ CLI Agent: {self.display_name} failed after 3 attempts. Switching to fallback...")
                        # Resolve fallback model info (same provider, different model)
                        if self.provider == "openrouter":
                            model_info = get_openrouter_model_info(self._cli_fallback_model)
                        elif self.provider == "groq":
                            model_info = get_groq_model_info(self._cli_fallback_model)
                        elif self.provider == "openai":
                            model_info = get_openai_model_info(self._cli_fallback_model)
                        elif self.provider == "anthropic":
                            model_info = get_anthropic_model_info(self._cli_fallback_model)
                        elif self.provider == "google":
                            model_info = get_google_model_info(self._cli_fallback_model)
                        elif self.provider == "perplexity":
                            model_info = get_perplexity_model_info(self._cli_fallback_model)
                        else:
                            raise e
                        # Hot-swap model (provider stays the same, no re-init needed)
                        self.model = model_info["api_name"]
                        self.has_vision = model_info["vision"]
                        self.display_name = model_info["display_name"]
                        self.model_info = model_info
                        # Clear fallback so we don't loop forever
                        self._cli_fallback_model = None
                        print(f"✅ CLI Agent: Now using {self.display_name}")
                        # Retry with fallback (same messages, full history intact)
                        try:
                            response = self.provider_instance.send_request(messages, self.model, annotated_screenshot_base64)
                            return response['choices'][0]['message']['content']
                        except Exception as fallback_e:
                            print(f"❌ CLI Agent: Fallback {self.display_name} also failed: {fallback_e}")
                            raise fallback_e
                    else:
                        raise e
    
    def get_model_name(self) -> str:
        """Get the current model short name (preserves vertex suffix for downstream routing)"""
        return self.model_short_name
    
    def get_provider_name(self) -> str:
        """Get the current provider name"""
        return self.provider