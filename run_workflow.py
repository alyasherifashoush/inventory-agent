"""Run the inventory workflow, pause for the manager's approval, then finish.

Run from the project root:  python run_workflow.py
"""
from langgraph.types import Command

from workflow import graph

# A thread_id is required because the graph has a checkpointer:
# it is the "save file" the paused graph is stored under.
config = {"configurable": {"thread_id": "daily-run"}}


def run(graph_input):
    """Run (or resume) the graph, print each step, and return the interrupt if it paused."""
    paused_with = None
    for step in graph.stream(graph_input, config, stream_mode="updates"):
        for node, update in step.items():
            if node == "__interrupt__":          # the graph paused at human_review
                paused_with = update[0].value
                continue

            print(f"\n=== {node} ===")
            if node == "check_expiry":
                print(f"   {len(update['expiring'])} batches expired or expiring within 3 days")
            elif node == "check_low_stock":
                print(f"   {len(update['low_stock'])} products below reorder level")
            elif node == "check_slow_movers":
                print(f"   {len(update['slow_movers'])} slow-moving products")
            elif node == "suggest_discounts":
                print(f"   Attempt {update['attempts']}: LLM proposed "
                      f"{len(update['proposed_discounts'])} discounts")
            elif node == "evaluate_discounts":
                print("   REJECTED:\n     " + update["feedback"].replace("\n", "\n     ")
                      if update["feedback"] else "   All suggestions passed the rules.")
            elif node == "draft_supplier_emails":
                print(f"   {len(update['email_drafts'])} supplier emails drafted")
            elif node == "human_review":
                print(f"   Manager decision: {update['manager_decision']}")
            elif node == "apply_decisions":
                if update["saved_files"]:
                    print(f"   Saved to the outbox folder: {', '.join(update['saved_files'])}")
                else:
                    print("   Rejected by the manager: nothing was sent.")
    return paused_with


# 1. Run until the graph pauses for approval.
review = run({})

# 2. Show the manager what needs approval.
print("\n" + "=" * 60)
print("MANAGER REVIEW")
print("=" * 60)
print("\nDiscounts:")
for d in review["discounts"]:
    print(f"   {d['product']}: {d['old_price']} -> {d['new_price']} EGP  ({d['reason']})")
for email in review["emails"]:
    print(f"\n--- Email to {email['supplier']} <{email['to']}> ---")
    print(f"Subject: {email['subject']}\n")
    print(email["body"])

answer = input("\nApprove and send? (yes/no): ").strip().lower()
decision = "approve" if answer in ("y", "yes") else "reject"

# 3. Resume the paused graph with the manager's answer.
run(Command(resume=decision))
print("\nWorkflow finished.")
