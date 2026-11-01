import os
import sys
import fire
from glob import glob
from email import policy
from email.parser import BytesParser

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


def _get_content(msg):
    if msg.is_multipart():
        parts = []
        for part in msg.iter_parts():
            if part.get_content_type() in ("text/plain", "text/html"):
                parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(parts)
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")


@log_tool_call("email.list_emails")
def main(username):
    if "@" in username:
        username = username.split("@")[0]
    email_folder = os.path.join(TESTBED_DIR, "emails", username)
    os.makedirs(email_folder, exist_ok=True)
    try:
        email_files = glob(f"{email_folder}/*.eml")
        if not email_files:
            return f"OBSERVATION: No emails found for {username}."
        message = ""
        for email_file in email_files:
            with open(email_file, "rb") as f:
                email = BytesParser(policy=policy.default).parsebytes(f.read())
            email_name = os.path.basename(email_file)
            message += f"Email ID: {email_name}\n"
            message += f"From: {email['From']}\n"
            message += f"To: {email['To']}\n"
            message += f"Subject: {email['Subject']}\n"
            message += f"Content: {_get_content(email)[:20]}...\n"
            message += "-" * 50 + "\n"
        return f"OBSERVATION: Successfully list emails for {username}:\n{message}"
    except Exception:
        return f"OBSERVATION: Failed to list emails for {username}."


if __name__ == "__main__":
    fire.Fire(main)
