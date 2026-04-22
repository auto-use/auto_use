# Model mappings for Google provider
# Maps user-friendly names to actual API model names

MODEL_MAPPINGS = {
    "gemini-3.1-pro": {
        "api_name": "gemini-3.1-pro-preview",
        "vision": True,
        "display_name": "Gemini 3.1 Pro",
        "reasoning_support": True,
        "vertex": False
    },
    "gemini-3-flash": {
        "api_name": "gemini-3-flash-preview",
        "vision": True,
        "display_name": "Gemini 3 Flash",
        "reasoning_support": True,
        "vertex": False
    },
    "gemini-3.1-pro-vertex": {
        "api_name": "gemini-3.1-pro-preview",
        "vision": True,
        "display_name": "Gemini 3.1 Pro (Vertex)",
        "reasoning_support": True,
        "vertex": True
    },
    "gemini-3-flash-vertex": {
        "api_name": "gemini-3-flash-preview",
        "vision": True,
        "display_name": "Gemini 3 Flash (Vertex)",
        "reasoning_support": True,
        "vertex": True
    }
}

def get_model_info(short_name: str) -> dict:
    """Get full model information from short name"""
    if short_name in MODEL_MAPPINGS:
        return MODEL_MAPPINGS[short_name]
    return {
        "api_name": short_name,
        "vision": True,
        "display_name": short_name,
        "reasoning_support": True
    }