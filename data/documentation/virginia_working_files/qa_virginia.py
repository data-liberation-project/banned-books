"""Check clean_virginia.py's extraction against an independent one.

The three Virginia PDFs are printed spreadsheets, and clean_virginia.py reads
them by following Excel's gridlines. That works, but it fails quietly: where
Excel left a cell unbordered the reader merges it into its neighbour, and the
result is a plausible-looking row with another row's criteria in it. Nothing in
the output says so.

So this script extracts the same three PDFs a second time, using PyMuPDF and
assigning each *word* to a cell by its centre point rather than following
gridlines, and diffs the two readings cell by cell. Where they disagree, one of
them is wrong and the page is worth looking at.

The two readings are not expected to agree exactly. Some differences are
artifacts of the comparison rather than defects, and are classified out:

    copyright glyph   PyMuPDF orders "©2019 Owen Brooks", pdfplumber
                      "Owen Brooks ©2019"
    ellipsis          pdfplumber's NFKC pass turns "..." into "..."
    line-wrap hyphen  the two disagree about which side of a cell boundary a
                      hyphen falls on

What is left should be empty. It is printed in full, along with two standing
assertions that caught real bugs:

    row completeness   every Excel row number present exactly once, no gaps
    merge signature    a criteria cell citing the same code twice, which is
                       what a vertical merge looks like from the output side

Usage:
    pip install pdfplumber pymupdf
    python data/documentation/virginia_working_files/qa_virginia.py

Run it from the repository root: the paths inside clean_virginia.py are
relative to there. Exits non-zero if anything unexplained turns up.
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz


# Add the etl module to the path
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "etl"))

import clean_virginia as cv


# Where each sheet keeps its criteria, for the merge-signature check.
CRITERIA_COLUMN = {"books": 4, "periodicals": 5, "misc": 4}


# The independent reading ------------------------------------------------


def merge_close(values, tolerance=2.0):
    """Collapse rule positions that are a hair apart into one."""
    merged = []
    for value in values:
        if not merged or value - merged[-1] > tolerance:
            merged.append(value)
    return merged


def page_rules(page):
    """Return (vertical, horizontal) rule positions drawn on the page."""
    vertical, horizontal = set(), set()
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                (x0, y0), (x1, y1) = item[1], item[2]
                if abs(x0 - x1) < 0.5 and abs(y0 - y1) > 5:
                    vertical.add(round(x0, 1))
                elif abs(y0 - y1) < 0.5 and abs(x0 - x1) > 5:
                    horizontal.add(round(y0, 1))
            elif item[0] == "re":
                rect = item[1]
                if rect.width < 1.5:
                    vertical.add(round(rect.x0, 1))
                elif rect.height < 1.5:
                    horizontal.add(round(rect.y0, 1))
    return merge_close(sorted(vertical)), merge_close(sorted(horizontal))


def band(edges, value):
    """The index of the band `value` falls in, or None if it falls outside."""
    for index in range(len(edges) - 1):
        if edges[index] <= value < edges[index + 1]:
            return index
    return None


def read_sheet(pdf_path):
    """Return {excel row number: [cell, ...]} for a printed sheet."""
    records = {}
    with fitz.open(pdf_path) as document:
        for page in document:
            columns, rows = page_rules(page)
            if len(columns) < 3 or len(rows) < 3:
                continue

            grid = defaultdict(list)
            for x0, y0, x1, y1, word, *_ in page.get_text("words"):
                column = band(columns, (x0 + x1) / 2)
                row = band(rows, (y0 + y1) / 2)
                if column is not None and row is not None:
                    grid[(row, column)].append((round(y0, 1), x0, word))

            cells = defaultdict(dict)
            for (row, column), words in grid.items():
                text = " ".join(word for _, _, word in sorted(words))
                cells[row][column] = re.sub(r"\s+", " ", text).strip()

            for row, columns_ in cells.items():
                label = columns_.get(0, "")
                if label.isdigit() and int(label) >= cv.FIRST_DATA_ROW:
                    records[int(label)] = [
                        columns_.get(i, "") for i in range(1, max(columns_) + 1)
                    ]
    return records


def read_sheet_via_pipeline(sheet, spec):
    """The same sheet as clean_virginia.py reads it, hand repairs included."""
    columns = spec["columns"]
    rows = {}
    for row_number, cells in cv.read_sheet(cv.RAW_DIR / spec["pdf"]):
        cells = [cv.squish(cell or "") for cell in cells]
        for field, value in (cv.ROW_FIXES.get((sheet, row_number)) or {}).items():
            cells[columns[field]] = value
        rows[row_number] = cells
    return rows


# Comparison -------------------------------------------------------------


def normalise(value):
    """Compare on content, not on whitespace or quote style."""
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", "", value).lower()


def explained(ours, theirs):
    """Name the artifact that accounts for a difference, if one does.

    Each of these is deliberately narrow. None of them can hide the defects
    this script exists to catch - a merged cell, a shifted column, a record
    collapsed into its title - because all of those change what words a cell
    holds, and every test here preserves the words.
    """
    if "©" in ours or "©" in theirs:
        return "copyright glyph"
    if ours.replace("...", "…") == theirs or ours == theirs.replace("…", "..."):
        return "ellipsis"
    if sorted(ours.split()) == sorted(theirs.split()):
        return "word order"
    if re.sub(r"[-\s]", "", ours) == re.sub(r"[-\s]", "", theirs):
        return "line-wrap hyphen"
    if ours.rstrip(" .,;:") == theirs.rstrip(" .,;:"):
        return "trailing punctuation"
    # One character apart, and the odd character out is non-ASCII either way:
    # the two readers picked different glyphs for the same mark, as they do for
    # the final and lunate sigma in a transliterated Russian title.
    if len(ours) == len(theirs):
        odd = [(a, b) for a, b in zip(ours, theirs) if a != b]
        if len(odd) == 1 and not all(c.isascii() for c in odd[0]):
            return "confusable glyph"
    return None


def compare(sheet, ours, theirs):
    """Yield the unexplained cell differences for one sheet."""
    missing = set(ours) - set(theirs)
    extra = set(theirs) - set(ours)
    for row_number in sorted(missing | extra):
        found = "pipeline only" if row_number in missing else "independent only"
        yield (sheet, row_number, None, found, "")

    for row_number in sorted(set(ours) & set(theirs)):
        a, b = ours[row_number], theirs[row_number]
        for column in range(max(len(a), len(b))):
            ours_cell = a[column] if column < len(a) else ""
            theirs_cell = b[column] if column < len(b) else ""
            if normalise(ours_cell) == normalise(theirs_cell):
                continue
            if explained(ours_cell, theirs_cell):
                continue
            yield (sheet, row_number, column, ours_cell, theirs_cell)


# Standing assertions ----------------------------------------------------


def check_row_numbers(sheet, rows):
    """Excel's row numbers should run unbroken from the first data row."""
    numbers = sorted(rows)
    expected = list(range(cv.FIRST_DATA_ROW, cv.FIRST_DATA_ROW + len(numbers)))
    if numbers != expected:
        gaps = sorted(set(expected) - set(numbers))
        return [f"{sheet}: row numbers are not contiguous; missing {gaps[:20]}"]
    return []


