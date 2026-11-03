#!/usr/bin/env python3
"""Convert Oregon DOC's rejected-publications workbook to the project schema.

Source (relative to the repository root):
    data/raw/oregon/rejected-publications.xlsx

Output:
    data/processed/cleaned_oregon.csv

Run from any working directory:
    python etl/clean_oregon/extract.py

Uses only the Python standard library. The source Excel workbook has a single
"Books" worksheet. Its data header is on row 6 and its columns are:
BOOK_ID, TITLE, ISBN, Status, Decision Date, Violation Reason.

The project's output schema is: title, author, date, publication_type,
rejection_reason. Author and publication type are intentionally blank: they
are not separately reported in this workbook. Only rows marked REJ are
included. Duplicate titles are retained because they can represent different
books/editions or separate decisions.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "raw" / "oregon" / "rejected-publications.xlsx"
DESTINATION = REPO_ROOT / "data" / "processed" / "cleaned_oregon.csv"

FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
EXPECTED_HEADERS = ("BOOK_ID", "TITLE", "ISBN", "Status", "Decision Date", "Violation Reason")
BASELINE_RECORD_COUNT = 1876  # For the April 17, 2026 source revision; not a hard limit.

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL_COLUMN = re.compile(r"^([A-Z]+)\d+$")

# A comma marks a new reason only when followed by a known reason category or
# standalone reason. In particular, do NOT split internal commas in values
# such as "Substance: Lipstick, crayon, stickers, tape".
NEW_REASON = re.compile(
    r",\s+(?=(?:"
    r"(?:Item|Material|Security|Sexual|Sexual Violence|Substance|"
    r"Publications|Content|Outgoing|Monetary value|Content restrictions|Maps):"
    r"|(?:Sexually Explicit Material|Unauthorized Attachments|"
    r"Package Authorization Required|Maps)(?=,|$)"
    r"))"
)


def read_shared_strings(archive: ZipFile) -> list[str]:
    """Return Excel's shared-string table, including rich-text cell fragments."""
    try:
        xml = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    return [
        "".join(text.text or "" for text in entry.findall(".//x:t", NS))
        for entry in root.findall("x:si", NS)
    ]


def extract_cell_value(cell: ET.Element, strings: list[str]) -> str:
    """Read one cell from the provided workbook without Excel dependencies."""
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//x:t", NS))

    value = cell.find("x:v", NS)
    if value is None or value.text is None:
        # The source has no formulas in relevant columns. Fail rather than
        # silently importing a cached formula as if it were an original value.
        if cell.find("x:f", NS) is not None:
            raise ValueError(f"Formula cell not supported: {cell.get('r')}")
        return ""

    return strings[int(value.text)] if cell_type == "s" else value.text


def read_source_rows(source: Path):
    """Yield (Excel row number, A-F cell values) from the first worksheet."""
    with ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall("x:sheets/x:sheet", NS)
        if len(sheets) != 1 or sheets[0].get("name") != "Books":
            raise ValueError("Expected the supplied single-sheet workbook named 'Books'.")

        # The source workbook places its single 'Books' sheet at sheet1.xml.
        strings = read_shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in root.findall("x:sheetData/x:row", NS):
            row_num = int(row.get("r"))
            values = {letter: "" for letter in "ABCDEF"}
            for cell in row.findall("x:c", NS):
                match = CELL_COLUMN.match(cell.get("r", ""))
                if match and match.group(1) in values:
                    values[match.group(1)] = extract_cell_value(cell, strings).strip()
            yield row_num, values


def convert_excel_date(value: str, row_num: int) -> str:
    """Convert Excel 1900-system serial dates to ISO 8601 (YYYY-MM-DD)."""
    if not value:
        return ""
    try:
        serial = float(value)
        if not (1 <= serial < 100000):
            raise ValueError("date serial out of range")
        # Excel's 1900 leap-year bug is accounted for by the 1899-12-30 epoch.
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid decision date in Excel row {row_num}: {value!r}") from exc


def format_rejection_reasons(raw: str) -> str:
    """Join separate source violations using ' | ' without rewriting wording."""
    if not raw:
        return ""
    return " | ".join(part.strip() for part in NEW_REASON.split(raw) if part.strip())


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Missing Oregon source workbook: {SOURCE}")

    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    reason_counts: Counter[str] = Counter()
    header_seen = False

    for row_num, values in read_source_rows(SOURCE):
        if row_num == 6:
            found_headers = tuple(values[letter] for letter in "ABCDEF")
            if found_headers != EXPECTED_HEADERS:
                raise ValueError(f"Source columns changed: {found_headers!r}")
            header_seen = True
            continue
        if row_num < 7 or not any(values.values()):
            # Rows 1-5 contain explanatory notes, and the workbook includes
            # hundreds of formatted-but-empty trailing rows.
            continue

        book_id, title, _isbn, status, excel_date, raw_reason = (
            values[letter] for letter in "ABCDEF"
        )
        if not book_id and not title and not status:
            continue
        if not book_id or not title or status != "REJ":
            raise ValueError(
                f"Unexpected data at Excel row {row_num}: "
                f"BOOK_ID={book_id!r}, TITLE={title!r}, Status={status!r}"
            )
        if book_id in seen_ids:
            raise ValueError(f"Repeated BOOK_ID {book_id!r} at Excel row {row_num}")
        seen_ids.add(book_id)

        reason = format_rejection_reasons(raw_reason)
        reason_counts["with_reason" if reason else "missing_reason"] += 1
        if " | " in reason:
            reason_counts["multiple_reasons"] += 1
        records.append(
            {
                "title": title,
                "author": "",  # Source has no author column.
                "date": convert_excel_date(excel_date, row_num),
                "publication_type": "",  # Source has no publication-type column.
                "rejection_reason": reason,
            }
        )

    if not header_seen or not records:
        raise ValueError("No usable data found in the source workbook")

    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with DESTINATION.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records):,} records to {DESTINATION}")
    print(f"Rejection reasons present: {reason_counts['with_reason']:,}")
    print(f"Rejection reasons missing: {reason_counts['missing_reason']:,}")
    print(f"Records with multiple rejection reasons: {reason_counts['multiple_reasons']:,}")
    if len(records) != BASELINE_RECORD_COUNT:
        print(
            f"Note: Source has {len(records):,} records; the April 2026 "
            f"reference workbook had {BASELINE_RECORD_COUNT:,}."
        )


if __name__ == "__main__":
    main()
