"""Adversarial check of data/processed/cleaned_south_carolina.csv against its source.

etl/clean_south_carolina.py reads the PDF with PyMuPDF's table finder. This
script reads it a second, independent way: pdfplumber's words, grouped into
lines, with every left-column line assigned to the right-column cell (date or
"Disapproved") whose vertical centre is nearest. That is how a wrapped title
is rejoined without trusting anyone's table detection.

It then checks each CSV row against the cell it came from:
  - row count, order, and decision date;
  - lossless split: the letters and digits of title + marker ("by",
    "edited by") + author + reason, in that order, must equal the letters and
    digits of the source cell, so the split can drop only spaces and
    punctuation, never words, and cannot reorder anything;
  - the split happened at the last " by " and left none in the author;
  - a reason written "<code>: <policy text>" quotes that clause of the 2013
    policy PDF word for word (read here from the PDF, not from the ETL), and
    is reduced back to the bare code before the lossless check.

FAIL  the CSV disagrees with the source. Exits non-zero.
WARN  the CSV is faithful, but the split or the source row deserves a look.

Usage (from anywhere):
    pip install pdfplumber
    python data/documentation/south_carolina_working_files/qa_south_carolina.py
"""

import csv
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "data/raw/south_carolina/Records_for_Production_FOIA_0047-26.pdf"
CSV_PATH = REPO_ROOT / "data/processed/cleaned_south_carolina.csv"
POLICY_PDF = Path(__file__).with_name("PS-10-08_2015-09_wayback.pdf")  # May 1, 2013 edition
EXPANDED = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{1,2}): (.+?)(?: \| (.*))?")
FIELDS = ["title", "author", "date", "publication_type", "rejection_reason"]
FOOTER = re.compile(r"Records for Production FOIA 0047-26 \d+")
REASONISH = re.compile(r"(?i)explicit|nudity|\bnude\b|\bpgs?\.?\s*\d|\b\d{1,2}\.\d{1,2}\.\d{1,2}\b")

fails, warns = [], []


def alnum(s):
    return re.sub(r"[\W_]", "", s).lower()


def column_split(page, pn):
    """x of the drawn rule between the two columns: the middle of three rules."""
    xs = sorted({round(e["x0"]) for e in page.edges if e["orientation"] == "v"})
    groups = [x for i, x in enumerate(xs) if i == 0 or x - xs[i - 1] > 3]
    if len(groups) != 3:
        sys.exit(f"FAIL: page {pn} has column rules at {xs}, expected three")
    return groups[1]


