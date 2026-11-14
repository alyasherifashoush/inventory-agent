"""Test the evaluator on its own, with deliberately bad suggestions (no LLM involved)."""
from workflow import evaluate_discounts

fake_state = {
    "proposed_discounts": [
        {"product": "Pasta 500g", "new_price": 22, "reason": "slow mover"},       # OK
        {"product": "Pasta 500g", "new_price": 17, "reason": "too cheap"},        # below cost (18)
        {"product": "Tomatoes 1kg", "new_price": 25, "reason": "price went up"},  # not a discount (20)
        {"product": "Milk", "new_price": 30, "reason": "wrong name"},             # not an exact name
    ]
}

result = evaluate_discounts(fake_state)

print("APPROVED:")
for d in result["approved_discounts"]:
    print("  ", d["product"], d["new_price"])
print("\nFEEDBACK the LLM would receive:")
print(result["feedback"])