import os
import sys
import fire
from PyPDF2 import PdfReader

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _read_file(pdf_file_path):
    reader = PdfReader(pdf_file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text


@log_tool_call("pdf.read_file")
def main(pdf_file_path):
    if not os.path.exists(pdf_file_path):
        return f"OBSERVATION: The pdf file {pdf_file_path} does not exist. Failed to read the file."
    return "OBSERVATION: " + _read_file(pdf_file_path)


if __name__ == "__main__":
    fire.Fire(main)
