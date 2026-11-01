import os
import sys
import fire
import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _set_cell(file_path, text, row_idx, column_idx, sheet_name=None):
    if text is True:
        text = ""
    try:
        workbook = openpyxl.load_workbook(file_path) if os.path.exists(file_path) else openpyxl.Workbook()
        if sheet_name is None:
            sheet = workbook.active
        else:
            try:
                sheet = workbook[sheet_name]
            except KeyError:
                sheet = workbook.create_sheet(title=sheet_name)
        sheet.cell(row=int(row_idx), column=int(column_idx), value=text)
        workbook.save(file_path)
        return True
    except Exception:
        return False


@log_tool_call("excel.set_cell")
def main(file_path, row_idx, column_idx, text, sheet_name=None):
    if not os.path.exists(file_path):
        return f"OBSERVATION: The file {file_path} does not exist. Failed to write to the file."
    success = _set_cell(file_path, text, row_idx, column_idx, sheet_name)
    if success:
        return f"OBSERVATION: Successfully write text to {file_path}"
    return f"OBSERVATION: Failed to write text to {file_path}"


if __name__ == "__main__":
    fire.Fire(main)
