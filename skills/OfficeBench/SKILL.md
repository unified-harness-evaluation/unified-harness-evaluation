---
name: OfficeBench
description: Office productivity tools for working with files in the testbed. Provides Excel, Word, PDF, email, calendar, OCR, shell, and LLM capabilities.
---

## Dependencies

Run once at the start of each session before calling any tools:

```
uv pip install openpyxl python-docx PyPDF2 pdf2docx PyMuPDF Pillow pytesseract icalendar fire litellm
```

---

## Testbed

All files live under the unified testbed root at `/workspace/testbed/` (inside container).

Usernames are short names (e.g. `alice`, `bob`, `carol`) — never full email addresses.

## Calling tools

The container CWD is `/workspace`. Call tools directly — no `cd` needed:

```
python3 skills/OfficeBench/tools/<app>/<tool>.py [--arg value ...]
```

File paths for testbed files use the full container path, e.g.:
```
/workspace/testbed/docs/report.docx
/workspace/testbed/data/budget.xlsx
```

Quote arguments that contain spaces or special characters.

---

## Excel

**read_file** — read all cell values (row, col): value
```
python3 skills/OfficeBench/tools/excel/read_file.py --file_path <path> [--sheet <sheet_name>]
```

**set_cell** — write a value to a cell (1-based row/col indices)
```
python3 skills/OfficeBench/tools/excel/set_cell.py \
  --file_path <path> --row_idx <int> --column_idx <int> --text '<value>' [--sheet_name <sheet>]
```

**delete_cell** — clear a cell
```
python3 skills/OfficeBench/tools/excel/delete_cell.py \
  --file_path <path> --row_idx <int> --column_idx <int> [--sheet_name <sheet>]
```

**create_new_file** — create a new empty Excel file
```
python3 skills/OfficeBench/tools/excel/create_new_file.py --file_path <path>
```

**convert_to_pdf** — convert Excel to PDF via LibreOffice
```
python3 skills/OfficeBench/tools/excel/convert_to_pdf.py \
  --excel_file_path <path> --pdf_file_path <path>
```

---

## Word

**read_file** — read paragraph text
```
python3 skills/OfficeBench/tools/word/read_file.py --file_path <path>
```

**write_to_file** — append text (style: `pure-text` | `title` | `subtitle`)
```
python3 skills/OfficeBench/tools/word/write_to_file.py \
  --file_path <path> --contents '<text>' [--style pure-text]
```

**create_new_file** — create a new empty Word document
```
python3 skills/OfficeBench/tools/word/create_new_file.py --file_path <path>
```

**convert_to_pdf** — convert Word to PDF
```
python3 skills/OfficeBench/tools/word/convert_to_pdf.py \
  --word_file_path <path> --pdf_file_path <path>
```

---

## PDF

**read_file** — extract text from all pages
```
python3 skills/OfficeBench/tools/pdf/read_file.py --pdf_file_path <path>
```

**convert_to_image** — render first page to an image file
```
python3 skills/OfficeBench/tools/pdf/convert_to_image.py \
  --pdf_file_path <path> --image_file_path <path>
```

**convert_to_word** — convert PDF to Word document
```
python3 skills/OfficeBench/tools/pdf/convert_to_word.py \
  --pdf_file_path <path> --word_file_path <path>
```

---

## Email

**list_emails** — list inbox emails for a user
```
python3 skills/OfficeBench/tools/email/list_emails.py --username <name>
```

**read_email** — read a specific email (email_id is the filename, e.g. `Hello.eml`)
```
python3 skills/OfficeBench/tools/email/read_email.py --username <name> --email_id '<Subject.eml>'
```

**send_email** — send an email (saved to both sender and recipient inboxes)
```
python3 skills/OfficeBench/tools/email/send_email.py \
  --sender <name> --recipient <name> --subject '<subject>' --content '<body>'
```

---

## Calendar

**list_events** — list all events from a user's calendar
```
python3 skills/OfficeBench/tools/calendar/list_events.py --username <name>
```

**create_event** — add an event (datetime: `YYYY-MM-DD HH:MM:SS`)
```
python3 skills/OfficeBench/tools/calendar/create_event.py \
  --user <name> --summary '<title>' --time_start '<start>' --time_end '<end>'
```

**delete_event** — remove an event by its summary/title
```
python3 skills/OfficeBench/tools/calendar/delete_event.py --user <name> --summary '<title>'
```

---

## OCR

**recognize_file** — extract text from an image via OCR
```
python3 skills/OfficeBench/tools/ocr/recognize_file.py --file_path <path>
```

---

## Shell

**command** — run a shell command (working directory: testbed root)
```
python3 skills/OfficeBench/tools/shell/command.py --command '<cmd>'
```

---

## LLM

**complete_text** — send a prompt to the configured LLM and return the response
```
python3 skills/OfficeBench/tools/llm/complete_text.py --prompt '<prompt>'
```