def lines_of(page, split_x):
    """[(is_right_column, y_centre, text)] for each visual line."""
    # Group on the baseline (bottom): superscripts such as "3rd" sit higher at the top.
    words = sorted(page.extract_words(keep_blank_chars=False, use_text_flow=False),
                   key=lambda w: (round(w["bottom"]), w["x0"]))
    lines = []
    for w in words:
        side = w["x0"] >= split_x
        if lines and lines[-1]["side"] == side and abs(lines[-1]["bottom"] - w["bottom"]) < 2:
            lines[-1]["words"].append(w)
        else:
            lines.append({"side": side, "bottom": w["bottom"], "words": [w]})
    out = []
    for ln in lines:
        ws = sorted(ln["words"], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        centre = (min(w["top"] for w in ws) + max(w["bottom"] for w in ws)) / 2
        out.append((ln["side"], centre, text))
    return out


def read_source():
    rows = []
    with pdfplumber.open(SOURCE) as pdf:
        for pn, page in enumerate(pdf.pages, 1):
            lines = [l for l in lines_of(page, column_split(page, pn)) if not FOOTER.fullmatch(l[2])]
            rights = [(y, t) for side, y, t in lines if side]
            cells = {y: [] for y, _ in rights}
            for side, y, text in lines:
                if side:
                    continue
                if not rights:
                    fails.append(f"Page {pn}: title text with no date column: {text!r}")
                    continue
                nearest = min(rights, key=lambda r: abs(r[0] - y))
                if abs(nearest[0] - y) > 20:  # rows are ~15pt apart; wrapped cells centre their date
                    fails.append(f"Page {pn}: line {text!r} is {abs(nearest[0] - y):.0f}pt from any date")
                cells[nearest[0]].append((y, text))
            for y, when in rights:
                parts = [t for _, t in sorted(cells[y])]
                if not parts:
                    fails.append(f"Page {pn}: date {when!r} has no title")
                rows.append((pn, " ".join(parts), when))
    return rows


def policy_clauses():
    """{'19.1.4': clause text, ...} from section 19.1 of the 2013 policy PDF."""
    with pdfplumber.open(POLICY_PDF) as pdf:
        text = " ".join(p.extract_text() or "" for p in pdf.pages)
    if "ISSUE DATE: MAY 1, 2013" not in text:
        sys.exit("FAIL: policy PDF is not the May 1, 2013 edition of PS-10.08")
    section = text[text.rfind("19. CORRESPONDENCE REVIEW COMMITTEE"):]
    parts = re.split(r"(19\.1\.\d{1,2})(?=\s|[A-Z])", section)
    clauses = {}
    for code, body in zip(parts[1::2], parts[2::2]):
        # First occurrence is the clause; later ones are cross-references ("19.1.6 above").
        clauses.setdefault(code, " ".join(body.replace("•", " ").split()))
    return clauses


def expected_date(when):
    if when.strip().lower() == "disapproved":
        return ""
    m = re.fullmatch(r"\s*(\d+)[/.](\d+)[/.](\d+)\s*", when)
    if not m:
        fails.append(f"Unrecognised date cell {when!r}")
        return None
    mo, d, y = (int(g) for g in m.groups())
    return date(y + 2000 if y < 100 else y, mo, d).isoformat()


def main():
    rows = read_source()
    header = rows.pop(0)
    if (header[1], header[2]) != ("Title and Author", "Disapproved"):
        fails.append(f"Header row changed: {header}")

    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            fails.append(f"CSV header is {reader.fieldnames}, expected {FIELDS}")
        actual = list(reader)
    if len(actual) != len(rows):
        fails.append(f"Row count: CSV has {len(actual)}, source has {len(rows)}")

    clauses = policy_clauses()
    capital_by, odd_author, reasonish, multi_by = [], [], [], []
    for i, ((pn, cell, when), act) in enumerate(zip(rows, actual), start=1):
        where = f"CSV row {i} (page {pn})"
        if (exp := expected_date(when)) is not None and act["date"] != exp:
            fails.append(f"{where} date: source {when!r} -> {exp!r}, CSV {act['date']!r}")
        if act["publication_type"]:
            fails.append(f"{where} publication_type should be blank: {act['publication_type']!r}")

        title, author, reason = act["title"], act["author"], act["rejection_reason"]
        if m := EXPANDED.fullmatch(reason):
            code, quoted, note = m.groups()
            clause = clauses.get(code, "")
            rest = clause[len(quoted.rstrip(".")):] if clause.startswith(quoted.rstrip(".")) else None
            if rest is None or (rest and rest[0] not in ".;"):
                fails.append(f"{where} reason text for {code} does not match the 2013 policy:\n"
                             f"      CSV    {quoted!r}\n      policy {clause[:len(quoted) + 20]!r}")
            reason = f"{code} {note or ''}"  # back to what the source cell said
        elif re.search(r"\b\d{1,2}\.\d{1,2}\.\d{1,2}\b", reason):
            fails.append(f"{where} reason has a policy code but no policy text: {reason!r}")
        if not title:
            fails.append(f"{where} has an empty title (source {cell!r})")
        markers = ["by", "editedby", "editiedby"] if author else [""]
        if not any(alnum(cell) == alnum(title) + m + alnum(author) + alnum(reason) for m in markers):
            fails.append(f"{where} split lost or reordered text:\n      source {cell!r}\n      CSV    "
                         f"{title!r} | {author!r} | {reason!r}")
        if author and re.search(r"(?i)\sby\s", author):
            fails.append(f"{where} author still contains ' by ': {author!r}")
        if re.search(r";|\b\d{1,2}\.\d{1,2}\.\d{1,2}\b", author):
            fails.append(f"{where} author still holds a reason or policy code: {author!r}")
        if not author and re.search(r"(?i)\sby\s", cell):
            fails.append(f"{where} source has ' by ' but no author was split: {cell!r}")
        if reason and not author:
            fails.append(f"{where} has a reason but no author: {reason!r}")

        if author and not re.search(r"\sby\s", cell) and re.search(r"\sBy\s", cell):
            capital_by.append(f"{title!r} | {author!r}")
        if author and (len(author.split()) == 1 and not author[0].isupper() or "www." in author):
            odd_author.append(f"{title!r} | {author!r}")
        if len(re.findall(r"(?i)\sby\s", cell)) > 1:
            multi_by.append(cell)
        if REASONISH.search(title):
            reasonish.append(title)
        if re.match(r"[=+\-@]", title):
            warns.append(f"{where} title starts with {title[0]!r}; spreadsheets may treat it as a formula")

    undated = sum(1 for a in actual if not a["date"])
    dup = sum(n - 1 for n in Counter((a["title"].lower(), a["author"].lower()) for a in actual).values() if n > 1)
    if capital_by:
        warns.append(f"{len(capital_by)} splits on a capitalised ' By ' (check the title really ends there):\n      "
                     + "\n      ".join(capital_by))
    if odd_author:
        warns.append("Authors that look like publishers or sites: " + "; ".join(odd_author))
    if multi_by:
        warns.append(f"Cells with more than one ' by ' (split at the last): {multi_by}")
    if reasonish:
        warns.append(f"{len(reasonish)} titles still contain reason-like notes (kept, not split): {reasonish}")
    warns.append(f"{undated} rows have no date (source says only 'Disapproved')")
    if dup:
        warns.append(f"{dup} rows repeat an earlier title and author")

    print(f"Source rows: {len(rows)}   CSV rows: {len(actual)}")
    for w in warns:
        print("WARN:", w)
    for f_ in fails:
        print("FAIL:", f_)
    print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
