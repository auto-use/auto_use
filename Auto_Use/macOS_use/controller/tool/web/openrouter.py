import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

# Get the directory where this file is located
current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, model, api_key=None):
    """
    Perform web search using OpenRouter with dynamic model
    
    Args:
        query: Search query
        model: Full OpenRouter model name (e.g., "google/gemini-2.5-flash")
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        # Priority: frontend key > .env fallback
        key = api_key or os.getenv('OPENROUTER_API_KEY')
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "plugins": [{"id": "web", "engine": "exa", "max_results": 20}]
            }
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        raise Exception(f"Error in web search: {str(e)}")


if __name__ == "__main__":
    # For testing purposes, require model as second argument
    if len(sys.argv) < 2:
        print("Usage: python openrouter.py <model_name>")
        print("Example: python openrouter.py google/gemini-2.5-flash")
        sys.exit(1)
    model = sys.argv[1]
    query = input("Search: ")
    print(web_search(query, model))
