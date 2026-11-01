import os
import sys
import fire
from docx import Document

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


@log_tool_call("word.read_file")
def main(file_path):
    if not os.path.exists(file_path):
        return f"OBSERVATION: The file {file_path} does not exist. Failed to read the file."
    doc = Document(file_path)
    content = "The following is the content from the word file:"
    for paragraph in doc.paragraphs:
        content += f"\n{paragraph.text}"
    return "OBSERVATION: " + content


if __name__ == "__main__":
    fire.Fire(main)
