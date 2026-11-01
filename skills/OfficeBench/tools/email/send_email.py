import os
import sys
import fire
from email.message import EmailMessage

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


@log_tool_call("email.send_email")
def main(sender, recipient, subject, content):
    if "@" in sender:
        sender = sender.split("@")[0]
    if "@" in recipient:
        recipient = recipient.split("@")[0]
    try:
        os.makedirs(os.path.join(TESTBED_DIR, "emails", sender), exist_ok=True)
        os.makedirs(os.path.join(TESTBED_DIR, "emails", recipient), exist_ok=True)
        email = EmailMessage()
        email["From"] = sender + "@example.com"
        email["To"] = recipient + "@example.com"
        email["Subject"] = subject
        email.set_content(content)
        for folder in [sender, recipient]:
            email_file = os.path.join(TESTBED_DIR, "emails", folder, f"{subject}.eml")
            with open(email_file, "w") as f:
                f.write(email.as_string())
        return f"OBSERVATION: Successfully sent email to {recipient}."
    except Exception as e:
        return f"OBSERVATION: Failed to send email to {recipient}. Error: {e}"


if __name__ == "__main__":
    fire.Fire(main)
