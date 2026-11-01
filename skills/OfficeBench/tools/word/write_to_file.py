import os
import sys
import fire
from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


_PURE_TEXT_ALIASES = {"pure-text", "plain", "plain-text", "normal", "text", "paragraph", ""}


def _write_to_file(file_path, contents, style="pure-text"):
    try:
        doc = Document(file_path) if os.path.exists(file_path) else Document()
        if style.lower() in _PURE_TEXT_ALIASES:
            doc.add_paragraph(contents)
        elif style == "title":
            doc.add_heading(contents, 0)
        elif style == "subtitle":
            doc.add_heading(contents, 1)
        else:
            doc.add_paragraph(contents)
        doc.save(file_path)
        return True
    except Exception:
        return False


@log_tool_call("word.write_to_file")
def main(file_path, contents, style="pure-text"):
    if not os.path.exists(file_path):
        return f"OBSERVATION: The file {file_path} does not exist. Failed to write to the file."
    success = _write_to_file(file_path, contents, style)
    if success:
        return f"OBSERVATION: Successfully write contents to {file_path}"
    return f"OBSERVATION: Failed to write contents to {file_path}"


if __name__ == "__main__":
    fire.Fire(main)
