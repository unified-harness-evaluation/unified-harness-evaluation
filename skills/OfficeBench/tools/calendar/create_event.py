import os
import sys
import fire
from icalendar import Calendar, Event
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


@log_tool_call("calendar.create_event")
def main(user, summary, time_start, time_end):
    if "@" in user:
        user = user.split("@")[0]
    calendar_dir = os.path.join(TESTBED_DIR, "calendar")
    os.makedirs(calendar_dir, exist_ok=True)
    calendar_file = os.path.join(calendar_dir, f"{user}.ics")
    try:
        if not os.path.exists(calendar_file):
            cal = Calendar()
            cal.add("prodid", "-//My Calendar Product//mxm.dk//")
            cal.add("version", "2.0")
        else:
            cal = Calendar.from_ical(open(calendar_file, "rb").read())
        event = Event()
        event.add("summary", summary)
        event.add("dtstart", datetime.strptime(time_start, "%Y-%m-%d %H:%M:%S"))
        event.add("dtend", datetime.strptime(time_end, "%Y-%m-%d %H:%M:%S"))
        event.add("dtstamp", datetime.now())
        event.add("description", "")
        event.add("location", "")
        cal.add_component(event)
        with open(calendar_file, "wb") as f:
            f.write(cal.to_ical())
        return f"OBSERVATION: Successfully create a new event to {user}'s calendar."
    except Exception:
        return f"OBSERVATION: Failed to create a new event to {user}'s calendar."


if __name__ == "__main__":
    fire.Fire(main)
