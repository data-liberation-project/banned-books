"""Clean the Illinois DOC "Adult Disapproved List" PDF.

The IDOC list is a print-formatted table - Title, Review Date, Volume #,
Publication # and Title Status - with no ruled gridlines, so pdfplumber
can't follow cell borders the way clean_virginia.py does. Cells are told
apart here by each word's x position on the page instead.

Long titles routinely run past the Title column's right edge and print
straight into the Review Date column with no separating space, in a few
dozen rows abutting the date itself ("...GUIDE FOR M07/25/2025"). Those
overflow characters are recovered back onto the title before the date
is read, rather than left glued to it or dropped.

Per instructions, Publication # and Title Status (every row reads
"Disapproved") are dropped from the output. Volume # is kept even though
it's not part of the shared schema, since for the many periodicals on
this list ("CLUB", "HUSTLER", "CHERI"...) it's the only thing that tells
one disapproved issue apart from another.

Usage:
    pip install pdfplumber
    python etl/clean_illinois.py

Writes data/processed/cleaned_illinois.csv
"""

import csv
import re
from pathlib import Path

import pdfplumber

RAW_PATH = Path("data/raw/illinois/illinois_disapproved_list.pdf")
OUT_PATH = Path("data/processed/cleaned_illinois.csv")

# Column boundaries in points, read off the header row's word positions:
# Title runs roughly 0-290, Review Date 290-360, Volume # 360-410.
# Publication # and Title Status, both dropped, start beyond 410.
TITLE_MAX = 290
DATE_MAX = 360
VOLUME_MAX = 410

# A genuine data row always carries its Title Status value ("Disapproved")
# printed at x0 ~= 493; the same word appears at x0 ~= 262 in the "Adult
# Disapproved List" banner repeated at the top of every page, and nowhere
# in the header row or the "Page X of 24" line. Requiring it this far
# right is what tells a real row apart from the surrounding page furniture.
STATUS_X0_MIN = 480

# A word that runs past the Title column and into the Review Date column
# prints with no space before the date ("...GUIDE FOR M07/25/2025"). Any
# word carrying a trailing date is split so the leading text rejoins the
# title and only the date itself is read as the Review Date.
GLUED_DATE_RE = re.compile(r"^(\D*)(\d{1,2}/\d{1,2}/\d{4})$")

# "ERO NINJA SCROLLS" is dated 09/15/2220 on both of its rows in the source
# - a keying error for 2020, the year every other row from the same review
# batch (volume 2, publication 9781648276729) carries.
DATE_FIXES = {"09/15/2220": "09/15/2020"}

FIELDNAMES = ["title", "author", "date", "publication_type", "rejection_reason", "volume"]


def squish(text):
    return re.sub(r"\s+", " ", text).strip()


def split_glued_date(word):
    """Return (leading_text, date) for a word, splitting off a trailing date."""
    match = GLUED_DATE_RE.match(word)
    return match.groups() if match else (word, "")


def parse_date(raw):
    """Convert a Review Date cell from MM/DD/YYYY to ISO 8601."""
    if not raw:
        return ""
    raw = DATE_FIXES.get(raw, raw)
    month, day, year = raw.split("/")
    return f"{year}-{int(month):02d}-{int(day):02d}"


def read_rows(pdf_path):
    """Yield the words of every genuine data row, page by page."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            rows = {}
            for word in page.extract_words():
                rows.setdefault(round(word["top"], 1), []).append(word)
            for row_words in rows.values():
                row_words.sort(key=lambda w: w["x0"])
                if any(
                    w["text"] == "Disapproved" and w["x0"] >= STATUS_X0_MIN
                    for w in row_words
                ):
                    yield row_words


def parse_row(row_words):
    """Return (title, date_raw, volume) for one data row's words."""
    title_words, date_word, volume_word = [], "", ""
    for word in row_words:
        x0, text = word["x0"], word["text"]
        if x0 >= VOLUME_MAX:
            continue  # Publication # and Title Status - dropped
        leading, glued_date = split_glued_date(text)
        if glued_date:
            date_word = glued_date
            text = leading
        if not text:
            continue
        if x0 < TITLE_MAX:
            title_words.append(text)
        elif x0 < DATE_MAX:
            date_word = text
        else:
            volume_word = text
    return squish(" ".join(title_words)), date_word, volume_word


def main():
    records = []
    for row_words in read_rows(RAW_PATH):
        title, date_raw, volume = parse_row(row_words)
        if not title:
            continue
        records.append(
            {
                "title": title,
                "author": "",
                "date": parse_date(date_raw),
                "publication_type": "",
                "rejection_reason": "",
                "volume": volume,
            }
        )

    records.sort(key=lambda r: (r["title"].lower(), r["date"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)

    dated = sum(1 for r in records if r["date"])
    print(f"total          {len(records):5d} records -> {OUT_PATH}")
    print(f"with a date    {dated:5d} ({dated / len(records):.1%})")


if __name__ == "__main__":
    main()
