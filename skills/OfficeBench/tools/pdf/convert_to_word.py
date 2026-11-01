import os
import sys
import fire
from pdf2docx import Converter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _convert_to_word(pdf_file_path, word_file_path):
    try:
        cv = Converter(pdf_file_path)
        cv.convert(word_file_path, start=0, end=None)
        cv.close()
        return True
    except Exception:
        return False


@log_tool_call("pdf.convert_to_word")
def main(pdf_file_path, word_file_path):
    if not os.path.exists(pdf_file_path):
        return f"OBSERVATION: The pdf file {pdf_file_path} does not exist. Failed to convert the file to word."
    success = _convert_to_word(pdf_file_path, word_file_path)
    if success:
        return f"OBSERVATION: Successfully convert {pdf_file_path} to {word_file_path}"
    return f"OBSERVATION: Failed to convert {pdf_file_path} to {word_file_path}"


if __name__ == "__main__":
    fire.Fire(main)
