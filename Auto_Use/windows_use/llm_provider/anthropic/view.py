# Model mappings for Anthropic provider
# Maps user-friendly names to actual API model names

MODEL_MAPPINGS = {
    "claude-haiku-4.5": {
        "api_name": "claude-haiku-4-5-20251001",
        "vision": True,
        "display_name": "Claude Haiku 4.5"
    },
    "claude-sonnet-4.5": {
        "api_name": "claude-sonnet-4-5-20250929",
        "vision": True,
        "display_name": "Claude Sonnet 4.5"
    },
    "claude-opus-4.5": {
        "api_name": "claude-opus-4-5-20251101",
        "vision": True,
        "display_name": "Claude Opus 4.5"
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