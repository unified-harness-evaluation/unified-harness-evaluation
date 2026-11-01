import os
import sys
import fire
from icalendar import Calendar

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


@log_tool_call("calendar.delete_event")
def main(user, summary):
    if "@" in user:
        user = user.split("@")[0]
    calendar_file = os.path.join(TESTBED_DIR, "calendar", f"{user}.ics")
    try:
        cal = Calendar.from_ical(open(calendar_file, "rb").read())
        for component in cal.walk():
            if component.name == "VEVENT" and component.get("summary") == summary:
                cal.subcomponents.remove(component)
                break
        with open(calendar_file, "wb") as f:
            f.write(cal.to_ical())
        return f"OBSERVATION: Successfully delete an event named {summary} from {user}'s calendar."
    except Exception:
        return f"OBSERVATION: Failed to delete an event named {summary} from {user}'s calendar."


if __name__ == "__main__":
    fire.Fire(main)
