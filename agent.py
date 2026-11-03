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
    config = {"configurable": {"thread_id": "manager-1"}}
    print("Inventory assistant ready. Type 'quit' to exit.\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in ("quit", "exit"):
            break
        if not question:
            continue

        before = len(agent.get_state(config).values.get("messages", []))
        result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config)
        new_messages = result["messages"][before:]

        show_tool_calls(new_messages)
        print(f"Agent: {result['messages'][-1].text}\n")


if __name__ == "__main__":
    main()