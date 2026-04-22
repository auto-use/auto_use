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