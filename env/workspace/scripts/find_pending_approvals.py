"""Print unapproved Q3 expenses grouped by employee ID."""
import json

EXPENSES_FILE = "../data/expenses_q3.json"
EMPLOYEES_FILE = "../data/employees.json"

with open(EXPENSES_FILE) as fh:
    expenses = json.load(fh)

with open(EMPLOYEES_FILE) as fh:
    employees = json.load(fh)

id_to_name = {e["id"]: e["name"] for e in employees}

# Group unapproved by employee
pending = {}
for exp in expenses:
    if not exp["approved"]:
        eid = exp["employee_id"]
        pending.setdefault(eid, []).append(exp)

if not pending:
    print("No unapproved expenses found.")
else:
    print("=" * 55)
    print("  Meridian Analytics — Unapproved Expenses (Q3)")
    print("=" * 55)
    total = 0.0
    for eid, exps in sorted(pending.items()):
        name = id_to_name.get(eid, eid)
        subtotal = sum(e["amount"] for e in exps)
        total += subtotal
        print(f"\n  {name} ({eid})  — subtotal: ${subtotal:.2f}")
        for e in exps:
            print(f"    [{e['expense_id']}] {e['date']}  ${e['amount']:>7.2f}  {e['category']:<10}  {e['description']}")
    print()
    print(f"  Total unapproved: ${total:.2f}")
    print("=" * 55)
