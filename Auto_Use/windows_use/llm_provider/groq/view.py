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

# Model mappings for Groq provider
# Maps user-friendly names to actual API model names

MODEL_MAPPINGS = {
    "gpt-oss-120b": {
        "api_name": "openai/gpt-oss-120b",
        "vision": False,
        "display_name": "GPT-OSS 120B",
        "reasoning_support": True,
        "reasoning_effort": "medium",
        "hidden": True
    },
    "llama-4-scout": {
        "api_name": "meta-llama/llama-4-scout-17b-16e-instruct",
        "vision": True,
        "display_name": "Llama 4 Scout 17B"
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
        "display_name": short_name
    }