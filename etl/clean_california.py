#!/usr/bin/env python3
"""Convert CDCR's disapproved-publications list to the project schema.

Source: data/raw/california/Disapproved Publications - Family & Friends Services.pdf
Output: data/processed/cleaned_california.csv

Install dependency: python -m pip install pymupdf
Run from anywhere:  python etl/clean_california.py

The PDF is a browser printout of one long web table (Publication, Author,
Publisher, Reason for Decision), cut into 792pt pages. Table detection fails
on it: a text line that straddles a cut is drawn, partly, on both pages
("NOVEL VOLUME TWO" / "dit" at the bottom of one page, "NOVEL,VOLUME TWO" /
"nudity" at the top of the next), and rows cut by a page are dropped.

So this script works from text lines instead:
  1. every line is placed on the continuous strip (page index x 792 + y);
  2. copies of a straddling line land at the same strip position; for each
     column the copy with the most text is kept;
  3. a record starts on a line whose reason column begins with a known
     opening ("Title 15", "CCR, Title 15", "Nudity – 12 consecutive issues");
     the following lines up to the next record belong to it.
Lines inside a cell are joined with a space, except after a line-ending
hyphen, which in this source is always a real hyphen (PIN-UPS, JULY-AUGUST).
Font ligatures (e.g. "ﬁ" in "scientiﬁc") are written as plain letters.

The source has no dates or publication types, so those columns are blank.
Publisher is not in the project schema and is dropped. Reasons are kept as
written: they already give the CCR Title 15 section and its wording.
Titles are kept in the source's capitals. Duplicates are kept.
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data/raw/california/Disapproved Publications - Family & Friends Services.pdf"
DESTINATION = REPO_ROOT / "data/processed/cleaned_california.csv"

FIELDS = ("title", "author", "date", "publication_type", "rejection_reason")
HEADER = ["Publication", "Author", "Publisher", "Reason for Decision"]
COLUMN_EDGES = (100, 180, 260)  # left edges of the columns are x=28, 108, 188, 268
RECORD_START = re.compile(r"(CCR, )?Title 15\b|Nudity – 12\b")  # first line of "Nudity – 12 consecutive issues – …"
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})  # PDF font ligatures
SAME_LINE = 1.0  # pt; copies of one line differ by ~0.1, lines in a cell are 7.6 apart
EXPECTED_RECORDS = 4264  # March 2026 printout; a change means the source changed.


def squish(text: str) -> str:
    return " ".join(text.translate(LIGATURES).split())


def join_lines(lines: list[str]) -> str:
    """Join cell lines; a line ending in '-' joins the next without a space."""
    text = ""
    for line in filter(None, map(squish, lines)):
        text += line if (not text or text.endswith("-")) else " " + line
    return text


def strip_lines():
    """Return the deduplicated visual lines: [{column index: text}] top to bottom."""
    found = []  # (strip y, column, page, x0, text)
    with pymupdf.open(SOURCE) as doc:
        for page_index, page in enumerate(doc):
            if round(page.rect.height) != 792:
                raise ValueError(f"Page {page_index + 1} is not 792pt tall")
            # Keep glyphs beyond the page edge: a line cut by a page break is
            # only complete if neither copy loses its outside characters.
            flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP
            for block in page.get_text("dict", clip=pymupdf.INFINITE_RECT(), flags=flags)["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"])
                    if not text.strip():
                        continue
                    x0, y0 = line["bbox"][0], line["bbox"][1]
                    column = sum(x0 >= edge for edge in COLUMN_EDGES)
                    found.append((page_index * 792 + y0, column, page_index, x0, text))

    found.sort()
    clusters, current = [], []
    for item in found:
        if current and item[0] - current[0][0] > SAME_LINE:
            clusters.append(current)
            current = []
        current.append(item)
    if current:
        clusters.append(current)

    visual = []
    for cluster in clusters:
        by_column_page = defaultdict(list)
        for _, column, page_index, x0, text in cluster:
            by_column_page[(column, page_index)].append((x0, text))
        best = {}
        for (column, _page), parts in by_column_page.items():
            text = squish(" ".join(t for _, t in sorted(parts)))
            if len(text.replace(" ", "")) > len(best.get(column, "").replace(" ", "")):
                best[column] = text
        visual.append(best)
    return visual


def main() -> None:
    visual = strip_lines()
    # The page title "Disapproved Publications" sits above the table header.
    if visual[:2] != [{0: "Disapproved"}, {0: "Publications"}]:
        raise ValueError(f"Page title changed: {visual[:2]!r}")
    header = [visual[2].get(c, "") for c in range(4)]
    if header != HEADER:
        raise ValueError(f"Header changed: {header!r}")

    records = []  # each: {column: [lines]}
    for row in visual[3:]:
        if RECORD_START.match(row.get(3, "")):
            if not row.get(0):
                raise ValueError(f"Record starts with no publication: {row!r}")
            records.append(defaultdict(list))
        elif not records:
            raise ValueError(f"Text before the first record: {row!r}")
        for column, text in row.items():
            records[-1][column].append(text)

    rows = [{
        "title": join_lines(r[0]),
        "author": join_lines(r[1]),
        "date": "",
        "publication_type": "",
        "rejection_reason": join_lines(r[3]),
    } for r in records]

    if EXPECTED_RECORDS and len(rows) != EXPECTED_RECORDS:
        print(f"Note: {len(rows):,} records; the March 2026 source had {EXPECTED_RECORDS:,}.")
    with DESTINATION.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} records to {DESTINATION}")


if __name__ == "__main__":
    main()
