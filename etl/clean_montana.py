#!/usr/bin/env python3
"""Convert Montana DOC's denied-books workbook to the project schema.

Source: data/raw/montana/Denied books_PHCF_February 2026.xlsx
        (Pine Hills Correctional Facility), sheet "Denied Book List"
Output: data/processed/cleaned_montana.csv

Install dependency: python -m pip install openpyxl
Run from anywhere:  python etl/clean_montana.py

Only the "Denied Book List" sheet is read. The workbook's other sheets hold
inmate personal records unrelated to book bans and are deliberately ignored.
The sheet has no publication-type column, so that field is left blank. The
"Committee" column (reviewer) and the broken formula column F (#NAME?) are
dropped. Duplicate titles are kept, since they can be separate decisions.

Not processed: data/raw/montana/Denied_books_MSP_February_2026.xls (Montana
State Prison) is protected with Microsoft Information Rights Management and
cannot be opened without permission from the issuing tenant.
"""

import csv
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data/raw/montana/Denied books_PHCF_February 2026.xlsx"
DESTINATION = REPO_ROOT / "data/processed/cleaned_montana.csv"

FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
HEADER_ROW = 4
EXPECTED_HEADERS = ("Book Title", "Author", "Reason(s) for Denial", "Date")


def clean(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def main() -> None:
    sheet = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)["Denied Book List"]
    rows = sheet.iter_rows(min_row=HEADER_ROW, max_col=4, values_only=True)

    headers = tuple(clean(v) for v in next(rows))
    if headers != EXPECTED_HEADERS:
        raise ValueError(f"Source columns changed: {headers!r}")

    records = []
    for row_num, (title, author, reason, date) in enumerate(rows, start=HEADER_ROW + 1):
        if not any(clean(v) for v in (title, author, reason, date)):
            continue  # The sheet has many formatted-but-empty rows.
        if not clean(title):
            raise ValueError(f"Row {row_num} has data but no title")
        if date is not None and not hasattr(date, "date"):
            raise ValueError(f"Row {row_num} has a non-date Date value: {date!r}")
        records.append({
            "title": clean(title),
            "author": clean(author),
            "date": date.date().isoformat() if date else "",
            "publication_type": "",
            "rejection_reason": clean(reason),
        })

    with DESTINATION.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records):,} records to {DESTINATION}")


if __name__ == "__main__":
    main()
