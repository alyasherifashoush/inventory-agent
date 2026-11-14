"""The inventory workflow, built as a LangGraph graph.

Flow:
    START -> check_expiry, check_low_stock, check_slow_movers   (run in parallel)
          -> suggest_discounts   (LLM, structured output)
          -> evaluate_discounts  (Python rules)
          -> back to suggest_discounts if rejected, otherwise:
          -> draft_supplier_emails (LLM writes reorder emails)
          -> human_review          (PAUSES with interrupt() until the manager answers)
          -> apply_decisions       (saves emails + discounts to the outbox folder)
          -> END
"""
import os
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from tools import (
    get_connection,
    get_expiring_products,
    get_low_stock_products,
    get_slow_moving_products,
)

load_dotenv()

MAX_ATTEMPTS = 3  # how many times the LLM may try before we stop looping
OUTBOX = Path(__file__).parent / "outbox"  # where "sent" emails are saved


# ---------- 1. Structured output: the "form" the LLM must fill in ----------

class Discount(BaseModel):
    product: str = Field(description="Exact product name, copied from the data")
    new_price: float = Field(description="Discounted price per unit in EGP")
    reason: str = Field(description="One short sentence explaining why")


class DiscountPlan(BaseModel):
    discounts: list[Discount] = Field(description="One entry per product to discount")


class SupplierEmail(BaseModel):
    supplier: str = Field(description="Supplier name, copied from the data")
    to: str = Field(description="Supplier email address, copied from the data")
    subject: str = Field(description="Short email subject line")
    intro: str = Field(description="One polite sentence introducing the order")
    closing: str = Field(description="One sentence asking the supplier to confirm the delivery date")


class EmailBatch(BaseModel):
    emails: list[SupplierEmail] = Field(description="Exactly one email per supplier")


llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL"), temperature=0)
discount_llm = llm.with_structured_output(DiscountPlan)
email_llm = llm.with_structured_output(EmailBatch)


# ---------- 2. State: the shared data every node reads and updates ----------

class InventoryState(TypedDict, total=False):
    expiring: list[dict]            # from check_expiry
    low_stock: list[dict]           # from check_low_stock (used tomorrow for supplier emails)
    slow_movers: list[dict]         # from check_slow_movers
    proposed_discounts: list[dict]  # what the LLM suggested
    approved_discounts: list[dict]  # what passed the Python rules
    feedback: str                   # why suggestions were rejected ("" = all good)
    attempts: int                   # how many times the LLM has suggested
    reorders: list[dict]            # what to order, quantities calculated in Python
    email_drafts: list[dict]        # emails written by the LLM, not sent yet
    manager_decision: str           # "approve" or "reject", given at human_review
    saved_files: list[str]          # files written to the outbox ("sent")


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
- Round every new_price to the nearest 0.5 EGP.

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


def draft_supplier_emails(state: InventoryState):
    """Python decides WHAT to order; the LLM only writes the emails."""
    reorders = []
    for item in state["low_stock"]:
        # Order enough to reach twice the reorder level.
        quantity = item["reorder_level"] * 2 - item["stock"]
        reorders.append({**item, "order_quantity": quantity})

    if not reorders:
        return {"reorders": [], "email_drafts": []}

    prompt = f"""You write purchase-order emails for a supermarket in Egypt.
Write exactly one email per supplier. Copy the supplier name and email address exactly.
You only write the subject, one intro sentence and one closing sentence:
the product list and the signature are added automatically.

Products to reorder: {reorders}
"""
    batch = email_llm.invoke(prompt)

    # Python builds the layout, so the format and the numbers are always right.
    drafts = []
    for email in batch.emails:
        items = [r for r in reorders if r["supplier_email"] == email.to]
        product_lines = "\n".join(f"- {r['product']}: {r['order_quantity']} units" for r in items)
        body = (
            f"Dear {email.supplier},\n\n"
            f"{email.intro}\n\n"
            f"{product_lines}\n\n"
            f"{email.closing}\n\n"
            f"Best regards,\nStore Manager"
        )
        drafts.append({"supplier": email.supplier, "to": email.to,
                       "subject": email.subject, "body": body})
    return {"reorders": reorders, "email_drafts": drafts}


def human_review(state: InventoryState):
    """Pause the graph and wait for the manager. Needs a checkpointer."""
    decision = interrupt({
        "discounts": state["approved_discounts"],
        "emails": state["email_drafts"],
    })
    # Code below runs only after the manager answers and the graph is resumed.
    return {"manager_decision": decision}


def apply_decisions(state: InventoryState):
    """Simulate sending: save each approved email and the discount list as text files."""
    if state["manager_decision"] != "approve":
        return {"saved_files": []}

    OUTBOX.mkdir(exist_ok=True)
    saved = []
    for email in state["email_drafts"]:
        file_name = email["supplier"].replace(" ", "_").replace(".", "") + ".txt"
        (OUTBOX / file_name).write_text(
            f"To: {email['to']}\nSubject: {email['subject']}\n\n{email['body']}\n",
            encoding="utf-8",
        )
        saved.append(file_name)

    lines = [f"{d['product']}: {d['old_price']} -> {d['new_price']} EGP ({d['reason']})"
             for d in state["approved_discounts"]]
    (OUTBOX / "discounts.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    saved.append("discounts.txt")
    return {"saved_files": saved}


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
builder.add_node("draft_supplier_emails", draft_supplier_emails)
builder.add_node("human_review", human_review)
builder.add_node("apply_decisions", apply_decisions)

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
    {"retry": "suggest_discounts", "done": "draft_supplier_emails"},
)
builder.add_edge("draft_supplier_emails", "human_review")
builder.add_edge("human_review", "apply_decisions")
builder.add_edge("apply_decisions", END)

# The checkpointer saves the state at every step, so the graph can pause at
# human_review and continue later from exactly the same point.
graph = builder.compile(checkpointer=InMemorySaver())
