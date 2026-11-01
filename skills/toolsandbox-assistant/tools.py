#!/usr/bin/env python3
"""ToolSandboxAssistant — CLI dispatcher for the mock-assistant tools.

Usage:
    python tools.py <tool_name> --json '{"arg": "value", ...}'
    python tools.py <tool_name> --arg value [--arg2 value2 ...]
    python tools.py list          # list available tools
    python tools.py reset         # no-op (world.db is seeded fresh per task)

Every call prints a single JSON object and exits 0:
    success -> {"ok": true,  "result": <value>}
    failure -> {"ok": false, "error": {"type": "<ExceptionType>", "message": "..."}}

State lives in the unified per-task ``world.db`` (this skill owns the ``ts_*``
tables). Its path is read from the TOOLSANDBOX_ASSISTANT_DB env var, defaulting
to ``./world.db`` in the current working directory (``/workspace/world.db`` in
the sandbox). Only keys you pass are forwarded to a tool; omitted arguments fall
back to the tool's own default.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import contact, db, messaging, reminder, setting, utilities  # noqa: E402

# tool_name -> callable. Grouped to mirror the original modules.
REGISTRY = {
    # contact
    "add_contact": contact.add_contact,
    "modify_contact": contact.modify_contact,
    "remove_contact": contact.remove_contact,
    "search_contacts": contact.search_contacts,
    # messaging
    "send_message_with_phone_number": messaging.send_message_with_phone_number,
    "search_messages": messaging.search_messages,
    # reminder
    "add_reminder": reminder.add_reminder,
    "modify_reminder": reminder.modify_reminder,
    "search_reminder": reminder.search_reminder,
    "remove_reminder": reminder.remove_reminder,
    # setting
    "set_low_battery_mode_status": setting.set_low_battery_mode_status,
    "get_low_battery_mode_status": setting.get_low_battery_mode_status,
    "set_location_service_status": setting.set_location_service_status,
    "get_location_service_status": setting.get_location_service_status,
    "set_cellular_service_status": setting.set_cellular_service_status,
    "get_cellular_service_status": setting.get_cellular_service_status,
    "set_wifi_status": setting.set_wifi_status,
    "get_wifi_status": setting.get_wifi_status,
    "get_current_location": setting.get_current_location,
    # utilities
    "get_current_timestamp": utilities.get_current_timestamp,
    "timestamp_to_datetime_info": utilities.timestamp_to_datetime_info,
    "datetime_info_to_timestamp": utilities.datetime_info_to_timestamp,
    "shift_timestamp": utilities.shift_timestamp,
    "timestamp_diff": utilities.timestamp_diff,
    "seconds_to_hours_minutes_seconds": utilities.seconds_to_hours_minutes_seconds,
    "unit_conversion": utilities.unit_conversion,
    "calculate_lat_lon_distance": utilities.calculate_lat_lon_distance,
    "search_holiday": utilities.search_holiday,
}


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))


def _parse_extra(extra: list) -> dict:
    """Parse leftover --key value pairs, JSON-decoding values when possible."""
    kwargs: dict = {}
    i = 0
    while i < len(extra):
        token = extra[i]
        if not token.startswith("--"):
            i += 1
            continue
        key = token[2:]
        if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
            raw = extra[i + 1]
            i += 2
        else:
            raw = "true"  # bare flag
            i += 1
        try:
            kwargs[key] = json.loads(raw)
        except json.JSONDecodeError:
            kwargs[key] = raw
    return kwargs


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("command", help="tool name, or 'list' / 'reset'")
    parser.add_argument("--json", dest="json_args", default=None, help="JSON object of arguments")
    args, extra = parser.parse_known_args(argv)

    if args.command == "list":
        _emit({"ok": True, "result": sorted(REGISTRY.keys())})
        return 0
    if args.command == "reset":
        path = db.reset()
        _emit({"ok": True, "result": {"reset": True, "db_path": str(path)}})
        return 0

    if args.command not in REGISTRY:
        _emit(
            {
                "ok": False,
                "error": {
                    "type": "UnknownTool",
                    "message": f"Unknown tool '{args.command}'. Run `list` to see tools.",
                },
            }
        )
        return 0

    kwargs: dict = {}
    if args.json_args:
        try:
            parsed = json.loads(args.json_args)
        except json.JSONDecodeError as exc:
            _emit({"ok": False, "error": {"type": "JSONDecodeError", "message": str(exc)}})
            return 0
        if not isinstance(parsed, dict):
            _emit(
                {
                    "ok": False,
                    "error": {"type": "ValueError", "message": "--json must be a JSON object"},
                }
            )
            return 0
        kwargs.update(parsed)
    kwargs.update(_parse_extra(extra))

    try:
        result = REGISTRY[args.command](**kwargs)
        _emit({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001 - surface every failure as an envelope
        _emit({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
