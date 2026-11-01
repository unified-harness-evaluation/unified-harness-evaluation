"""Summarize Q3 sales data from ../data/sales_q3.csv."""
import csv
from collections import defaultdict

DATA_FILE = "../data/sales_q3.csv"

total_revenue = 0.0
deals_by_region = defaultdict(int)
revenue_by_region = defaultdict(float)
won = lost = pending = 0

with open(DATA_FILE, newline="") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        amount = float(row["amount"])
        region = row["region"]
        status = row["status"]
        deals_by_region[region] += 1
        if status == "won":
            total_revenue += amount
            revenue_by_region[region] += amount
            won += 1
        elif status == "lost":
            lost += 1
        else:
            pending += 1

total_deals = won + lost + pending
win_rate = won / total_deals * 100 if total_deals else 0

print("=" * 45)
print("  Meridian Analytics — Q3 Sales Summary")
print("=" * 45)
print(f"  Total deals worked : {total_deals}")
print(f"  Won                : {won}")
print(f"  Lost               : {lost}")
print(f"  Pending            : {pending}")
print(f"  Win rate           : {win_rate:.1f}%")
print(f"  Total revenue (won): ${total_revenue:,.0f}")
print()
print("  Revenue by region (won deals):")
for region, rev in sorted(revenue_by_region.items(), key=lambda x: -x[1]):
    count = sum(1 for r in open(DATA_FILE).readlines()[1:]
                if r.split(",")[2] == region and r.strip().endswith("won"))
    print(f"    {region:<8} ${rev:>10,.0f}  ({deals_by_region[region]} deals total)")
print("=" * 45)
