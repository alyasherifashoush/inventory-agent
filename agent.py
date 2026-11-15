"""Decision-support chat agent: ask questions about the store's inventory.

Run from the project root:  python agent.py
Type 'quit' to exit.
"""
import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver

from tools import ALL_TOOLS

load_dotenv()

SYSTEM_PROMPT = """You are an inventory assistant for a small supermarket in Egypt.
You help the store manager make decisions about stock, expiry, discounts and reordering.

Rules:
- Always use the tools to get real data. Never invent products, numbers or dates.
- Prices are in EGP.
- Never suggest a discounted price below the product's unit_cost.
- Be concise: lead with the answer, then the key numbers.
- If a tool has default values, use them instead of asking the manager for parameters.
"""

llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL"), temperature=0)

# Agent = model (brain) + tools (hands) + system prompt (rules) + checkpointer (memory).
# create_agent builds a small LangGraph graph: model -> tools -> model, looping until
# the model answers with text instead of a tool call.
agent = create_agent(
    model=llm,
    tools=ALL_TOOLS,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver(),  # short-term memory: remembers this conversation
)


def show_tool_calls(messages):
    """Print which tools the agent called during this turn (to see the agent loop)."""
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            print(f"   [tool] {call['name']}({call['args']})")


def main():
    # thread_id = the name of the saved conversation. Same id = same memory;
    # a different id starts a fresh conversation.
    config = {"configurable": {"thread_id": "manager-1"}}
    print("Inventory assistant ready. Type 'quit' to exit.\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in ("quit", "exit"):
            break
        if not question: #If you pressed Enter without typing anything, question is an empty string, which counts as false. continue jumps back to the top of the loop, so no empty message is sent to Gemini.
            continue

        # Count the saved messages before this question, so we can print only this turn's tool calls
        before = len(agent.get_state(config).values.get("messages", []))

        # Send only the new question; the checkpointer adds the saved history automatically.
        # Inside, the agent loop runs: tool calls -> tool results -> final answer.
        result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config)
        
        # Slice: keep only the messages created during this question
        new_messages = result["messages"][before:]

        show_tool_calls(new_messages)
        print(f"Agent: {result['messages'][-1].text}\n")


if __name__ == "__main__":
    main()