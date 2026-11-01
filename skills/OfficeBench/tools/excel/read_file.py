import os
import sys
import fire
import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


def _read_file(file_path, sheet=None):
    if sheet is None:
        ws = openpyxl.load_workbook(file_path).active
    else:
        ws = openpyxl.load_workbook(file_path)[sheet]
    content = ""
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value if cell.value is not None else "[Empty Cell]"
            content += f"({cell.row}, {cell.column}): {value}\t"
        content += "\n"
    return content


@log_tool_call("excel.read_file")
def main(file_path, sheet=None):
    if not os.path.exists(file_path):
        return f"OBSERVATION: The file {file_path} does not exist. Failed to read the file."
    contents = _read_file(file_path, sheet)
    return f"OBSERVATION: The following is the table from the excel file:\n{contents}"


if __name__ == "__main__":
    fire.Fire(main)
