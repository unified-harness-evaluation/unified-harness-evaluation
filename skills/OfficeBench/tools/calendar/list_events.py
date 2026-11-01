import os
import sys
import fire
import icalendar

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


def _fmt(obj):
    return obj.dt.strftime("%Y-%m-%d %H:%M:%S") if obj else ""


@log_tool_call("calendar.list_events")
def main(username):
    if "@" in username:
        username = username.split("@")[0]
    calendar_dir = os.path.join(TESTBED_DIR, "calendar")
    os.makedirs(calendar_dir, exist_ok=True)
    calendar_file = os.path.join(calendar_dir, f"{username}.ics")
    if not os.path.exists(calendar_file):
        cal = icalendar.Calendar()
        cal.add("prodid", "-//My Calendar Product//mxm.dk//")
        cal.add("version", "2.0")
        with open(calendar_file, "wb") as f:
            f.write(cal.to_ical())
    try:
        cal = icalendar.Calendar.from_ical(open(calendar_file, "rb").read())
        message = ""
        for component in cal.walk():
            if component.name == "VEVENT":
                message += f"Summary: {component.get('summary')}\n"
                message += f"Start Time: {_fmt(component.get('dtstart'))}\n"
                message += f"End Time: {_fmt(component.get('dtend'))}\n"
                message += f"Description: {component.get('description')}\n"
                message += f"Location: {component.get('location')}\n"
                message += "-" * 50 + "\n"
        message = message.strip()
        if not message:
            return f"OBSERVATION: No events found for {username}."
        return f"OBSERVATION: Successfully list events for {username}:\n{message}"
    except Exception:
        return f"OBSERVATION: Failed to list events for {username}."


if __name__ == "__main__":
    fire.Fire(main)
