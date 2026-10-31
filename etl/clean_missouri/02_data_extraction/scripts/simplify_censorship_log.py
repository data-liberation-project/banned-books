#!/usr/bin/env python3
"""Create the standardized five-column Missouri censorship-log dataset.

Called by the repository's etl/clean_missouri/run_pipeline.py after the PDF
has been repaired and reconstructed as a structured CSV. This script can also
be invoked directly with an input CSV and output CSV path, and requires only
the Python standard library.

For rejection_reason, concatenate these source columns IN THIS ORDER:
    Reason for Censorship
    Ryan Crews Number for Policy
    Jason Lewis Number for Policy
    Earl Dye Number for Policy

Empty entries are omitted. Repeated text is included only once (case-insensitive,
ignoring trailing punctuation). Distinct reasons are separated with ' | '.
No reasons are inferred from Justification/Comments.

DATE CAUTION: 'date' is the date the censorship letter was sent, which is NOT
necessarily the date the publication was reviewed or originally banned.

The source lacks explicit author and medium fields. 'author' is extracted only
from obvious 'by Author Name' title endings. 'publication_type' is classified
only from words in the title or issue information; otherwise left blank.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
import re

OUTPUT_COLS = ("title", "author", "date", "publication_type", "rejection_reason")
REASON_COLS = (
    "Reason for Censorship",
    "Ryan Crews Number for Policy",
    "Jason Lewis Number for Policy",
    "Earl Dye Number for Policy",
    "Justification/Comments"
)
REQUIRED = ("Title of Publication", "Volume/Issue Number", "Censorship Letters Sent Out Date", *REASON_COLS)
MEDIA_PATTERNS = (
    ("video", r"\b(?:dvd|vhs|blu[- ]?ray|video tapes?|videotapes?)\b"),
    ("audio", r"\b(?:audio\s*cd|music\s*cd|compact\s*disc|cd[- ]?rom|cd|cassette|vinyl record)\b"),
    ("newspaper", r"\bnewspapers?\b"),
    ("newsletter", r"\bnewsletters?\b"),
    ("magazine", r"\bmagazines?\b"),
    ("catalog", r"\b(?:catalogs?|catalogues?)\b"),
    ("comic", r"\b(?:comic books?|graphic novels?)\b"),
    ("pamphlet", r"\bpamphlets?\b"),
    ("calendar", r"\bcalendars?\b"),
    ("poster", r"\bposters?\b"),
    ("map", r"\b(?:maps?|atlases)\b"),
    ("book", r"\bbooks?\b"),
)


def tidy(value: str | None) -> str:
    """Collapse internal whitespace but otherwise preserve source wording."""
    return re.sub(r"\s+", " ", value or "").strip()

def date_from_source(value: str) -> str:
    value = tidy(value)
    value = re.sub(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*",
        "", value, flags=re.I,
    )
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return ""

def joined_reasons(row: dict[str, str]) -> str:
    """Join DISTINCT, NONEMPTY source cells in the requested column order."""
    reasons = []
    seen = set()
    for column in REASON_COLS:
        value = tidy(row.get(column))
        if not value:
            continue
        # Ignore capitalization and trivial final punctuation for duplicate
        # detection; keep the first occurrence's original wording in output.
        fingerprint = value.casefold().rstrip(";., ")
        if fingerprint not in seen:
            seen.add(fingerprint)
            reasons.append(value)
    return " | ".join(reasons)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_csv", type=Path, help="Reconstructed source CSV")
    parser.add_argument("output_csv", type=Path, help="Destination five-column CSV")
    args = parser.parse_args()

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    with args.input_csv.open(encoding="utf-8-sig", newline="") as source, \
         args.output_csv.open("w", encoding="utf-8-sig", newline="") as target:
        reader = csv.DictReader(source)
        missing = [column for column in REQUIRED if column not in (reader.fieldnames or ())]
        if missing:
            parser.error("Missing source columns: " + ", ".join(missing))
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLS)
        writer.writeheader()
        for source_row in reader:
            title = tidy(source_row.get("Title of Publication"))
            record = {
                "title": title,
                "author": "", ## not a data point in the original dataset 
                "date": date_from_source(source_row.get("Censorship Letters Sent Out Date", "")),
                "publication_type": "", ## not a data point in the original dataset
                "rejection_reason": joined_reasons(source_row),
            }
            writer.writerow(record)
            stats["rows"] += 1
            if not title:
                stats["missing_title"] += 1
            for column in OUTPUT_COLS:
                if record[column]:
                    stats[column] += 1
            if " | " in record["rejection_reason"]:
                stats["multiple_reasons"] += 1

    print(f"Wrote {stats['rows']:,} rows: {args.output_csv}")
    print("Nonempty values: " + ", ".join(f"{column}={stats[column]:,}" for column in OUTPUT_COLS))
    print(f"Multiple distinct reason entries: {stats['multiple_reasons']:,}")
    if stats["missing_title"]:
        print(f"WARNING: {stats['missing_title']:,} source rows lack a title")


if __name__ == "__main__":
    main()
