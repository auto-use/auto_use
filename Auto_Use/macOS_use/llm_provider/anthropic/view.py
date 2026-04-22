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

# Model mappings for Anthropic provider
# Maps user-friendly names to actual API model names

MODEL_MAPPINGS = {
    "claude-haiku-4.5": {
        "api_name": "claude-haiku-4-5-20251001",
        "vision": True,
        "display_name": "Claude Haiku 4.5"
    },
    "claude-opus-4.7": {
        "api_name": "claude-opus-4-7",
        "vision": True,
        "display_name": "Claude Opus 4.7"
    },
    "claude-opus-4.6": {
        "api_name": "claude-opus-4-6",
        "vision": True,
        "display_name": "Claude Opus 4.6"
    },
    "claude-sonnet-4.6": {
        "api_name": "claude-sonnet-4-6",
        "vision": True,
        "display_name": "Claude Sonnet 4.6"
    },
}

def get_model_info(short_name: str) -> dict:
    """Get full model information from short name"""
    if short_name in MODEL_MAPPINGS:
        return MODEL_MAPPINGS[short_name]
    # If not found, assume it's already a full model name
    return {
        "api_name": short_name,
        "vision": True,
        "display_name": short_name
    }