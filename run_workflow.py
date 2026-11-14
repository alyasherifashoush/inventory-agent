"""Run the inventory workflow and print what each node does, step by step.

Run from the project root:  python run_workflow.py
"""
from workflow import graph

final = {}

# stream() runs the graph like invoke(), but hands us each node's update as it finishes.
for step in graph.stream({}, stream_mode="updates"):
    for node, update in step.items():
        final.update(update)
        print(f"\n=== {node} ===")

        if node == "check_expiry":
            print(f"   {len(update['expiring'])} batches expired or expiring within 3 days")
        elif node == "check_low_stock":
            print(f"   {len(update['low_stock'])} products below reorder level")
        elif node == "check_slow_movers":
            print(f"   {len(update['slow_movers'])} slow-moving products")
        elif node == "suggest_discounts":
            print(f"   Attempt {update['attempts']}: LLM proposed:")
            for d in update["proposed_discounts"]:
                print(f"     - {d['product']}: {d['new_price']} EGP ({d['reason']})")
        elif node == "evaluate_discounts":
            if update["feedback"]:
                print("   REJECTED:")
                print("     " + update["feedback"].replace("\n", "\n     "))
            else:
                print("   All suggestions passed the rules.")

print("\n=== FINAL APPROVED DISCOUNTS ===")
for d in final.get("approved_discounts", []):
    off = round((1 - d["new_price"] / d["old_price"]) * 100)
    print(f"   {d['product']}: {d['old_price']} -> {d['new_price']} EGP "
          f"({off}% off, cost {d['unit_cost']})")