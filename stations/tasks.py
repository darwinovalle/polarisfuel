from celery import shared_task
from openpyxl import load_workbook
from pathlib import Path
import os

from stations.services.import_pipeline import run_import
from stations.services.parsing import REQUIRED_HEADERS

def _read_excel_rows(file_path: str):
    workbook = load_workbook(file_path, data_only=True)
    sheet = workbook.active

    rows_iter = sheet.iter_rows(values_only=True)
    header_row = next(rows_iter, None)
    if not header_row:
        raise ValueError("Excel file is empty")

    headers = [str(h).strip() if h is not None else "" for h in header_row]
    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        raise ValueError(f"Missing headers: {', '.join(missing)}")

    parsed_rows = []
    for values in rows_iter:
        row = {headers[i]: values[i] for i in range(len(headers))}
        parsed_rows.append(row)

    return parsed_rows

@shared_task(name="stations.tasks.run_daily_import")
def run_daily_import():
    source_path = os.getenv("EXCEL_SOURCE_PATH", "").strip()
    if not source_path:
        return {"status": "skipped", "reason": "EXCEL_SOURCE_PATH not set"}
    path = Path(source_path)
    if not path.exists():
        return {"status": "skipped", "reason": f"file not found: {source_path}"}

    rows = _read_excel_rows(str(path))
    result = run_import(rows, source_filename=path.name)
    return {"status": "ok", "result": result}
