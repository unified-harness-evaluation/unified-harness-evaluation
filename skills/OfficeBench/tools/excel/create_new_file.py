import os
import sys
import fire
import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _create_new_file(file_path):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        wb = openpyxl.Workbook()
        wb.active.title = "Sheet"
        wb.save(file_path)
        return True
    except Exception:
        return False


@log_tool_call("excel.create_new_file")
def main(file_path):
    if os.path.exists(file_path):
        return f"OBSERVATION: File {file_path} already exists"
    success = _create_new_file(file_path)
    if success:
        return f"OBSERVATION: Successfully create new file {file_path}"
    return f"OBSERVATION: Failed to create new file {file_path}"


if __name__ == "__main__":
    fire.Fire(main)
