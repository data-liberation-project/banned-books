#!/usr/bin/env python3
"""Convert South Carolina DOC's disapproved-publications list to the project schema.

Source: data/raw/south_carolina/Records_for_Production_FOIA_0047-26.pdf
Output: data/processed/cleaned_south_carolina.csv

Install dependency: python -m pip install pymupdf
Run from anywhere:  python etl/clean_south_carolina.py

The PDF is a printed two-column Excel sheet: "Title and Author" and
"Disapproved" (the decision date). PyMuPDF's table finder reads one table per
page and rejoins titles that wrap onto two lines. The last 71 rows (pages
23-24) say "Disapproved" instead of a date; their date is left blank.

The left column is free text. It is split with these rules, nothing more:
  - author is whatever follows the last " by " (any case); a trailing
    "edited"/"editied" before it belongs to the author marker, not the title;
  - in that author part, text after a ";" or from a policy code such as
    "19.1.4" onward is the rejection reason (the code is kept in the reason);
  - cells without " by " are kept whole as the title, annotations included.
A policy code in the reason is written as "<code>: <policy text>", from SCDC
policy PS-10.08 (May 1, 2013 edition, in force when these codes were used;
copy in data/documentation/south_carolina_working_files/). Any other note in
the same reason follows after " | ". For 19.1.6 only the rule's first sentence
is used; the rest of that paragraph is definitions.
Publication type is not given and is left blank. Duplicates are kept.
"""

import csv
import re
from datetime import date
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data/raw/south_carolina/Records_for_Production_FOIA_0047-26.pdf"
DESTINATION = REPO_ROOT / "data/processed/cleaned_south_carolina.csv"

FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
EXPECTED_ROWS = 1026  # March 2026 production; a change means the source changed.

BY = re.compile(r"\s(?:edit(?:i)?ed\s+)?by\s", re.I)
REASON_START = re.compile(r"\s*;\s*|,?\s*(?=\b\d{1,2}\.\d{1,2}\.\d{1,2}\b)")
DATE = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2}|\d{4})")
CODE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{1,2})\s*(.*)")

# PS-10.08 (May 1, 2013), section 19.1: only the codes that appear in the source.
POLICY = {
    "19.1.4": "Materials that advocate racial, religious, or national hatred in such a way "
              "that could lead to the risk of physical violence or group disruption",
    "19.1.5": "Encouragement or instruction in the commission of criminal activity",
    "19.1.6": "Sexually explicit material, publications, or material that features nudity "
              "which by its nature or content poses a threat to the security, good order, "
              "or discipline of the institution, or which facilitates criminal activity.",
}


def squish(text: str) -> str:
    return " ".join(text.split())


def split_cell(cell: str) -> tuple[str, str, str]:
    """Return (title, author, rejection_reason) from one "Title and Author" cell."""
    cell = squish(cell)
    matches = list(BY.finditer(cell))
    if not matches:
        return cell, "", ""
    last = matches[-1]
    title, rest = cell[: last.start()], cell[last.end():]
    author, reason = rest, ""
    if (m := REASON_START.search(rest)) and m.start() > 0:
        author, reason = rest[: m.start()], rest[m.end():]
    return title.strip(" ;,-"), author.strip(" ;,"), expand_code(reason.strip())


def expand_code(reason: str) -> str:
    """'19.1.5 How to build a gun.' -> '19.1.5: <policy text> | How to build a gun.'"""
    m = CODE.fullmatch(reason)
    if not m:
        return reason
    code, note = m.groups()
    if code not in POLICY:
        raise ValueError(f"Policy code {code} has no text in POLICY; add it from PS-10.08")
    return f"{code}: {POLICY[code]}" + (f" | {note}" if note else "")


def parse_date(text: str, where: str) -> str:
    text = text.strip()
    if text.lower() == "disapproved":
        return ""
    m = DATE.fullmatch(text)
    if not m:
        raise ValueError(f"{where}: unexpected date cell {text!r}")
    month, day, year = (int(g) for g in m.groups())
    return date(year + 2000 if year < 100 else year, month, day).isoformat()


def main() -> None:
    records = []
    with pymupdf.open(SOURCE) as doc:
        for page_num, page in enumerate(doc, start=1):
            tables = page.find_tables().tables
            if len(tables) != 1:
                raise ValueError(f"Page {page_num}: expected one table, found {len(tables)}")
            for row_num, row in enumerate(tables[0].extract()):
                where = f"Page {page_num} row {row_num}"
                if len(row) != 2:
                    raise ValueError(f"{where}: expected 2 cells, got {row!r}")
                cell, when = (c or "" for c in row)
                if page_num == 1 and row_num == 0:
                    if (squish(cell), squish(when)) != ("Title and Author", "Disapproved"):
                        raise ValueError(f"Header changed: {row!r}")
                    continue
                if not squish(cell):
                    raise ValueError(f"{where}: no title")
                title, author, reason = split_cell(cell)
                records.append({
                    "title": title,
                    "author": author,
                    "date": parse_date(when, where),
                    "publication_type": "",
                    "rejection_reason": reason,
                })

    if len(records) != EXPECTED_ROWS:
        print(f"Note: {len(records):,} records; the March 2026 source had {EXPECTED_ROWS:,}.")
    with DESTINATION.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records):,} records to {DESTINATION}")


if __name__ == "__main__":
    main()
