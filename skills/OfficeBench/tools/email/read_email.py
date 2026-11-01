import os
import sys
import fire
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


@log_tool_call("email.read_email")
def main(username, email_id):
    if "@" in username:
        username = username.split("@")[0]
    if not email_id.endswith(".eml"):
        email_id += ".eml"
    email_file = os.path.join(TESTBED_DIR, "emails", username, email_id)
    try:
        with open(email_file, "rb") as f:
            email = BytesParser(policy=policy.default).parsebytes(f.read())
        message = (
            f"From: {email['From']}\n"
            f"To: {email['To']}\n"
            f"Subject: {email['Subject']}\n"
            f"Content: {_get_content(email)}\n"
        )
        return f"OBSERVATION: Successfully read email {email_id} for {username}:\n{message}"
    except Exception:
        return f"OBSERVATION: Failed to read email {email_id} for {username}."


if __name__ == "__main__":
    fire.Fire(main)
