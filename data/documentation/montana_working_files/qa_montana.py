"""Adversarial check of data/processed/cleaned_montana.csv against its source.

etl/clean_montana.py reads the workbook with openpyxl. This script does not
import it or openpyxl: it unzips the .xlsx and parses the sheet XML itself
(standard library only), then compares the CSV with that independent reading
cell by cell. The point is to catch what a single reader would hide: dropped
or invented rows, values changed in transit, dates shifted, data sitting
outside the columns the ETL reads, and rows that are suspect at the source.

FAIL  the CSV disagrees with the source, or the source has something the ETL
      silently ignores. Exits non-zero.
WARN  the CSV matches the source, but a human should look (normalisation the
      ETL applied, suspect source rows, provenance questions).

Usage (from anywhere):
    python data/documentation/montana_working_files/qa_montana.py
"""

import csv
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "data/raw/montana/Denied books_PHCF_February 2026.xlsx"
CSV_PATH = REPO_ROOT / "data/processed/cleaned_montana.csv"
SHEET = "Denied Book List"
HEADER_ROW = 4
FIELDS = ["title", "author", "date", "publication_type", "rejection_reason"]

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

fails, warns = [], []


def fail(msg):
    fails.append(msg)


def warn(msg):
    warns.append(msg)


# Independent reading of the workbook --------------------------------------


