#!/usr/bin/env python3
"""Convert Rhode Island DOC's publication review tracking sheet to the project schema.

Source: data/raw/rhode_island/Publication_Review_Tracking_Sheet_-_APRA.xlsx
Output: data/processed/cleaned_rhode_island.csv

Install dependency: python -m pip install openpyxl
Run from anywhere:  python etl/clean_rhode_island.py

The sheet tracks every publication reviewed, approved or denied. Only denied
rows are kept. The date is the decision date written inside the "Decision &
Date" text (e.g. "Denied, 12-13-2018", "Denied 8-26-21", "Denied 2/1/22").
The source has no author, publication type or rejection reason, so those are
blank. The Facility column is not in the project schema and is dropped.
Repeat denials are kept as separate rows. The one "Inmate Letter" row is
dropped because it is not a publication. The inmate name, ID and
chain-of-custody columns are empty and not read.
"""

import csv
import re
from datetime import date
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data/raw/rhode_island/Publication_Review_Tracking_Sheet_-_APRA.xlsx"
DESTINATION = REPO_ROOT / "data/processed/cleaned_rhode_island.csv"

FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
EXPECTED_HEADERS = ("Facility", "Publication", "Date Rec'd", "Inmate Name",
                    "Inmate ID #", "Chain of Custody", "Decision & Date")
EXCLUDED_TITLES = {"Inmate Letter"}

# Tolerates the source's typos "Dennied" and "Appproved".
DENIED = re.compile(r"^\s*den+ied\b", re.I)
APPROVED = re.compile(r"^\s*ap+roved\b", re.I)
DECISION_DATE = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})\b")


def clean(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def decision_date(text: str, row_num: int) -> str:
    match = DECISION_DATE.search(text)
    if not match:
        raise ValueError(f"Row {row_num}: no date in decision {text!r}")
    month, day, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000  # Two-digit years in this sheet are all 20xx.
    return date(year, month, day).isoformat()


def main() -> None:
    sheet = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)["Sheet1"]
    rows = sheet.iter_rows(max_col=7, values_only=True)

    headers = tuple(clean(v) for v in next(rows))
    if headers != EXPECTED_HEADERS:
        raise ValueError(f"Source columns changed: {headers!r}")

    records, excluded = [], 0
    for row_num, row in enumerate(rows, start=2):
        facility, title, _received, *_pii, decision = (clean(v) for v in row)
        if not any((facility, title, decision)):  # facility only detects blank rows
            continue
        if APPROVED.match(decision):
            continue
        if not DENIED.match(decision):
            raise ValueError(f"Row {row_num}: decision is neither approved nor denied: {decision!r}")
        if not title:
            raise ValueError(f"Row {row_num}: denied row has no publication title")
        if title in EXCLUDED_TITLES:
            excluded += 1
            continue
        records.append({
            "title": title,
            "author": "",
            "date": decision_date(decision, row_num),
            "publication_type": "",
            "rejection_reason": "",
        })

    if excluded != len(EXCLUDED_TITLES):
        raise ValueError(f"Expected to exclude {len(EXCLUDED_TITLES)} row(s), excluded {excluded}")

    with DESTINATION.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records):,} records to {DESTINATION}")


if __name__ == "__main__":
    main()
