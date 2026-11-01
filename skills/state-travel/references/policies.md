# Travel booking & service — Policies

Full policy reference for this domain. The agent can also fetch any topic at
runtime via the `get_policies` tool. Topics below are the canonical set.

## cancel

```json
{
  "topic": "cancellation",
  "rules": {
    "free_cancellation_window": "Full refund within 24 hours (domestic) or 48 hours (international) of booking",
    "basic_economy": "Not cancellable after free window (unless insured)",
    "economy_domestic": "Cancellation fee: max($50, 15% of ticket price)",
    "economy_international": "Cancellation fee: max($75, 20% of ticket price)",
    "business_domestic": "Cancellation fee: 5% of ticket price",
    "business_international": "Cancellation fee: 8% of ticket price",
    "first": "Free cancellation",
    "insurance": "Travel insurance covers cancellation regardless of cabin class",
    "route_type_matters": "Fees differ by route type (domestic vs international). Check flight route_type."
  },
  "applicable_cabin_class": "economy",
  "applicable_route_type": "domestic"
}
```

## change

```json
{
  "topic": "change",
  "rules": {
    "free_change_window": "Free changes within 24 hours (domestic) or 48 hours (international) of booking",
    "basic_economy": "Not changeable after free window",
    "economy_domestic_personal": "Domestic change fee: $75 if departure >7 days, $150 if ≤7 days. Fare difference also applies.",
    "economy_international_personal": "International change fee: $100 if departure >7 days, $200 if ≤7 days. Fare difference also applies.",
    "economy_medical": "Medical changes: 50% discount on standard fee, rounded down to the nearest dollar (requires change_reason='medical')",
    "economy_bereavement": "Bereavement changes: 75% discount on standard fee, rounded down to the nearest dollar (requires change_reason='bereavement')",
    "jury_duty": "Jury duty: free change (change_reason='jury_duty')",
    "military": "Military deployment: free change (change_reason='military')",
    "schedule_change": "Airline schedule changes: free, no fee (change_reason='schedule_change')",
    "weather": "Weather-related changes: free, no fee (change_reason='weather')",
    "business": "Free changes (fare difference still applies)",
    "first": "Free changes (fare difference still applies)",
    "change_reason_required": "Pass change_reason parameter: 'personal', 'medical', 'bereavement', 'jury_duty', 'military', 'schedule_change', or 'weather'",
    "route_type_matters": "Fees differ by route type. Check flight route_type."
  },
  "applicable_cabin_class": "economy",
  "applicable_route_type": "domestic"
}
```

## baggage

```json
{
  "topic": "baggage",
  "carry_on": 1,
  "base_checked_bags": 1,
  "loyalty_bonus_checked_bags": 0,
  "checked_bags_free": 1,
  "checked_bag_fee": 35,
  "oversized_bag_fee": 100,
  "cabin_class": "economy",
  "loyalty_tier": "basic"
}
```

## delay_compensation

```json
{
  "topic": "delay_compensation",
  "rules": {
    "under_120_min": "No compensation (delay under 120 minutes / 2 hours)",
    "120_to_239_min": "$25 meal voucher (delay from 120 up to but not including 240 minutes)",
    "240_min_or_more": "Rebooking + $25 meal voucher + hotel if overnight (delay of 240 minutes / 4 hours or more)",
    "overnight_delay": "If delay causes overnight stay, hotel voucher + $50 incidentals provided"
  }
}
```

## loyalty

```json
{
  "topic": "loyalty",
  "rules": {
    "minimum_redemption": "1,000 points minimum to redeem",
    "domestic_rate": "1 point = $0.01 (100 points = $1)",
    "international_rate": "1 point = $0.015 (100 points = $1.50)",
    "rounding": "Points used are rounded to the nearest 100",
    "max_coverage": "Points can cover up to 100% of flight price"
  },
  "applicable_loyalty_tier": "basic",
  "applicable_route_type": "domestic"
}
```

## upgrade

```json
{
  "topic": "upgrade",
  "rules": {
    "economy_to_business": "Upgrade fee = target cabin listed price minus amount already paid",
    "business_to_first": "Upgrade fee = target cabin listed price minus amount already paid",
    "economy_to_first": "Not available directly (must upgrade to business first)",
    "basic_economy": "Not eligible for upgrades"
  },
  "applicable_cabin_class": "economy"
}
```

## hotel_cancel

```json
{
  "topic": "hotel_cancellation",
  "rules": {
    "standard_room_48h_plus": "Free cancellation if 48+ hours before check-in",
    "standard_room_24_48h": "50% of first night charge if 24-48 hours before check-in",
    "standard_room_under_24h": "Full first night charge if <24 hours before check-in",
    "suite": "Suite bookings are non-refundable (full charge regardless of timing)"
  }
}
```

## car_rental_cancel

```json
{
  "topic": "car_rental_cancellation",
  "rules": {
    "24h_plus": "Free cancellation if 24+ hours before pickup",
    "under_24h": "One day charge if <24 hours before pickup",
    "luxury_suv_surcharge": "Luxury and SUV rentals incur an additional $50 cancellation surcharge at all times"
  }
}
```
