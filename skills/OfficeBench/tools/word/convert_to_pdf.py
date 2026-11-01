import os
import sys
import fire
import shutil
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _convert_to_pdf(word_file_path, pdf_file_path):
    try:
        output_dir = os.path.dirname(pdf_file_path)
        os.makedirs(output_dir, exist_ok=True)
        lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
        if lo_bin:
            subprocess.call([lo_bin, "--headless", "--convert-to", "pdf", word_file_path, "--outdir", output_dir])
            stem = os.path.splitext(os.path.basename(word_file_path))[0]
            generated = os.path.join(output_dir, stem + ".pdf")
            if generated != pdf_file_path and os.path.exists(generated):
                os.rename(generated, pdf_file_path)
            if os.path.exists(pdf_file_path):
                return True
        from docx import Document
        from fpdf import FPDF
        doc = Document(word_file_path)
        pdf = FPDF()
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                safe = text.encode("latin-1", errors="replace").decode("latin-1")
                pdf.multi_cell(0, 8, safe)
                pdf.ln(2)
        pdf.output(pdf_file_path)
        return os.path.exists(pdf_file_path)
    except Exception:
        return False


@log_tool_call("word.convert_to_pdf")
def main(word_file_path, pdf_file_path):
    if not os.path.exists(word_file_path):
        return f"OBSERVATION: The word file {word_file_path} does not exist. Failed to convert the file to pdf."
    success = _convert_to_pdf(word_file_path, pdf_file_path)
    if success:
        return f"OBSERVATION: Successfully convert {word_file_path} to {pdf_file_path}"
    return f"OBSERVATION: Failed to convert {word_file_path} to {pdf_file_path}"


if __name__ == "__main__":
    fire.Fire(main)
