"""The inventory workflow, built as a LangGraph graph.

Flow:
    START -> check_expiry, check_low_stock, check_slow_movers   (run in parallel)
          -> suggest_discounts   (LLM, structured output)
          -> evaluate_discounts  (Python rules)
          -> back to suggest_discounts if rejected, otherwise END
"""
import os
from typing import TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from tools import (
    get_connection,
    get_expiring_products,
    get_low_stock_products,
    get_slow_moving_products,
)

load_dotenv()

MAX_ATTEMPTS = 3  # how many times the LLM may try before we stop looping


# ---------- 1. Structured output: the "form" the LLM must fill in ----------

class Discount(BaseModel):
    product: str = Field(description="Exact product name, copied from the data")
    new_price: float = Field(description="Discounted price per unit in EGP")
    reason: str = Field(description="One short sentence explaining why")


class DiscountPlan(BaseModel):
    discounts: list[Discount] = Field(description="One entry per product to discount")


llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL"), temperature=0)
discount_llm = llm.with_structured_output(DiscountPlan)


# ---------- 2. State: the shared data every node reads and updates ----------

class InventoryState(TypedDict, total=False):
    expiring: list[dict]            # from check_expiry
    low_stock: list[dict]           # from check_low_stock (used tomorrow for supplier emails)
    slow_movers: list[dict]         # from check_slow_movers
    proposed_discounts: list[dict]  # what the LLM suggested
    approved_discounts: list[dict]  # what passed the Python rules
    feedback: str                   # why suggestions were rejected ("" = all good)
    attempts: int                   # how many times the LLM has suggested


# ---------- 3. Nodes: one function per step ----------

def check_expiry(state: InventoryState):
    return {"expiring": get_expiring_products.invoke({"days": 3})}


def check_low_stock(state: InventoryState):
    return {"low_stock": get_low_stock_products.invoke({})}


def check_slow_movers(state: InventoryState):
    return {"slow_movers": get_slow_moving_products.invoke({})}


def suggest_discounts(state: InventoryState):
    """Generator: the LLM proposes discounts."""
    prompt = f"""You are the pricing assistant of a supermarket. Prices are in EGP.
Suggest discounts for:
1. Batches expiring soon (days_left from 0 to 3). Do NOT discount batches with a
   negative days_left: they have already expired and must be thrown away.
2. Slow-moving products.

Rules:
- Copy each product name exactly as it is written in the data.
- new_price must be lower than unit_price and never below unit_cost.
- The closer the expiry date, the bigger the discount.
- At most one entry per product.

Expiring batches: {state["expiring"]}
Slow movers: {state["slow_movers"]}
"""
    if state.get("feedback"):
        prompt += f"\nYour previous suggestion was rejected. Fix these problems:\n{state['feedback']}\n"

    plan = discount_llm.invoke(prompt)
    return {
        "proposed_discounts": [d.model_dump() for d in plan.discounts],
        "attempts": state.get("attempts", 0) + 1,
    }


def evaluate_discounts(state: InventoryState):
    """Evaluator: plain Python checks every suggestion against the database."""
    approved, problems = [], []
    with get_connection() as conn:
        for d in state["proposed_discounts"]:
            row = conn.execute(
                "SELECT unit_cost, unit_price FROM products WHERE name = ?",
                (d["product"],),
            ).fetchone()

            if row is None:
                problems.append(f"'{d['product']}' is not an exact product name.")
            elif d["new_price"] < row["unit_cost"]:
                problems.append(
                    f"{d['product']}: {d['new_price']} EGP is below the unit cost "
                    f"of {row['unit_cost']} EGP."
                )
            elif d["new_price"] >= row["unit_price"]:
                problems.append(
                    f"{d['product']}: {d['new_price']} EGP is not lower than the "
                    f"current price of {row['unit_price']} EGP."
                )
            else:
                approved.append({**d, "old_price": row["unit_price"], "unit_cost": row["unit_cost"]})

    return {"approved_discounts": approved, "feedback": "\n".join(problems)}


# ---------- 4. Routing: decide where to go after the evaluator ----------

def route_after_evaluation(state: InventoryState):
    if state["feedback"] and state["attempts"] < MAX_ATTEMPTS:
        return "retry"
    return "done"


# ---------- 5. Build the graph ----------

builder = StateGraph(InventoryState)

builder.add_node("check_expiry", check_expiry)
builder.add_node("check_low_stock", check_low_stock)
builder.add_node("check_slow_movers", check_slow_movers)
builder.add_node("suggest_discounts", suggest_discounts)
builder.add_node("evaluate_discounts", evaluate_discounts)

# Parallel: all three checks start at the same time...
builder.add_edge(START, "check_expiry")
builder.add_edge(START, "check_low_stock")
builder.add_edge(START, "check_slow_movers")
# ...and suggest_discounts waits until all three are finished.
builder.add_edge("check_expiry", "suggest_discounts")
builder.add_edge("check_low_stock", "suggest_discounts")
builder.add_edge("check_slow_movers", "suggest_discounts")

builder.add_edge("suggest_discounts", "evaluate_discounts")
builder.add_conditional_edges(
    "evaluate_discounts",
    route_after_evaluation,
    {"retry": "suggest_discounts", "done": END},
)

graph = builder.compile()