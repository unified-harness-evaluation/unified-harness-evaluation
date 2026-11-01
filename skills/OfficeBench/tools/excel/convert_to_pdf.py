import os
import sys
import fire
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _convert_to_pdf(excel_file_path, pdf_file_path):
    try:
        output_dir = os.path.dirname(pdf_file_path)
        os.makedirs(output_dir, exist_ok=True)
        subprocess.call(
            ["libreoffice", "--headless", "--convert-to", "pdf", excel_file_path, "--outdir", output_dir]
        )
        stem = os.path.splitext(os.path.basename(excel_file_path))[0]
        generated = os.path.join(output_dir, stem + ".pdf")
        if generated != pdf_file_path and os.path.exists(generated):
            os.rename(generated, pdf_file_path)
        return os.path.exists(pdf_file_path)
    except Exception:
        return False


@log_tool_call("excel.convert_to_pdf")
def main(excel_file_path, pdf_file_path):
    if not os.path.exists(excel_file_path):
        return f"OBSERVATION: {excel_file_path} does not exist. Failed to convert {excel_file_path} to {pdf_file_path}"
    success = _convert_to_pdf(excel_file_path, pdf_file_path)
    if success:
        return f"OBSERVATION: Successfully convert {excel_file_path} to {pdf_file_path}"
    return f"OBSERVATION: Failed to convert {excel_file_path} to {pdf_file_path}"


if __name__ == "__main__":
    fire.Fire(main)
