"""Adversarial check of data/processed/cleaned_rhode_island.csv against its source.

etl/clean_rhode_island.py reads the workbook with openpyxl. This script does
not import it or openpyxl: it unzips the .xlsx, parses the sheet XML with the
standard library, decides independently which rows are denials, and compares
the CSV with that reading row by row. It also cross-checks each decision date
against the sheet's "Date Rec'd" and "Date Response to the Facility" columns,
which the ETL ignores, to catch dates mistyped in the source.

FAIL  the CSV disagrees with the source, or the source has something the ETL
      silently mishandles. Exits non-zero.
WARN  the CSV matches the source, but a human should look.

Usage (from anywhere):
    python data/documentation/rhode_island_working_files/qa_rhode_island.py
"""

import csv
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "data/raw/rhode_island/Publication_Review_Tracking_Sheet_-_APRA.xlsx"
CSV_PATH = REPO_ROOT / "data/processed/cleaned_rhode_island.csv"
FIELDS = ["title", "author", "date", "publication_type", "rejection_reason"]
EXCLUDED = {"inmate letter"}
# Columns: A Facility, B Publication, C Date Rec'd, D-F inmate/custody (PII),
# G Decision & Date, H Date Response to the Facility, I Comments.
PII_COLUMNS = {4: "Inmate Name", 5: "Inmate ID #", 6: "Chain of Custody"}

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

fails, warns = [], []


def text_of(node):
    phonetic = {id(t) for ph in node.iter(M + "rPh") for t in ph.iter(M + "t")}
    return "".join(t.text or "" for t in node.iter(M + "t") if id(t) not in phonetic)


def col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n