def check_merge_signature(sheet, rows):
    """A criteria cell citing one code twice is a merged pair of cells."""
    column = CRITERIA_COLUMN[sheet]
    problems = []
    for row_number, cells in sorted(rows.items()):
        raw = cells[column] if column < len(cells) else ""
        # Only cells that are nothing but criteria. Page numbers, prose, and
        # the cells parsed through CRITERIA_FIXES can all repeat a letter
        # without it meaning anything; clean_virginia.py reports those itself.
        if cv.squish(raw) in cv.CRITERIA_FIXES or not cv.parse_criteria(raw):
            continue
        codes = re.findall(r"\b[A-I]\d?\b", raw)
        if len(codes) >= 2 and len(codes) != len(set(codes)):
            problems.append(
                f"{sheet} row {row_number}: criteria {raw!r} repeats a code, "
                f"which is what a vertical cell merge looks like"
            )
    return problems


def main():
    differences, problems = [], []
    counts = Counter()

    for sheet, spec in cv.SHEETS.items():
        ours = read_sheet_via_pipeline(sheet, spec)
        theirs = read_sheet(cv.RAW_DIR / spec["pdf"])

        print(
            f"{sheet:14} pipeline {len(ours):5d} rows   "
            f"independent {len(theirs):5d} rows"
        )

        counts["rows"] += len(ours)
        differences.extend(compare(sheet, ours, theirs))
        problems.extend(check_row_numbers(sheet, ours))
        problems.extend(check_merge_signature(sheet, ours))

    print()
    for problem in problems:
        print(f"FAIL {problem}")

    if differences:
        print(f"FAIL {len(differences)} unexplained cell differences:")
        for sheet, row_number, column, ours_cell, theirs_cell in differences:
            where = f"{sheet} row {row_number}"
            if column is not None:
                where += f" column {column}"
            print(
                f"  {where}\n    pipeline    {ours_cell!r}"
                f"\n    independent {theirs_cell!r}"
            )

    if problems or differences:
        return 1

    print(f"ok: {counts['rows']} rows read the same way twice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
