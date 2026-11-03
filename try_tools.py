from tools import get_expiring_products, get_low_stock_products, get_slow_moving_products

print("EXPIRING (3 days):")
for row in get_expiring_products.invoke({"days": 3}):
    print("  ", row)

print("\nLOW STOCK:")
for row in get_low_stock_products.invoke({}):
    print("  ", row)

print("\nSLOW MOVERS:")
for row in get_slow_moving_products.invoke({}):
    print("  ", row)