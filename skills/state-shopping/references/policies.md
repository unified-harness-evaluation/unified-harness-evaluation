# Online shopping assistant — Policies

Full policy reference for this domain. The agent can also fetch any topic at
runtime via the `get_policies` tool. Topics below are the canonical set.

## welcome_discount

```json
{
  "topic": "welcome_discount",
  "summary": "First-time customers receive an automatic 5% welcome discount on their first order.",
  "rules": [
    "Eligibility: customer.is_first_time is True (empty purchase history).",
    "Application: applied automatically at checkout, not via promo code.",
    "Stacking: not combinable with promo codes. Customer gets the better of the two.",
    "One-time: returning customers are not eligible."
  ]
}
```

## loyalty_points

```json
{
  "topic": "loyalty_points",
  "summary": "Loyalty points are earned on every purchase. Rate depends on membership tier.",
  "rules": [
    "Platinum: 3 points per dollar spent.",
    "Gold: 2 points per dollar spent.",
    "Standard: 1 point per dollar spent.",
    "Calculation: applied to the final total after all discounts.",
    "Disclosure: agents should mention points earned after any cart completion."
  ]
}
```

## gift_wrap

```json
{
  "topic": "gift_wrap",
  "summary": "Gift wrapping is a $5 per-item add-on available on any product.",
  "rules": [
    "Fee: $5 per wrapped item.",
    "Availability: available on all products unless product.gift_wrap_available is False.",
    "Modification: can be toggled per cart item via update_cart_item."
  ]
}
```

## quantity_limit

```json
{
  "topic": "quantity_limit",
  "summary": "Anti-hoarding: maximum 3 units of the same product per cart.",
  "rules": [
    "Limit: 3 units of the same product per cart.",
    "Enforcement: applies to total quantity in cart (existing + new).",
    "No exceptions regardless of tier, promo, or reason."
  ]
}
```

## brand_bundle

```json
{
  "topic": "brand_bundle",
  "summary": "Buying 2+ items of the same brand qualifies for a 3% bonus discount on those items.",
  "rules": [
    "Eligibility: 2+ items sharing the same brand.",
    "Discount: 3% off each qualifying item's line total.",
    "Stacking: stacks with category bundle and promo codes.",
    "Informational: agent surfaces this to the customer; the cart does not auto-apply it."
  ]
}
```

## category_bundle

```json
{
  "topic": "category_bundle",
  "summary": "Buying 3+ items from the same category qualifies for a 5% bundle discount on those items.",
  "rules": [
    "Eligibility: 3+ items sharing the same category.",
    "Discount: 5% off each qualifying item's line total.",
    "Stacking: does NOT stack with promo codes on the same items. Customer gets the better of the two."
  ]
}
```

## backorder

```json
{
  "topic": "backorder",
  "summary": "Out-of-stock items flagged backorder_available can be reserved with a 10% deposit.",
  "rules": [
    "Eligibility: product.in_stock is False AND product.backorder_available is True.",
    "Deposit: 10% of the product price, refundable if restock fails.",
    "Timeline: estimated 2–4 weeks to restock.",
    "Proactive: when a requested product is OOS, agent should check and offer backorder if available."
  ]
}
```

## price_alerts

```json
{
  "topic": "price_alerts",
  "summary": "Products with previous_price higher than current price recently went on sale.",
  "rules": [
    "Detection: product.previous_price > product.price.",
    "Disclosure: agent should proactively mention price drops when recommending or showing details."
  ]
}
```

## promo_stacking

```json
{
  "topic": "promo_stacking",
  "summary": "At most one promo code per cart. Some discounts stack with each other but not with promo codes.",
  "rules": [
    "One promo code per cart.",
    "Category bundle (5%) does NOT stack with promo codes on the same items — customer gets the better of the two.",
    "Welcome discount (5%) does NOT stack with promo codes — customer gets the better of the two.",
    "Brand bundle bonus (3%) DOES stack with everything."
  ]
}
```

## shipping

```json
{
  "topic": "shipping",
  "summary": "Shipping speed depends on customer preference and tier. Three options: standard, express, next_day.",
  "rules": [
    "Standard: listed shipping_days, $6 fee.",
    "Express: -1 day vs standard, $12 fee. Free for Gold and Platinum.",
    "Next-day: next business day, $15 fee. Free for Platinum.",
    "Bundle override: 5+ items total grants free standard shipping regardless of tier.",
    "Agent action rule: do NOT call set_shipping_option without an explicit customer choice. You may discuss options in chat when the customer asks about shipping/delivery/deadlines, but the write call must come AFTER the customer names a specific option."
  ]
}
```

## returns

```json
{
  "topic": "returns",
  "summary": "30-day return window from delivery. Items must be in original condition.",
  "rules": [
    "Window: 30 days from delivery date.",
    "Condition: unused, with original packaging.",
    "Refund: to original payment method within 5 business days of return receipt.",
    "Exclusions: final-sale items and digital goods are not returnable."
  ]
}
```

## price_match

```json
{
  "topic": "price_match",
  "summary": "One-time price adjustment within 7 days of purchase if the same item goes on sale.",
  "rules": [
    "Window: 7 days from order date.",
    "Scope: same SKU, not similar items.",
    "Refund: difference is credited to original payment method.",
    "Exclusions: third-party promo codes, flash sales shorter than 24 hours."
  ]
}
```

## loyalty_redemption

```json
{
  "topic": "loyalty_redemption",
  "summary": "Loyalty points can be redeemed at checkout to offset part of the cart total. 100 points = $1.",
  "rules": [
    "Rate: 100 loyalty points = $1.00 off.",
    "Cap: redemption cannot exceed 50% of the current cart total.",
    "Minimum redemption: 500 points ($5).",
    "Stacking: stacks with promo codes and category bundles.",
    "Restriction: not combinable with the first-time welcome discount.",
    "Points are debited from the customer's balance at redemption.",
    "Agent action rule: do NOT call redeem_loyalty_points without an explicit customer-specified amount. You may discuss and recommend redemption in chat, but the write call must come AFTER the customer names a specific number of points."
  ]
}
```
