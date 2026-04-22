# Model mappings for Perplexity provider
# Maps user-friendly names to actual Perplexity Agent API model names

MODEL_MAPPINGS = {
    "gpt-5.4": {
        "api_name": "openai/gpt-5.4",
        "vision": True,
        "display_name": "GPT-5.4",
        "reasoning_support": True,
        "reasoning_effort": "medium"
    },
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
        "reasoning_effort": "medium"
    },
    "claude-sonnet-4.6": {
        "api_name": "anthropic/claude-sonnet-4-6",
        "vision": True,
        "display_name": "Claude Sonnet 4.6",
        "reasoning_support": True,
        "reasoning_effort": "medium"
    },
    "claude-opus-4.6": {
        "api_name": "anthropic/claude-opus-4-6",
        "vision": True,
        "display_name": "Claude Opus 4.6",
        "reasoning_support": True,
        "reasoning_effort": "medium"
    },
    "sonar": {
        "api_name": "perplexity/sonar",
        "vision": False,
        "display_name": "Perplexity Sonar",
        "reasoning_support": False
    },
}

def get_model_info(short_name: str) -> dict:
    """Get full model information from short name"""
    if short_name in MODEL_MAPPINGS:
        return MODEL_MAPPINGS[short_name]
    return {
        "api_name": short_name,
        "vision": True,
        "display_name": short_name,
        "reasoning_support": False
    }