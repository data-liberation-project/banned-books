"""Extract Virginia's publication disapproval criteria to a plain CSV.

Virginia cites its reason for banning a publication as a code — A1, C3, D — in
the "Criteria" column of its disapproved publications lists. This script pulls
the definitions of those codes out of Operating Procedure 803.2, Incoming
Publications, and writes them to rejection_reasons.csv so that
etl/clean_virginia.py can turn each code into readable text.

The source is the January 1, 2015 edition of OP 803.2, whose "Specific Criteria
for Publication Disapproval" section lists the criteria in full. Later editions
moved the list into a separate Attachment 1 that VADOC does not publish, so this
edition is the one that documents the codes.

    virginia-publications.pdf   https://www.prisonpro.com/images/pdf/virginia-publications.pdf

Usage:
    python data/documentation/virginia_working_files/extract_criteria.py

Writes data/documentation/virginia_working_files/rejection_reasons.csv
"""

import csv
import re
from pathlib import Path

import pdfplumber

HERE = Path(__file__).resolve().parent
PDF_PATH = HERE / "virginia-publications.pdf"
OUT_PATH = HERE / "rejection_reasons.csv"

SECTION_START = "H. Specific Criteria for Publication Disapproval"
# The criteria run A through I; the section that follows also starts with "I.",
# so the list has to be closed on this heading rather than on a letter.
SECTION_END = "I. Disapproval of Non-English Language Publications"

# Printed page furniture that interrupts the list mid-criterion.
PAGE_FURNITURE = re.compile(
    r"^(?:Page \d+ of \d+|Operating Procedure: 803\.2|January 1, 2015)$"
)

CRITERION = re.compile(r"^([A-I])\.\s+(.*)")
SUB_CRITERION = re.compile(r"^(\d)\.\s+(.*)")
# Notes and rollout dates qualify a criterion rather than defining it.
QUALIFIER = re.compile(r"^(?:Note:|Implementation Plan)")


def read_section():
    """Return the lines of the criteria section, free of page furniture."""
    with pdfplumber.open(PDF_PATH) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    start = text.index(SECTION_START) + len(SECTION_START)
    end = text.index(SECTION_END, start)

    lines = []
    for line in text[start:end].splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and not PAGE_FURNITURE.match(line):
            lines.append(line)
    return lines


def parse_criteria(lines):
    """Walk the list, collecting each lettered criterion and its sub-items."""
    criteria = []  # (code, [text fragments])
    letter = None
    collecting = False

    for line in lines:
        if QUALIFIER.match(line):
            collecting = False
            continue

        match = CRITERION.match(line)
        if match:
            letter, text = match.groups()
            criteria.append((letter, [text]))
            collecting = True
            continue

        match = SUB_CRITERION.match(line)
        if match and letter:
            number, text = match.groups()
            criteria.append((f"{letter}{number}", [text]))
            collecting = True
            continue

        if collecting and criteria:
            criteria[-1][1].append(line)

    return [
        (code, re.sub(r"\s+", " ", " ".join(parts)).strip(" .:").replace("’", "'"))
        for code, parts in criteria
    ]


def main():
    criteria = parse_criteria(read_section())

    with OUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "description"])
        writer.writerows(criteria)

    print(f"{len(criteria)} criteria -> {OUT_PATH}")
    for code, description in criteria:
        print(f"  {code:3} {description[:70]}")


if __name__ == "__main__":
    main()