def read_sheet():
    """Return ({row: {col: (type, value)}}, sheet names) for the only sheet."""
    with ZipFile(SOURCE) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        if (pr := wb.find(M + "workbookPr")) is not None and pr.get("date1904") in ("1", "true"):
            fails.append("Workbook uses the 1904 date system")
        sheets = list(wb.iter(M + "sheet"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        target = rels[sheets[0].get(R + "id")].lstrip("/")
        path = target if target.startswith("xl/") else str(PurePosixPath("xl") / target)
        shared = [text_of(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si")]
        root = ET.fromstring(z.read(path))
    grid = {}
    for row in root.iter(M + "row"):
        for c in row.iter(M + "c"):
            t, v = c.get("t", "n"), c.find(M + "v")
            if t == "inlineStr":
                val = text_of(c)
            elif v is None or v.text is None:
                continue
            else:
                val = shared[int(v.text)] if t == "s" else v.text
            grid.setdefault(int(row.get("r")), {})[col_index(c.get("r"))] = (t, val)
        if row.get("hidden") in ("1", "true"):
            warns.append(f"Row {row.get('r')} is hidden in Excel")
    return grid, [s.get("name") for s in sheets]


def norm(s):
    return " ".join(s.split())


def classify(decision):
    """'denied' / 'approved' / None, by squeezing repeated letters in the first word."""
    first = re.sub(r"(.)\1+", r"\1", (re.findall(r"[a-z]+", decision.lower()) or [""])[0])
    return {"denied": "denied", "aproved": "approved"}.get(first)


def dates_in(text):
    out = []
    for m, d, y in re.findall(r"(\d+)[-/](\d+)[-/](\d+)", text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        out.append(date(y, int(m), int(d)))
    return out


def cell_date(cell):
    """A date from a numeric Excel cell or text like 'January 26,2021'; else None."""
    if cell is None:
        return None
    t, v = cell
    if t == "n":
        return date(1899, 12, 30) + timedelta(days=int(float(v)))
    try:
        return datetime.strptime(re.sub(r",\s*", ", ", norm(v)), "%B %d, %Y").date()
    except ValueError:
        found = dates_in(v)
        return found[0] if found else None


def main():
    grid, sheet_names = read_sheet()
    if len(sheet_names) != 1:
        fails.append(f"Expected one sheet, found {sheet_names}")

    expected, approved, excluded = [], 0, []
    for r in sorted(k for k in grid if k > 1):
        row = grid[r]
        val = lambda c: row.get(c, ("", ""))[1]
        if not any(norm(val(c)) for c in range(1, 10)):
            continue
        for c, (_, v) in row.items():
            if c > 9 and norm(v):
                fails.append(f"Row {r} column {c} has content beyond Comments: {v!r}")
        for c, name in PII_COLUMNS.items():
            if norm(val(c)):
                fails.append(f"Row {r} {name} is filled in; check before publishing (value withheld)")
        decision = norm(val(7))
        kind = classify(decision)
        if kind is None:
            fails.append(f"Row {r} decision is neither approved nor denied: {decision!r}")
            continue
        if kind == "approved":
            approved += 1
            continue
        title = norm(val(2))
        if title.lower() in EXCLUDED:
            excluded.append(r)
            continue

        found = dates_in(decision)
        if len(found) != 1:
            fails.append(f"Row {r} decision has {len(found)} dates: {decision!r}")
        decided = found[0] if found else None
        received, responded = cell_date(row.get(3)), cell_date(row.get(8))
        if decided and received and decided < received:
            warns.append(f"Row {r} {title!r}: decided {decided} before it was received {received}")
        if decided and received and (decided - received).days > 120:
            warns.append(f"Row {r} {title!r}: decided {decided}, {(decided - received).days} days after receipt")
        if decided and responded and not (0 <= (responded - decided).days <= 60):
            warns.append(f"Row {r} {title!r}: decided {decided} but response dated {responded}")
        if decided and not (date(2018, 1, 1) <= decided <= date(2026, 2, 28)):
            warns.append(f"Row {r} {title!r}: decision date {decided} is implausible")
        if decided and (y := re.search(r"\b(20\d\d)\b", title)) and int(y.group(1)) > decided.year:
            warns.append(f"Row {r} {title!r}: title names a year after the decision date {decided}")
        if norm(val(9)):
            warns.append(f"Row {r} {title!r} has a comment the CSV drops: {norm(val(9))!r}")
        expected.append((r, val(2), {
            "title": title, "author": "", "date": decided.isoformat() if decided else "",
            "publication_type": "", "rejection_reason": "",
            "_facility": norm(val(1)),  # not output; used for the duplicate check
        }))

    if len(excluded) != 1:
        fails.append(f"Expected exactly one excluded 'Inmate Letter' row, found rows {excluded}")

    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            fails.append(f"CSV header is {reader.fieldnames}, expected {FIELDS}")
        actual = list(reader)

    if len(actual) != len(expected):
        fails.append(f"Row count: CSV has {len(actual)}, source has {len(expected)} denials to keep")
    reshaped = 0
    for (r, raw_title, exp), act in zip(expected, actual):
        for field in FIELDS:
            if exp[field] != act.get(field):
                fails.append(f"Row {r} {field}: source {exp[field]!r} != CSV {act.get(field)!r}")
        if raw_title != act["title"]:
            reshaped += 1
    csv_titles = {norm(a["title"]).lower() for a in actual}
    if csv_titles & EXCLUDED:
        fails.append("The excluded Inmate Letter row is in the CSV")

    if reshaped:
        warns.append(f"ETL trimmed or collapsed whitespace in {reshaped} titles")
    dup = Counter((e["title"].lower(), e["date"]) for _, _, e in expected)
    for (title, d), n in dup.items():
        if n > 1:
            facs = sorted({e["_facility"] for _, _, e in expected if (e["title"].lower(), e["date"]) == (title, d)})
            warns.append(f"{title!r} denied {n} times on {d} ({', '.join(facs)}): "
                         "identical rows in the CSV; copies or separate issues?")

    print(f"Source: {len(expected) + len(excluded)} denied, {approved} approved, "
          f"{len(excluded)} excluded. CSV rows: {len(actual)}")
    for w in warns:
        print("WARN:", w)
    for f_ in fails:
        print("FAIL:", f_)
    print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
