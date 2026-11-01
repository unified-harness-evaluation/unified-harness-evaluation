# E-commerce customer support — Policies

Full policy reference for this domain. The agent can also fetch any topic at
runtime via the `get_policies` tool. Topics below are the canonical set.

## return

```json
{
  "topic": "return",
  "rules": {
    "agent_computes_amount": "process_return requires the agent to submit the net refund as `amount` on confirm. Compute it from the preview's component breakdown: base_item_price (after promo redistribution) minus restocking_fee plus restocking_discount minus shipping_clawback minus bulk_clawback minus repeat_surcharge minus paid_return_shipping_fee. The env writes the submitted amount verbatim — skipping a component (e.g. forgetting the Gold restocking discount) produces a wrong refund_amount and fails state scoring.",
    "windows_by_category": {
      "electronics": "15-day return window",
      "clothing": "30-day return window",
      "kitchen": "30-day return window",
      "books": "14-day return window",
      "accessories": "30-day return window"
    },
    "window_extensions": {
      "membership": "Gold/Platinum members get +15 days",
      "prime": "Prime shipping members get +15 additional days",
      "seasonal": "Orders placed in November or December extend through January 31 of the following year. Seasonal extension applies if it gives more time than tier/prime extensions.",
      "store_credit_grace": "Up to 15 days past the return window: store credit only."
    },
    "eligibility": {
      "defective_items": "No window restriction for defective, wrong item, or damaged in transit.",
      "already_returned": "Items already returned/exchanged/cancelled are ineligible.",
      "not_as_described": "Use not_as_described only for an unused/unworn item that materially differs from the listing. If the customer wore, washed, altered, or used the item and only dislikes fit, feel, texture, or preference-based qualities, classify the return as changed_mind instead."
    },
    "restocking_fee": {
      "base": "15% restocking fee for opened electronics returned for changed_mind.",
      "tier_discount": {
        "platinum": "Restocking fee fully waived.",
        "gold": "50% off the restocking fee.",
        "silver": "25% off the restocking fee.",
        "standard": "No discount."
      },
      "auto_applied": "Restocking fee and any tier discount are folded into the process_return refund amount automatically; the result reports the discount under 'restocking_discount' for transparency.",
      "completed_returns": "Once a changed-mind return is completed with the applicable restocking fee, do not reverse that fee later as a courtesy or supplemental refund."
    },
    "return_shipping_fee": {
      "low_value": "Orders with subtotal < $50: customer pays $8 return shipping fee.",
      "free_threshold": "Orders >= $50: free return label provided.",
      "fault_exempt": "Defective, wrong item, or damaged in transit: always free return shipping.",
      "deduction": "Return shipping fee, when charged, is deducted from the return refund."
    },
    "bulk_purchase_clawback": {
      "applies_when": "Order originally qualified for a bulk discount (3+ items with a discount code) AND the return drops remaining count below 3.",
      "amount": "$5 per remaining item, deducted from the return refund.",
      "no_discount_code": "If order had no discount code, no clawback applies."
    },
    "free_shipping_clawback": {
      "applies_when": "Order originally qualified for free shipping (subtotal >= $100) AND the return drops remaining subtotal below $100.",
      "amount": "$8 standard shipping fee is deducted from the return refund. This is a flat policy charge, not the original shipping cost (which was $0 on free-shipping orders).",
      "fault_exempt": "Defective, wrong item, or damaged in transit: no clawback (customer-fault returns only).",
      "paid_shipping": "If the order did not qualify for free shipping originally (subtotal < $100), no clawback applies."
    },
    "repeat_category_surcharge": {
      "rule": "Returning 2+ items from the same product category in one order: $5 surcharge per additional return (first return in each category is free).",
      "different_categories": "Returns from different categories do not trigger the surcharge.",
      "deduction": "Surcharge is deducted from the return refund."
    }
  }
}
```

## refund

```json
{
  "topic": "refund",
  "rules": {
    "amount": {
      "full_refund": "Full refund for defective, wrong item, or damaged in transit.",
      "promo_redistribution": "If a promo/coupon was used: discount allocated proportionally by item price. Refund = item_price - (discount * item_price / subtotal).",
      "outside_window": "Outside return window but within store-credit grace: store credit only.",
      "shipping_refund": "When refunding shipping (defective/wrong/damaged returns, 6+-days-late compensation), refund the actual shipping cost the customer was charged on the order — read order.shipping_cost and refund that amount. Standard policy: $0 on free-shipping orders (subtotal >= $100), $8 otherwise. NOT for buyer's remorse."
    },
    "method": {
      "original_payment": "Default refund method when item was paid for and is being returned for fault.",
      "store_credit": "Required for: gift returns (at current product price), outside-window grace returns, and exchange-cheaper differences.",
      "store_credit_only_constraint": "When a return is issued under the store-credit-only rule (gift return OR outside-window grace), the refund method cannot be changed back to original_payment afterward. process_refund will reject any attempt to flip the method on those returns."
    },
    "price_match": "If product price drops within 7 days of delivery, refund the difference (no return required).",
    "goodwill_credit": "Goodwill credits (e.g., fragile-item damage bonus) are issued as a refund with the credit amount."
  }
}
```

