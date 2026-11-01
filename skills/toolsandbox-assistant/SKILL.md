---
name: toolsandbox-assistant
description: >-
  Act as a mock personal-device assistant backed by the unified per-task SQLite
  database (`/workspace/world.db`, `ts_*` tables). Use when asked to manage
  contacts, send/search text messages, create or search reminders, toggle device
  settings (wifi, cellular, location, low battery), read the current location, or
  do timestamp/unit/distance/US-holiday calculations against the mock state.
  Ported from Apple's ToolSandbox benchmark; fully offline.
---

# ToolSandboxAssistant

A skill that exposes ToolSandbox's mock-assistant tools as a single CLI. All
state lives in the unified per-task `/workspace/world.db` (`ts_*` tables) — no
network calls, no external services. This skill lives at
`/workspace/skills/toolsandbox-assistant/` in the sandbox.


## Setup (one time)

Install the offline dependencies before first use:

```bash
uv pip install -r /workspace/skills/toolsandbox-assistant/requirements.txt
```

(`rapidfuzz`, `phonenumbers`, `pint`, `geopy`, `holidays` — all offline.)
Requires Python 3.10+.

## How state works — read this first

- All state lives in the unified per-task **`world.db`** at `/workspace/world.db`.
  This skill owns the `ts_`-prefixed tables (`ts_contacts`, `ts_messages`,
  `ts_reminders`, `ts_device_settings`); the tools address them by their logical
  names (`contacts`, etc.) automatically.
- `world.db` is seeded **fresh at the start of every task**, so there is no
  separate template to copy and no per-checkout working file to manage — reads
  and writes go straight to `/workspace/world.db`.
- Override the DB path with the `TOOLSANDBOX_ASSISTANT_DB` environment variable
  if you need to point at a different `world.db`.
- `python /workspace/skills/toolsandbox-assistant/tools.py reset` is a **no-op**
  (the runner already re-seeds `world.db` per task); it never wipes shared data.

## Invoking tools

```bash
python /workspace/skills/toolsandbox-assistant/tools.py <tool_name> --json '{"arg": "value", ...}'
# or:  python /workspace/skills/toolsandbox-assistant/tools.py <tool_name> --arg value --arg2 value2
python /workspace/skills/toolsandbox-assistant/tools.py list    # print all tool names
python /workspace/skills/toolsandbox-assistant/tools.py reset   # no-op (world.db is re-seeded per task)
```

Only the arguments you pass are forwarded; omitted arguments use the tool's own
default. Every call prints one JSON object and exits 0:

```json
{"ok": true,  "result": <value>}
{"ok": false, "error": {"type": "<ExceptionType>", "message": "..."}}
```

Always check `ok`. On failure, `error.type` is the original exception name
(e.g. `DuplicateError`, `NoDataError`, `NumberParseException`, `ConnectionError`,
`PermissionError`, `ValueError`, `TypeError`) — use it to decide how to recover.

## Tool catalog (28 tools)

### Contacts
- `add_contact(name, phone_number, relationship=None, is_self=False)` → person_id.
  Raises `DuplicateError` if adding a second self-contact.
- `modify_contact(person_id, name?, phone_number?, relationship?, is_self?)` → null.
  `NoDataError` if id missing; needs ≥1 field.
- `remove_contact(person_id)` → null. `NoDataError` if id missing.
- `search_contacts(person_id?, name?, phone_number?, relationship?, is_self?)` →
  list. `name`/`relationship` are fuzzy-matched; ids/phone/is_self exact. Needs
  ≥1 criterion.

### Messaging
- `send_message_with_phone_number(phone_number, content)` → message_id. Requires
  cellular ON (`ConnectionError` otherwise) and exactly one self-contact.
- `search_messages(message_id?, sender_person_id?, sender_phone_number?, recipient_person_id?, recipient_phone_number?, content?, creation_timestamp_lowerbound?, creation_timestamp_upperbound?)`
  → list. `content` fuzzy; timestamps are range bounds. Needs ≥1 criterion.

### Reminders
- `add_reminder(content, reminder_timestamp, latitude=None, longitude=None)` → reminder_id.
- `modify_reminder(reminder_id, content?, reminder_timestamp?, latitude?, longitude?)` → null.
  `NoDataError` if id missing; needs ≥1 field; refreshes creation timestamp.
- `search_reminder(reminder_id?, content?, creation_timestamp_lowerbound?, creation_timestamp_upperbound?, reminder_timestamp_lowerbound?, reminder_timestamp_upperbound?, latitude?, longitude?)`
  → list. `content` fuzzy; timestamps range bounds. Needs ≥1 criterion.
- `remove_reminder(reminder_id)` → null. `NoDataError` if id missing.

### Settings (device_settings is a single row)
- `get_wifi_status()` / `set_wifi_status(on)`
- `get_cellular_service_status()` / `set_cellular_service_status(on)`
- `get_location_service_status()` / `set_location_service_status(on)`
- `get_low_battery_mode_status()` / `set_low_battery_mode_status(on)`
- `get_current_location()` → {latitude, longitude}
- Semantics: toggling a setting to its current state raises `ValueError`.
  Enabling low-battery mode cascades wifi/cellular/location OFF. While
  low-battery mode is ON, enabling wifi/cellular/location raises
  `PermissionError`. `get_current_location` raises `PermissionError` when
  location service is OFF.

### Utilities (pure / offline)
- `get_current_timestamp()` → POSIX float (real wall clock)
- `timestamp_to_datetime_info(timestamp)` / `datetime_info_to_timestamp(year, month, day, hour, minute, second)`
- `shift_timestamp(timestamp, weeks=0, days=0, hours=0, minutes=0, seconds=0)`
- `timestamp_diff(timestamp_0, timestamp_1)` → {days, seconds}
- `seconds_to_hours_minutes_seconds(seconds)` → {hour, minute, second}
- `unit_conversion(amount, from_unit, to_unit)` → float (via `pint`)
- `calculate_lat_lon_distance(latitude_0, longitude_0, latitude_1, longitude_1)` → km (via `geopy`)
- `search_holiday(holiday_name, year=None)` → POSIX float or null. US holidays;
  requires wifi ON (`ConnectionError` otherwise).

## Examples

```bash
# Find the user's own contact
python /workspace/skills/toolsandbox-assistant/tools.py search_contacts --json '{"is_self": true}'

# Text a number (needs cellular on)
python /workspace/skills/toolsandbox-assistant/tools.py send_message_with_phone_number \
  --json '{"phone_number": "+1-415-555-0102", "content": "on my way"}'

# Create a reminder for a given POSIX time
python /workspace/skills/toolsandbox-assistant/tools.py add_reminder --json '{"content": "call mom", "reminder_timestamp": 1800000000.0}'

# Convert units
python /workspace/skills/toolsandbox-assistant/tools.py unit_conversion --json '{"amount": 100, "from_unit": "celsius", "to_unit": "fahrenheit"}'
```

## Notes / limitations

- Timestamps are POSIX seconds; validated to the 1980–2050 range.
- Fuzzy search uses rapidfuzz `WRatio` and returns at most the top 5 matches
  (matches the original benchmark behavior).
- The RapidAPI-backed tools (web/geo/weather/stock/currency search) from the
  original ToolSandbox are intentionally **not** included — they require live
  third-party APIs and would break self-containment.
