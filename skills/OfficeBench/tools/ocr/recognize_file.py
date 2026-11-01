import os
import sys
import fire
import pytesseract
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _recognize_file(file_path):
    try:
        return pytesseract.image_to_string(Image.open(file_path))
    except Exception:
        return None


@log_tool_call("ocr.recognize_file")
def main(file_path):
    if not os.path.exists(file_path):
        return f"OBSERVATION: The file {file_path} does not exist. Failed to recognize text."
    text = _recognize_file(file_path)
    if text:
        return f"OBSERVATION: The text from {file_path} is:\n{text}"
    return f"OBSERVATION: Failed to recognize text from {file_path}"


if __name__ == "__main__":
    fire.Fire(main)