## cancellation

```json
{
  "topic": "cancellation",
  "rules": {
    "pre_shipment": "Free cancellation before shipment (pending/processing status).",
    "in_transit": "$10 intercept fee per item for in-transit orders.",
    "delivered": "Cannot cancel delivered orders — must use the return process instead.",
    "partial": "Partial cancellation allowed if items not yet delivered.",
    "split_payment": "Refund distributed proportionally to original payment methods.",
    "already_cancelled": "Already cancelled orders cannot be cancelled again."
  }
}
```

## exchange

```json
{
  "topic": "exchange",
  "rules": {
    "must_be_different_product": "Exchanges must specify a different product than the original item. Self-swap (exchanging an item for the same product) is not allowed — use process_return for a refund instead.",
    "same_price": "Exchange for a same-price product: no charge, no refund.",
    "more_expensive": "Exchange for more expensive item: customer pays price difference.",
    "cheaper": "Exchange for cheaper item: difference refunded as store credit (not original payment).",
    "out_of_stock": "If requested item is out of stock: issue store credit for the original item; do not complete the exchange.",
    "return_window": "Must be within return window (same rules as returns).",
    "no_price_protection": "No price protection on exchanges (item price at time of purchase applies)."
  }
}
```

## warranty

```json
{
  "topic": "warranty",
  "rules": {
    "active": "Active warranty: eligible for claim.",
    "active_item_required": "Warranty claims require an active order item. Items already returned, exchanged, or cancelled are ineligible for a new warranty claim even if a warranty record still exists.",
    "expired_recent": "Expired <30 days: 50% off repair.",
    "expired_old": "Expired >30 days: full-price repair or 25% off replacement.",
    "claim_limit": "Max claims reached: paid repair only (40% of item price).",
    "repair_vs_replace": "Items <$100: replacement. Items >=$100: repair first.",
    "recurring_defect": "2+ prior claims for same issue: automatic replacement.",
    "manufacturer": "Manufacturer warranty covers first 12 months.",
    "extended": "Extended warranty covers after manufacturer period.",
    "void_exclusions": "Liquid, accidental, or user-caused physical damage (e.g. spills, drops, cracked screens from misuse) is NOT covered and voids the claim, even while the warranty is otherwise active. The eligibility check is date/claim-count based only and does not detect damage cause, so when the customer describes liquid/accidental/user damage, deny the claim on this exclusion and do not file it."
  }
}
```

## shipping

```json
{
  "topic": "shipping",
  "rules": {
    "not_received": {
      "under_500": "Delivered but not received (<$500): reship or refund.",
      "over_500": "Delivered but not received (>=$500): mandatory investigation (3-5 business days).",
      "signature_on_file": "Delivery with signature on file: claim denied."
    },
    "lost_in_transit": {
      "under_500": "Lost in transit (<$500): immediate reship or refund.",
      "over_500": "Lost in transit (>=$500): carrier claim required first.",
      "stuck_7_days": "No tracking update for 7+ days: treat as lost."
    },
    "damaged": {
      "rule": "Damaged in transit: full refund or replacement.",
      "fragile_bonus": "Fragile items damaged in transit qualify for a separate $10 goodwill credit, issued as a refund in addition to the return refund."
    },
    "late_delivery_compensation": {
      "tiers": {
        "1_to_2_days_late": "$5 credit",
        "3_to_5_days_late": "$15 credit",
        "6_plus_days_late": "Full shipping refund + $15 credit"
      },
      "shipping_refund_basis": "When refunding shipping, refund the actual shipping cost the customer was charged on the order — read order.shipping_cost. Standard policy charges $0 on free-shipping orders (subtotal >= $100) and $8 otherwise.",
      "tier_multipliers": {
        "gold": "1.5x multiplier on the base late-delivery credit only (NOT on shipping refund or goodwill). Rounded down (e.g., int(15*1.5) = 22).",
        "platinum": "2x multiplier on the base late-delivery credit only. Rounded down."
      },
      "repeated_issues": "3+ PRIOR issues in 6 months (not counting current incident): additional $25 goodwill credit.",
      "loyalty_bonus": "Platinum members with 50+ total orders: one-time $50 loyalty bonus on next compensation claim. Confirm with customer if already redeemed.",
      "max_cap": "Maximum compensation: 50% of order total (rounded down).",
      "calculation_order": "1) Compute base credit by days-late tier. 2) Apply tier multiplier to base credit only. 3) Add shipping refund (if 6+ days late) using order.shipping_cost. 4) Add goodwill (if 3+ prior issues or fragile damage). 5) Apply loyalty bonus if eligible. 6) Apply 50%-of-order cap on the sum."
    }
  }
}
```
