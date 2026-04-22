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

# Model mappings for OpenRouter provider
# Maps user-friendly names to actual API model names

MODEL_MAPPINGS = {
    "gemini-3.1-pro": {
        "api_name": "google/gemini-3.1-pro-preview",
        "vision": True,
        "display_name": "Gemini 3.1 Pro Preview",
        "reasoning_support": True,
        "reasoning_effort": "medium"
    },
    "gemini-3-flash": {
        "api_name": "google/gemini-3-flash-preview",
        "vision": True,
        "display_name": "Gemini 3 Flash Preview",
        "reasoning_support": True,
        "reasoning_effort": "xhigh"
    },
    "gpt-5.4-mini": {
        "api_name": "openai/gpt-5.4-mini",
        "vision": True,
        "display_name": "GPT-5.4 Mini",
        "reasoning_support": True
    },
    "gpt-5.4-pro": {
        "api_name": "openai/gpt-5.4-pro",
        "vision": True,
        "display_name": "GPT-5.4 Pro",
        "reasoning_support": False
    },
    "claude-opus-4.6": {
        "api_name": "anthropic/claude-opus-4.6",
        "vision": True,
        "display_name": "Claude Opus 4.6",
        "reasoning_support": True,
        "reasoning_effort": "low"
    },
    "claude-sonnet-4.6": {
        "api_name": "anthropic/claude-sonnet-4.6",
        "vision": True,
        "display_name": "Claude Sonnet 4.6",
        "reasoning_support": True,
        "reasoning_effort": "low"
    },
    "grok-4-fast": {
        "api_name": "x-ai/grok-4-fast",
        "vision": True,
        "display_name": "Grok 4 Fast",
        "reasoning_support": True,
        "reasoning_effort": "none"
    },
    "grok-4.1-fast": {
        "api_name":"x-ai/grok-4.1-fast",
        "vision": True,
        "display_name": "Grok 4.1 Fast",
        "reasoning_support": True,
        "reasoning_effort": "low"
    },
    "kimi-k2.5": {
        "api_name": "moonshotai/kimi-k2.5",
        "vision": True,
        "display_name": "Kimi K2.5",
        "reasoning_support": False
    }
}

def get_model_info(short_name: str) -> dict:
    """Get full model information from short name"""
    if short_name in MODEL_MAPPINGS:
        return MODEL_MAPPINGS[short_name]
    # If not found, assume it's already a full model name
    return {
        "api_name": short_name,
        "vision": True,
        "display_name": short_name,
        "reasoning_support": False
    }