#this main.py give terminal interface to the user to interact with the agent for ui refer app.py
import platform

if platform.system() == "Darwin":
    from Auto_Use.macOS_use.agent.service import AgentService
elif platform.system() == "Windows":
    from Auto_Use.windows_use.agent.service import AgentService
else:
    raise RuntimeError(f"Unsupported OS: {platform.system()}")

# Configuration
PROVIDER = "perplexity"
MODEL = "gemini-3-flash" #refer to the model name correctly from the view.py from llm provider folder.
# Your task here
task = """

write hello in milestone

"""

# Control conversation saving
conversation = False  # Set to False to disable conversation.txt
# Control thinking/reasoning
thinking = True  # Set to True to enable reasoning for supported models

# Run the agent
agent = AgentService(provider=PROVIDER, model=MODEL, save_conversation=conversation)
agent.process_request(task)

# Response is displayed inside process_request