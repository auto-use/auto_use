import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

current_dir = os.path.dirname(os.path.abspath(__file__))
web_md_path = os.path.join(current_dir, "web.md")

with open(web_md_path, "r") as f:
    system_prompt = f.read()


def web_search(query, api_key=None):
    """
    Perform web search using Anthropic Claude Haiku 4.5 with native web_search tool

    Args:
        query: Search query
        api_key: Runtime API key from frontend (priority over .env)
    """
    try:
        key = api_key or os.getenv('ANTHROPIC_API_KEY')

        client = anthropic.Anthropic(api_key=key)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": query}
            ],
            tools=[
                {"type": "web_search_20250305", "name": "web_search"}
            ],
        )

        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        return "\n".join(text_parts) if text_parts else str(response)
    except Exception as e:
        return f"Error in web search: {str(e)}"


if __name__ == "__main__":
    query = input("Search: ")
    print(web_search(query))
