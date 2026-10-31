#!/usr/bin/env python3
"""Extract North Carolina's disapproved-publications report to the banned-books schema.

Source: North Carolina Department of Adult Correction, "Disapproved
Publications Report (Bulletin Board Posting)", dated May 8, 2026.

Repository locations (relative to the repository root):
    Input:  data/raw/north_carolina/05_2026_Disapproved_Publication_List.pdf
    Output: data/processed/cleaned_north_carolina.csv

This script extracts the PDF's existing selectable text, without OCR. The
report contains a uniform, three-column table: Publication Name, Publication
Type, and Review Date. It does not supply authors or rejection reasons, so
those output columns are left blank rather than inferred.

Install dependency: python -m pip install pymupdf
Run from anywhere:   python etl/clean_north_carolina/clean_north_carolina.py
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF


INPUT_RELATIVE = Path("data/raw/north_carolina/05_2026_Disapproved_Publication_List.pdf")
OUTPUT_RELATIVE = Path("data/processed/cleaned_north_carolina.csv")
FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
KNOWN_PUBLICATION_TYPES = {"BOOK", "MAGAZINE", "PAMPHLET"}
DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
TOTAL_PATTERN = re.compile(r"(\d+)\s+matches\s+found", flags=re.IGNORECASE)


def locate_repository_root(script_file: Path) -> Path:
    """Find the repository via its data/raw/north_carolina directory.

    This makes paths independent of the shell's current working directory.
    """
    for directory in script_file.resolve().parents:
        if (directory / "data" / "raw" / "north_carolina").is_dir():
            return directory
    raise FileNotFoundError(
        "Cannot locate the repository. Create data/raw/north_carolina/ "
        "under the repository root and place the PDF there."
    )


def extract_records(pdf_path: Path) -> list[dict[str, str]]:
    """Read table rows using the PDF's text-block positions, not inferred metadata."""
    records: list[dict[str, str]] = []
    with fitz.open(pdf_path) as pdf:
        # The report itself states how many matching publications it contains.
        first_page_text = pdf[0].get_text()
        total_match = TOTAL_PATTERN.search(first_page_text)
        if total_match is None:
            raise ValueError("Could not find the 'N matches found' count on page 1.")
        expected_count = int(total_match.group(1))

        for page_number, page in enumerate(pdf, start=1):
            # Each publication appears in one text block with title, type,
            # and review date on separate lines. Keep the block's position:
            # the header and footer can otherwise appear among table entries.
            blocks = sorted(page.get_text("blocks"), key=lambda block: block[1])
            for block in blocks:
                x0, y0, _x1, _y1, block_text, _block_no, block_type = block
                if block_type != 0:
                    continue  # Images, not text.
                # In this report table rows start around x=39 and y>=97.
                # The repeated header is above the table; the footer starts
                # around x=76, even where it overlaps the bottom rows.
                if not (25 <= x0 <= 50 and y0 >= 95):
                    continue

                parts = [part.strip() for part in block_text.splitlines() if part.strip()]
                if len(parts) < 3:
                    raise ValueError(
                        f"Unexpected table row on PDF page {page_number}: {block_text!r}"
                    )
                # Join title fragments only if a title wraps across lines.
                title = " ".join(parts[:-2])
                publication_type, review_date = parts[-2:]
                if publication_type not in KNOWN_PUBLICATION_TYPES:
                    raise ValueError(
                        f"Unexpected publication type on page {page_number}: "
                        f"{publication_type!r}; title={title!r}"
                    )
                if not DATE_PATTERN.fullmatch(review_date):
                    raise ValueError(
                        f"Unexpected review date on page {page_number}: "
                        f"{review_date!r}; title={title!r}"
                    )
                date = datetime.strptime(review_date, "%m/%d/%Y").date().isoformat()
                records.append(
                    {
                        "title": title,
                        "author": "",  # Not included in the source report.
                        "date": date,  # Source's Review Date (not the report date).
                        "publication_type": publication_type,
                        "rejection_reason": "",  # Not included in the source report.
                    }
                )

    # Fail instead of silently writing a partial dataset if the report layout
    # changes or a title is missed. Preserve duplicate records from the source.
    if len(records) != expected_count:
        raise ValueError(
            f"Extracted {len(records)} entries, but the PDF reports "
            f"{expected_count} matches. Output not written."
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Override source PDF path")
    parser.add_argument("--output", type=Path, help="Override output CSV path")
    args = parser.parse_args()

    repository_root = locate_repository_root(Path(__file__))
    input_path = args.input or repository_root / INPUT_RELATIVE
    output_path = args.output or repository_root / OUTPUT_RELATIVE
    if not input_path.is_file():
        raise FileNotFoundError(f"Source PDF not found: {input_path}")

    records = extract_records(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    types = Counter(record["publication_type"] for record in records)
    print(f"Extracted {len(records)} records to {output_path}")
    print("Publication types: " + ", ".join(f"{name}={count}" for name, count in sorted(types.items())))
    print("Note: author and rejection_reason are blank because they are absent from the PDF.")


if __name__ == "__main__":
    main()