def text_of(node):
    """Concatenate <t> runs, skipping phonetic (<rPh>) annotations."""
    phonetic = {id(t) for ph in node.iter(M + "rPh") for t in ph.iter(M + "t")}
    return "".join(t.text or "" for t in node.iter(M + "t") if id(t) not in phonetic)


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group()
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def read_workbook():
    with ZipFile(SOURCE) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        if (pr := wb.find(M + "workbookPr")) is not None and pr.get("date1904") in ("1", "true"):
            fail("Workbook uses the 1904 date system; every date would be off by 4 years")
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheets = {}
        for s in wb.iter(M + "sheet"):
            target = rels[s.get(R + "id")].lstrip("/")
            path = target if target.startswith("xl/") else str(PurePosixPath("xl") / target)
            sheets[s.get("name")] = (path, s.get("state", "visible"))
        try:
            shared = [text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si")]
        except KeyError:
            shared = []
        parsed = {name: ET.fromstring(z.read(path)) for name, (path, _) in sheets.items()}
    return sheets, shared, parsed


def cells_of(root, shared):
    """{row: {col: (kind, value, has_formula)}} for every cell with a value."""
    rows = {}
    for row in root.iter(M + "row"):
        r = int(row.get("r"))
        for c in row.iter(M + "c"):
            t, v, f = c.get("t", "n"), c.find(M + "v"), c.find(M + "f") is not None
            if t == "inlineStr":
                val = text_of(c)
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            rows.setdefault(r, {})[col_index(c.get("r"))] = (t, val, f)
    return rows


def hidden_rows(root):
    return [int(r.get("r")) for r in root.iter(M + "row") if r.get("hidden") in ("1", "true")]


def serial_to_iso(serial):
    return (date(1899, 12, 30) + timedelta(days=int(serial))).isoformat()


def norm(s):
    return " ".join(s.split())


# Checks -------------------------------------------------------------------


def main():
    sheets, shared, parsed = read_workbook()

    if SHEET not in sheets:
        sys.exit(f"FAIL: sheet {SHEET!r} not found; sheets are {list(sheets)}")
    for name, (_, state) in sheets.items():
        if state != "visible":
            warn(f"Sheet {name!r} is {state}")
        if name != SHEET:
            n = sum(len(v) for v in cells_of(parsed[name], shared).values())
            header = " ".join(norm(v[1]) for v in cells_of(parsed[name], shared).get(2, {}).values())
            if n and re.search(r"title|book|publication|author", header, re.I):
                fail(f"Other sheet {name!r} looks like book data ({header!r}) but the ETL ignores it")
            elif n:
                warn(f"Other sheet {name!r} ignored ({n} cells; header: {header[:60]!r})")

    root = parsed[SHEET]
    grid = cells_of(root, shared)
    for r in hidden_rows(root):
        if r > HEADER_ROW and any(norm(v[1]) for v in grid.get(r, {}).values()):
            warn(f"Row {r} is hidden in Excel but has data (included in CSV)")

    header = [norm(grid.get(HEADER_ROW, {}).get(c, ("", "", False))[1]) for c in range(1, 5)]
    if header != ["Book Title", "Author", "Reason(s) for Denial", "Date"]:
        fail(f"Header row changed: {header}")
    for r in range(1, HEADER_ROW):
        stray = {c: v[1] for c, v in grid.get(r, {}).items() if norm(v[1])}
        if stray:
            fail(f"Row {r} (above header) has content the ETL skips: {stray}")

    # Build the expected CSV rows from the independent reading.
    expected = []
    for r in sorted(k for k in grid if k > HEADER_ROW):
        row = grid[r]
        get = lambda c: row.get(c, ("n", "", False))
        if any(get(c)[0] == "e" for c in range(1, 5)):
            fail(f"Row {r} has an Excel error value in A-D: {[get(c)[1] for c in range(1, 5)]}")
        for c, (t, v, _) in row.items():
            if c > 6 and norm(v):
                fail(f"Row {r} column {c} has content outside the table the ETL reads: {v!r}")
            if c == 6 and norm(v) and v != "#NAME?":
                fail(f"Row {r} column F has a real value, not the broken formula: {v!r}")
        title, author, reason, d = (get(c) for c in range(1, 5))
        if not any(norm(x[1]) for x in (title, author, reason, d)):
            if norm(get(5)[1]):
                fail(f"Row {r} has a Committee value but nothing in A-D; dropped by ETL")
            continue
        for label, cell in (("title", title), ("author", author), ("reason", reason)):
            if cell[0] not in ("s", "inlineStr", "str") and cell[1] != "":
                warn(f"Row {r} {label} is stored as a {cell[0]!r} cell: {cell[1]!r}")
        iso = ""
        if d[1] != "":
            if d[0] != "n":
                fail(f"Row {r} Date is text, not an Excel date: {d[1]!r}")
            else:
                serial = float(d[1])
                if serial != int(serial):
                    fail(f"Row {r} Date has a time component the CSV drops: {serial}")
                iso = serial_to_iso(serial)
        expected.append((r, {
            "title": title[1], "author": author[1], "date": iso,
            "publication_type": "", "rejection_reason": reason[1],
            "_committee": get(5)[1],
        }))

    # Compare with the CSV, row by row and in order.
    raw = CSV_PATH.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        warn("CSV starts with a UTF-8 BOM")
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            fail(f"CSV header is {reader.fieldnames}, expected {FIELDS}")
        actual = list(reader)

    if len(actual) != len(expected):
        fail(f"Row count: CSV has {len(actual)}, source has {len(expected)}")

    ws_changed = Counter()
    ws_examples = []
    for (r, exp), act in zip(expected, actual):
        for field in FIELDS:
            e, a = exp[field], act[field]
            if e == a:
                continue
            if norm(e) == a:
                ws_changed[field] += 1
                if e.strip() != a and len(ws_examples) < 8:
                    ws_examples.append(f"row {r} {field}: {e!r} -> {a!r}")
            else:
                fail(f"Row {r} {field}: source {e!r} != CSV {a!r}")

    # Source-side suspicion: the CSV is faithful, but are these rows right?
    for r, exp in expected:
        filled = [k for k in ("title", "author", "date", "rejection_reason") if norm(exp[k])]
        if filled == ["title"]:
            warn(f"Row {r} has only a title ({exp['title']!r}): possibly a name, not a book")
        if norm(exp["title"]).lower() == norm(exp["author"]).lower():
            warn(f"Row {r} title equals author: {exp['title']!r}")
        if exp["date"] and not ("2000-01-01" <= exp["date"] <= "2026-02-28"):
            warn(f"Row {r} date {exp['date']} is outside 2000 to Feb 2026")
        committee = norm(exp["_committee"])
        if committee and "denied" not in committee.lower():
            warn(f"Row {r} Committee is {committee!r}, which does not say denied")
        if "case by case" in committee.lower():
            warn(f"Row {r} Committee is {committee!r}: maybe not a blanket ban")
        if re.match(r"[=+\-@]", exp["title"].strip()):
            warn(f"Row {r} title starts with {exp['title'].strip()[0]!r}; spreadsheets may treat it as a formula")

    dup = Counter(tuple(norm(e[k]).lower() for k in FIELDS) for _, e in expected)
    for key, n in dup.items():
        if n > 1:
            warn(f"Exact duplicate rows x{n} (same title, author, date, reason): {key[0]!r}")
    by_title = Counter(norm(e["title"]).lower() for _, e in expected)
    multi = sorted(t for t, n in by_title.items() if n > 1)
    if multi:
        warn(f"{len(multi)} titles appear more than once with differing details: {multi}")

    with ZipFile(SOURCE) as z:
        path = re.search(rb'absPath url="([^"]+)"', z.read("xl/workbook.xml"))
    if path and b"PHCF" not in path.group(1).upper() and b"PINE" not in path.group(1).upper():
        warn(f"File is named PHCF but was last saved from {path.group(1).decode()!r}; "
             "confirm which facility this list belongs to")
    msp_mentions = [r for r, e in expected if re.search(r"\bMSP\b", e["rejection_reason"])]
    if msp_mentions:
        warn(f"Reasons mention MSP (Montana State Prison) in rows {msp_mentions}")

    # Report ---------------------------------------------------------------
    print(f"Source rows with data: {len(expected)}   CSV rows: {len(actual)}")
    if ws_changed:
        warn(f"ETL normalised whitespace (strip/collapse) in {dict(ws_changed)} cells; "
             f"internal-change examples: {ws_examples or 'none, only leading/trailing'}")
    for w in warns:
        print("WARN:", w)
    for f_ in fails:
        print("FAIL:", f_)
    print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
