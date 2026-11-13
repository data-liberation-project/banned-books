"""Adversarial check of data/processed/cleaned_california.csv against its source.

etl/clean_california.py reads the PDF's text lines with PyMuPDF, which drops
glyphs outside each page's clip, and starts a record wherever the reason
column begins "Title 15" (or one of two other openings). This script checks
it with a second, independent reading:

  - pdfplumber words, which ignore the clip, placed on one continuous strip
    (page index x 792 + top) so a line cut by a page break lines up with its
    copy on the next page; for each column the copy with the most text is kept;
  - records split by the table's drawn row borders: each row has a thin
    horizontal rule across the Publication column at its top, so the lines
    between two consecutive rules are one record. Neither text nor spacing
    plays any part in the split (spacing can't: a gap inside one record can
    be as wide as the gap between two).

Each reconstructed record must equal the CSV row (title, author, reason), in
order. Then it reports what a human should look at: truncated or irregular
reason text, duplicate rows, gaps too close to the split threshold.

FAIL  the CSV disagrees with the source. Exits non-zero.
WARN  the CSV is faithful, but the source deserves a look.

Usage (from anywhere):
    pip install pdfplumber
    python data/documentation/california_working_files/qa_california.py
"""

import csv
import re
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "data/raw/california/Disapproved Publications - Family & Friends Services.pdf"
CSV_PATH = REPO_ROOT / "data/processed/cleaned_california.csv"
FIELDS = ["title", "author", "date", "publication_type", "rejection_reason"]
PAGE = 792
COLUMN_EDGES = (100, 180, 260)
SAME_LINE = 1.5   # copies of one line across a page cut differ by ~0.1pt
SAME_RULE = 2.0   # a border is drawn as two edges 0.8pt apart, and repeated across a page cut
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})
OPENING = re.compile(r"(CCR, )?Title 15\b|Nudity – 12 consecutive issues")
STANDARD = re.compile(r"Title 15, Section 3006(\([A-Za-z0-9]+\))+ – \S.*")

fails, warns = [], []


def norm(s):
    return " ".join(s.translate(LIGATURES).split())


def join_cell(lines):
    out = ""
    for line in filter(None, map(norm, lines)):
        out += line if (not out or out.endswith("-")) else " " + line
    return out


def read_source():
    """Return (visual lines [(strip_y, {column: text})], row border strip_ys)."""
    words, edges = [], []
    with pdfplumber.open(SOURCE) as pdf:
        for i, page in enumerate(pdf.pages):
            if round(page.height) != PAGE:
                sys.exit(f"FAIL: page {i + 1} is {page.height}pt tall, expected {PAGE}")
            for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
                words.append((i * PAGE + w["top"], i, w["x0"], w["text"]))
            for r in page.rects:
                # A row border is a thin filled rectangle (0.8pt) across the
                # Publication column, x 24-105. Cell backgrounds and the white
                # page background are tall rectangles and are ignored.
                if r["height"] < 1.5 and r["x0"] <= 30 and 100 <= r["x1"] <= 110:
                    edges.append(i * PAGE + r["top"])
    edges.sort()
    rules = []
    for y in edges:
        if not rules or y - rules[-1] > SAME_RULE:
            rules.append(y)
    words.sort()
    clusters, current = [], []
    for w in words:
        if current and w[0] - current[0][0] > SAME_LINE:
            clusters.append(current)
            current = []
        current.append(w)
    clusters.append(current)

    lines = []
    for cluster in clusters:
        per = defaultdict(list)  # (column, page) -> words
        for _, page, x0, text in cluster:
            per[(sum(x0 >= e for e in COLUMN_EDGES), page)].append((x0, text))
        best = {}
        for (column, _), ws in per.items():
            text = norm(" ".join(t for _, t in sorted(ws)))
            if len(text.replace(" ", "")) > len(best.get(column, "").replace(" ", "")):
                best[column] = text
        lines.append((cluster[0][0], best))
    return lines, rules


def main():
    lines, rules = read_source()
    texts = [l[1] for l in lines[:3]]
    if texts != [{0: "Disapproved"}, {0: "Publications"},
                 {0: "Publication", 1: "Author", 2: "Publisher", 3: "Reason for Decision"}]:
        fails.append(f"Title/header changed: {texts}")
    body = lines[3:]

    groups = defaultdict(lambda: defaultdict(list))  # index of the rule above -> record
    for y, cols in body:
        above = bisect_right(rules, y) - 1
        if above < 0:
            fails.append(f"Text above the first row border: {cols}")
            continue
        for c, t in cols.items():
            groups[above][c].append(t)
    # The header row sits between the first two borders; it was taken off above.
    records = [groups[k] for k in sorted(groups)]
    empty_rows = sum(1 for a, b in zip(rules, rules[1:]) if b - a > 5) + 1 - len(groups) - 1

    expected = [{"title": join_cell(r[0]), "author": join_cell(r[1]),
                 "rejection_reason": join_cell(r[3])} for r in records]

    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            fails.append(f"CSV header is {reader.fieldnames}, expected {FIELDS}")
        actual = list(reader)
    if len(actual) != len(expected):
        fails.append(f"Row count: CSV has {len(actual)}, layout gives {len(expected)} records")

    for i, (exp, act) in enumerate(zip(expected, actual), start=1):
        for field in ("title", "author", "rejection_reason"):
            if exp[field] != act[field]:
                fails.append(f"Record {i} {field}:\n      source {exp[field]!r}\n      CSV    {act[field]!r}")
        if act["date"] or act["publication_type"]:
            fails.append(f"Record {i}: date/publication_type should be blank")
        if not exp["title"]:
            fails.append(f"Record {i} has no title in the source layout: {exp}")
        if not OPENING.match(exp["rejection_reason"]):
            fails.append(f"Record {i} reason has an unknown opening (split in the wrong place?): "
                         f"{exp['title']!r} | {exp['rejection_reason']!r}")

    # Things to look at, not errors -------------------------------------
    if empty_rows > 0:
        warns.append(f"{empty_rows} bordered rows hold no text (spacer or cut-off rows)")
    truncated = Counter(a["rejection_reason"] for a in actual
                        if re.search(r"safety of incarcerated\.?$", a["rejection_reason"]))
    if truncated:
        warns.append(f"{sum(truncated.values())} reasons end at 'incarcerated' (source text cut short): "
                     f"{list(truncated)}")
    irregular = Counter(a["rejection_reason"] for a in actual
                        if not STANDARD.fullmatch(a["rejection_reason"]))
    if irregular:
        warns.append(f"{sum(irregular.values())} reasons not in 'Title 15, Section 3006(..) – text' form:\n      "
                     + "\n      ".join(f"{n} x {r}" for r, n in irregular.most_common()))
    dup = sum(n - 1 for n in Counter(tuple(a[k] for k in FIELDS) for a in actual).values() if n > 1)
    if dup:
        warns.append(f"{dup} rows exactly repeat an earlier row")
    warns.append(f"{sum(1 for a in actual if not a['author'])} rows have no author")
    hyphen_joins = sum(len(re.findall(r"\w-\w", a["title"] + a["author"])) for a in actual)
    warns.append(f"{hyphen_joins} hyphenated words in titles/authors (line-end hyphens are kept and joined)")

    print(f"Layout records: {len(expected)}   CSV rows: {len(actual)}")
    for w in warns:
        print("WARN:", w)
    for f_ in fails[:40]:
        print("FAIL:", f_)
    if len(fails) > 40:
        print(f"... and {len(fails) - 40} more failures")
    print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
