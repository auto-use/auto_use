import os
import requests
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, api_key=None):
    """
    Perform web search using Perplexity Sonar via Agent API

    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        key = api_key or os.getenv('PERPLEXITY_API_KEY')

        response = requests.post(
            "https://api.perplexity.ai/v1/agent",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "perplexity/sonar",
                "instructions": system_prompt,
                "input": query,
                "tools": [{"type": "web_search"}],
                "max_output_tokens": 4096,
            }
        )
        response.raise_for_status()
        result = response.json()

        # Extract text from Agent API response
        for output_item in result.get("output", []):
            if output_item.get("type") == "message":
                for block in output_item.get("content", []):
                    if block.get("type") == "output_text":
                        return block.get("text", "")

        return str(result)
    except Exception as e:
        raise Exception(f"Error in web search: {str(e)}")


if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))