import os
import sys
import fire
import fitz

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _convert_to_image(pdf_file_path, image_file_path):
    try:
        with fitz.open(pdf_file_path) as doc:
            page = doc.load_page(0)
            pix = page.get_pixmap()
            pix.save(image_file_path)
        return True
    except Exception:
        return False


@log_tool_call("pdf.convert_to_image")
def main(pdf_file_path, image_file_path):
    if not os.path.exists(pdf_file_path):
        return f"OBSERVATION: The file {pdf_file_path} does not exist. Failed to convert pdf to image."
    success = _convert_to_image(pdf_file_path, image_file_path)
    if success:
        return f"OBSERVATION: Successfully convert {pdf_file_path} to {image_file_path}"
    return f"OBSERVATION: Failed to convert {pdf_file_path} to {image_file_path}"


if __name__ == "__main__":
    fire.Fire(main)
