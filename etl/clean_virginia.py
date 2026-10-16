"""Clean the Virginia DOC disapproved publications lists.

Virginia released its "Disapproved Publications List December 2010 - June 2025"
as three PDFs, each one an Excel sheet sent through "Microsoft: Print To PDF":

    Banned_Books.pdf              Title | Author | Date of Review | Page # | Criteria | Description
    Banned_Periodicals.pdf        Title | Issue  | Date of Review | Type | Page # | Criteria | (Description)
    Banned_Misc._Publications.pdf Title | Type   | Date of Review | Page # | Criteria | Description | Publisher | (unlabeled)

Because they are printed spreadsheets, the pages carry Excel's own gridlines,
column letters (A, B, C...) and row numbers. pdfplumber can follow those
gridlines, so the tables come out cleanly and every record can be tied back to
its spreadsheet row. The messiness is in the cell *values*, not the extraction:
dates are typed a couple hundred different ways, disapproval criteria are typed
in half a dozen shorthands, and a few hundred cells hold something other than
what their column header promises.

Usage:
    pip install pdfplumber
    python etl/clean_virginia.py

Writes data/processed/cleaned_virginia.csv
"""

import csv
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pdfplumber

RAW_DIR = Path("data/raw/virginia")
OUT_PATH = Path("data/processed/cleaned_virginia.csv")

# Follow the spreadsheet gridlines rather than guessing at whitespace, so that
# cells wrapped over several printed lines stay in one cell.
#
# Both sets of boundaries have to be supplied explicitly. Excel did not border
# every cell: on some pages the rule under a row stops short of the last
# columns, and on a few tall rows the column rules do not run the row's full
# height. Left to itself, pdfplumber finds no edge there and merges the cells -
# vertically, which moves one row's criteria onto another's, or horizontally,
# which collapses a whole record into its title. Feeding it the union of every
# rule on the page, however short, cuts every cell on all four sides.
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

# Row 1 is the sheet's banner, row 2 the header. Data starts at row 3.
FIRST_DATA_ROW = 3

# The three sheets, and where each one keeps a given field. Values are 0-based
# offsets into the row *after* the leading Excel row-number cell is dropped.
SHEETS = {
    "books": {
        "pdf": "Banned_Books.pdf",
        "columns": {
            "title": 0,
            "author": 1,
            "date": 2,
            "page_numbers": 3,
            "criteria": 4,
            "description": 5,
        },
        "default_type": "Book",
    },
    "periodicals": {
        "pdf": "Banned_Periodicals.pdf",
        "columns": {
            "title": 0,
            "issue": 1,
            "date": 2,
            "type": 3,
            "page_numbers": 4,
            "criteria": 5,
            # Column G carries the description; its header cell is blank.
            "description": 6,
        },
        "default_type": "Periodical",
    },
    "misc": {
        "pdf": "Banned_Misc._Publications.pdf",
        "columns": {
            "title": 0,
            # Header calls column B "Type", but it holds a type only about 7% of
            # the time; otherwise it is an issue, an author or a subtitle.
            "type_or_issue": 1,
            "date": 2,
            "page_numbers": 3,
            "criteria": 4,
            "description": 5,
            # Columns G and H are strays: G is headed "Publisher" but rarely
            # holds one, and H has no header at all. Kept verbatim as notes.
            "notes": [6, 7],
        },
        "default_type": "Miscellaneous Publication",
    },
}

# Hand repairs for what the gridlines cannot resolve, in the spirit of the
# manual_changes tribble in clean_new_jersey.R. Keyed by (sheet, Excel row).
ROW_FIXES = {
    # This description is longer than its cell is tall, so it overflows the
    # bottom border and the tail of the sentence is read as the next row's
    # description - crediting Squeeze Magazine with a note about Sportsform:
    # Basketball. Checked against page 129 of the printout.
    ("periodicals", 3066): {
        "description": "Story: Jay Z's Wayne Perry Flow. WAYNE Perry was hit "
        "man now serving 5 life",
    },
    ("periodicals", 3067): {"description": ""},
}


# Cell text --------------------------------------------------------------


def squish(value):
    """Collapse a wrapped cell into one line of text."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).replace(" ", " ")
    # Excel wraps on word boundaries, so a line ending in "-" is a hyphenated
    # word split across lines ("Inter-\nCommunal"), not two words.
    text = re.sub(r"-\s*\n\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


# Excel keeps a date as a count of days from 1899-12-30. Where an issue was
# typed as a date, the cell holds that count and the printout shows it raw:
# Rolling Stone "42117" is the 23 April 2015 issue. The window below covers the
# issue dates these lists could plausibly cite; no real issue *number* in the
# source runs to five figures, so nothing genuine is caught by it.
EXCEL_EPOCH = date(1899, 12, 30)
SERIAL_MIN, SERIAL_MAX = 36526, 46022  # 2000-01-01 to 2025-12-31


def decode_excel_serial(value):
    """Return the date an Excel day count stands for, or "" if it isn't one.

    The original precision is gone for good: "October 2012" and "10/1/2012"
    both serialize to 41183, and both come back as 2012-10-01.
    """
    text = value.strip()
    if not text.isdigit() or not SERIAL_MIN <= int(text) <= SERIAL_MAX:
        return ""
    return (EXCEL_EPOCH + timedelta(days=int(text))).isoformat()


# Dates ------------------------------------------------------------------

# The lists run December 2010 - June 2025. Anything outside that window is a
# typo in the source ("10/14/2002", "5/1/2107") rather than a real review date,
# and is dropped in favour of leaving date blank.
MIN_YEAR, MAX_YEAR = 2010, 2025

MONTHS = {
    "jan": 1,
    "january": 1,
    "janaury": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "augus": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "novemeber": 11,
    "dec": 12,
    "december": 12,
}

# VADOC facilities that were typed into the "Date of Review" column, sometimes
# instead of a date and sometimes alongside one ("Augusta April, 2013").
FACILITIES = [
    "Augusta",
    "Baskerville",
    "Bland",
    "Buckingham",
    "Caroline",
    "Coffeewood",
    "Deerfield",
    "Dillwyn CC",
    "Dillwyn",
    "Fluvanna",
    "Green Rock",
    "Greensville",
    "Halifax",
    "Haynesville",
    "Indian Creek",
    "Keen Mountain",
    "Lunenburg",
    "Marion",
    "Nottoway",
    "Pocahontas",
    "Powhatan",
    "Red Onion",
    "River North",
    "RNCC",
    "SBCC",
    "St. Brides",
    "Sussex II",
    "Sussex I",
    "Sussex ll",
    "Sussex Il",
    "Sussex 1",
    "SXI",
    "Wallens Ridge",
    "WRSP",
]
FACILITY_RE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(re.escape(f) for f in FACILITIES) + r")(?![A-Za-z])",
    re.IGNORECASE,
)
# Canonical spelling for the variants above.
FACILITY_CANONICAL = {
    "dillwyn cc": "Dillwyn",
    "rncc": "River North",
    "sbcc": "St. Brides",
    "sxi": "Sussex I",
    "sussex 1": "Sussex I",
    "sussex ll": "Sussex II",
    "sussex il": "Sussex II",
    "wrsp": "Wallens Ridge",
}

# One-off repairs. Values mapped to "" are unrecoverable typos: "2/12/20201"
# could be 2020 or 2021, and "12/16" gives no year at all.
DATE_FIXES = {
    "May 29. 2 012": "May 29 2012",
    "N o v e m ber 2014": "November 2014",
    "2/12/20201": "",
    "12/16": "",
    "-": "",
}

MONTH_WORD = r"[A-Za-z]+"


def split_facility(raw):
    """Pull any facility names out of a Date of Review cell."""
    facilities, seen = [], set()
    for match in FACILITY_RE.finditer(raw):
        name = FACILITY_CANONICAL.get(match.group(1).lower(), match.group(1))
        if name not in seen:
            seen.add(name)
            facilities.append(name)
    remainder = squish(FACILITY_RE.sub(" ", raw).strip(" ,/.-"))
    return "; ".join(facilities), remainder


def _iso(year, month=None, day=None):
    """Format to the precision we actually have: YYYY, YYYY-MM or YYYY-MM-DD."""
    if not MIN_YEAR <= year <= MAX_YEAR:
        return ""
    if month is None:
        return f"{year:04d}"
    if not 1 <= month <= 12:
        return ""
    if day is None:
        return f"{year:04d}-{month:02d}"
    if not 1 <= day <= 31:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_date(raw):
    """Return (iso_date, facility) for a Date of Review cell.

    The date is given to whatever precision the source offers, so "2/10/2020"
    becomes 2020-02-10 while "December 2018" becomes 2018-12. Cells that hold
    no recoverable date at all come back empty.
    """
    facility, text = split_facility(squish(raw))
    text = DATE_FIXES.get(text, text)
    if not text:
        return "", facility
    text = text.strip(" .,")

    def month_of(word):
        return MONTHS.get(word.strip(" .,").lower())

    # 2/10/2020, 12/16/20, and the missing-slash typos 10/112024 and 3/82023.
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})[/ ]?(\d{2}|\d{4})", text)
    if m:
        month, day, year = (int(g) for g in m.groups())
        return _iso(year + 2000 if year < 100 else year, month, day), facility

    # 7//2021 - month typed, day missing.
    m = re.fullmatch(r"(\d{1,2})//(\d{4})", text)
    if m:
        return _iso(int(m.group(2)), int(m.group(1))), facility

    # Excel's mmm-yy (Apr-22) and yy-mmm (24-Apr) formats.
    m = re.fullmatch(rf"({MONTH_WORD})-(\d{{2}})", text)
    if m and month_of(m.group(1)):
        return _iso(2000 + int(m.group(2)), month_of(m.group(1))), facility
    m = re.fullmatch(rf"(\d{{2}})-({MONTH_WORD})", text)
    if m and month_of(m.group(2)):
        return _iso(2000 + int(m.group(1)), month_of(m.group(2))), facility

    # Month D, YYYY in all its punctuation variants, including the glued-up
    # "July. 152011" and "Sept. 62011".
    m = re.fullmatch(rf"({MONTH_WORD})\.?,?\s*(\d{{1,2}})\.?,?\s*(\d{{4}})", text)
    if m and month_of(m.group(1)):
        return _iso(int(m.group(3)), month_of(m.group(1)), int(m.group(2))), facility
    m = re.fullmatch(rf"({MONTH_WORD})\.?\s*(\d{{1,2}})(\d{{4}})", text)
    if m and month_of(m.group(1)):
        return _iso(int(m.group(3)), month_of(m.group(1)), int(m.group(2))), facility

    # Jan/Feb 2014, Sept/Oct 2013, May 2017- June 2017: a range of months. We
    # keep the first, which is when the review window opened.
    m = re.fullmatch(rf"({MONTH_WORD})\s*/\s*({MONTH_WORD})\.?,?\s*(\d{{4}})", text)
    if m and month_of(m.group(1)):
        return _iso(int(m.group(3)), month_of(m.group(1))), facility
    m = re.match(rf"({MONTH_WORD})\.?,?\s*(\d{{4}})\s*-", text)
    if m and month_of(m.group(1)):
        return _iso(int(m.group(2)), month_of(m.group(1))), facility

    # December 2018, "April, 2013", "August 2013.", "2015 September".
    m = re.fullmatch(rf"({MONTH_WORD})\.?,?\s*(\d{{4}})", text)
    if m and month_of(m.group(1)):
        return _iso(int(m.group(2)), month_of(m.group(1))), facility
    m = re.fullmatch(rf"(\d{{4}})\s+({MONTH_WORD})", text)
    if m and month_of(m.group(2)):
        return _iso(int(m.group(1)), month_of(m.group(2))), facility

    m = re.fullmatch(r"(\d{4})", text)
    if m:
        return _iso(int(m.group(1))), facility

    # Anything left is a bare month name, a stray description, or garbage.
    return "", facility


# Criteria ---------------------------------------------------------------

# Criteria are cited in a shorthand where the letter carries over: "A1, 2, 3"
# means A1, A2, A3, and "C5, 6" means C5, C6. Ranges appear as "A1-4".
CRITERIA_TOKEN = re.compile(
    r"""^(?:
        (?P<letter>[A-Z])[-\s]?(?P<num>\d+)(?:-(?P<to>\d+))?   # A1, C-4, A1-4
        |(?P<bare>[A-Z])                                        # D
        |(?P<num_only>\d+)(?:-(?P<num_to>\d+))?                 # 2, 1-4
    )$""",
    re.VERBOSE,
)

# Cells where a citation is real but buried - in prose, or behind another
# sheet's page references. Everything else the parser turns down is genuinely
# not a citation, and is reported at the end of a run rather than guessed at.
CRITERIA_FIXES = {
    "EECL 12-14, EECL 18-20, EECL 28 A1": "A1",
    "EECLN 128-136, EECL 147, 154, 169 A1": "A1",
    "Criteria F for all offenders (Criteria E for offender F. Hardy 1149135)": "F, E",
}


def describe_criteria(codes, descriptions, unknown):
    """Turn "A1, I" into the criteria text Virginia disapproved the title under."""
    reasons = []
    for code in filter(None, codes.split(", ")):
        text = descriptions.get(code)
        if text:
            if text not in reasons:
                reasons.append(text)
        else:
            # Codes the procedure doesn't define: "A11", "D7", "J1" and friends
            # are keying errors, since A stops at 5 and D has no sub-items.
            unknown[code] += 1
    return reasons


def parse_criteria(raw):
    """Expand the criteria shorthand into a comma-separated list of codes.

    Returns "" when the cell holds anything that is not purely criteria codes -
    a handful of cells contain page numbers, a publication type, or a sentence,
    and guessing at those would invent citations that Virginia never made.
    """
    text = squish(raw)
    if not text:
        return ""
    text = CRITERIA_FIXES.get(text, text)

    codes, letter = [], None
    for token in re.split(r"[,\s]+", text):
        token = token.strip("().-")
        if not token:
            continue
        match = CRITERIA_TOKEN.match(token)
        if not match:
            return ""  # not a pure criteria cell; better blank than invented
        groups = match.groupdict()
        if groups["bare"]:
            letter = groups["bare"]
            codes.append(letter)
            continue
        if groups["letter"]:
            letter = groups["letter"]
            start, end = int(groups["num"]), groups["to"]
        else:
            if letter is None:
                return ""  # a number with no letter to attach it to
            start, end = int(groups["num_only"]), groups["num_to"]
        for number in range(start, int(end) + 1 if end else start + 1):
            codes.append(f"{letter}{number}")

    deduped = list(dict.fromkeys(codes))
    return ", ".join(deduped)


# Authors ----------------------------------------------------------------

# A copyright year is tacked onto about a third of the author cells, either
# marked ("Owen Brooks ©2019", "Nikki Turner @2003", "Dark House Copyright
# 2018", "2014 / Tristan Taormino") or just appended ("Terry Moore 2022").
COPYRIGHT_MARKED = re.compile(
    r"""(?:©|@|\(c\)|\bcopyright\b)\s*(?:19|20)\d{2}""", re.IGNORECASE
)
COPYRIGHT_LEADING = re.compile(r"^\s*(?:19|20)\d{2}(?:-(?:19|20)?\d{2})?\s*[/,]?\s*")
COPYRIGHT_TRAILING = re.compile(r"\s*(?:19|20)\d{2}(?:-(?:19|20)?\d{2})?\s*$")
# What's left once the year goes: a bare year, a range, stray punctuation. The
# surrounding text must be free of digits too, or an issue designator would be
# swallowed along with the year ("#3 2012" is an issue, not a bare copyright).
NO_AUTHOR_LEFT = re.compile(
    r"^[^A-Za-z0-9]*(?:19|20)\d{2}(?:\s*-\s*(?:19|20)?\d{2})?[^A-Za-z0-9]*$"
)

# "Oct. 2012" and "December 2015" are publication dates, not copyright years:
# the year is the only thing in the cell that carries meaning, so leave it.
MONTH_YEAR_END = re.compile(
    r"\b(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b"
    r"\.?,?\s*(?:19|20)\d{2}\s*$",
    re.IGNORECASE,
)


def strip_copyright_year(author):
    """Drop the copyright year from an author cell.

    Cells that hold nothing but a year ("2014", "*1941", "©2021") come back
    empty, since removing the year leaves no author behind.
    """
    if not author:
        return ""
    cleaned = COPYRIGHT_MARKED.sub(" ", author)
    if NO_AUTHOR_LEFT.match(cleaned.strip()):
        return ""
    cleaned = COPYRIGHT_LEADING.sub("", cleaned)
    # A trailing year is only a copyright year when the cell has no issue
    # material beside it. Where it does, the year dates that issue, and
    # split_issue_from_author moves the pair across together. (has_designator
    # is defined below, with the patterns it consults.)
    if not MONTH_YEAR_END.search(cleaned) and not has_designator(cleaned):
        cleaned = COPYRIGHT_TRAILING.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Leave a name's own punctuation alone ("Ian Kerner, Ph.D.") but clear any
    # separator the year left stranded.
    cleaned = re.sub(r"\s*[,;:/*©-]+\s*$", "", cleaned)
    return cleaned.strip(" ,;:/*©-")


# A good number of author cells are not authors at all but volume and issue
# designators, sometimes alone ("Vol 4, 5, 6", "#27, #28") and sometimes tacked
# onto a real name ("Akira Hizuki Vol 1", "Vol 1 Brick & Storm").
# The leading \b matters: without it "Nishino 2009" reads as issue "no 2009".
ISSUE_TOKEN = re.compile(
    r"(?:\b(?i:vols?|volumes?|issues?|nos?|tomes?|parts?)\b\.?,?\s*#?\s*"
    r"(?:\d+|[IVXLC]{1,7}\b)(?:[.\-/,&\s]+#?\d+)*"
    r"|#\s*\d+(?:[,&\-\s]+#?\d+)*)"
)

# Serial titles number their instalments in Roman numerals, and the number lands
# in the author column: "Letters To Penthouse" / "XXXVI". The periodicals sheet
# files exactly these values under Issue, which is where they belong. Note the
# source uses non-standard forms ("XXXX", "XXXXVIII"), so this matches the
# characters rather than validating the numeral.
ROMAN_ONLY = re.compile(r"[IVXLC]{1,9}")
# A numeral this long can only be a number; shorter runs are initials and words
# ("C E Case", "I & II Devlin O'Neil", "I Heart Monster Girls 4").
ROMAN_LEAD = re.compile(r"[IVXLC]{3,9}\s+\S")

# An ISBN tacked onto the author credit ("Sylvia Day ISBN 9780425273869").
# The issue column already carries ISBNs elsewhere in the source, so that is
# where they belong. Some are letter-prefixed or hyphenated.
ISBN_TOKEN = re.compile(r"\bISBN\b[\s:]*[A-Z]?\d[\d\-Xx]*", re.IGNORECASE)

# Edition statements, which land in the author column the same way.
# "Ed" is only an edition when an ordinal precedes it ("Barron's 10th Ed"):
# on its own it is nearly always a name or an editor credit in this data
# ("Ed Wheat & Gaye Wheat", "ED. Henk Schiffmacher", "John T. Moore Ed.D").
ORDINALS = (
    r"\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth"
    r"|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth"
    r"|seventeenth|eighteenth|nineteenth|twentieth"
)
EDITION_TOKEN = re.compile(
    r"(?i:(?:(?:" + ORDINALS + r"|revised|updated|expanded|new|anniversary"
    r"|international|chinese|english|american|u\.?s\.?|year|\d+(?=\s+year)"
    r"|and|&)[\s,]+)*editions?\b\.?(?:\s*\d+)?"
    r"|(?:" + ORDINALS + r")\s+ed\b\.?)"
)


def has_designator(text):
    """Whether a cell carries volume, edition or ISBN material."""
    return any(
        pattern.search(text) for pattern in (ISSUE_TOKEN, EDITION_TOKEN, ISBN_TOKEN)
    )


# When a volume number is present, any date sitting beside it belongs with it
# ("Ken Akamatsu Vol 4 Jan. 2005") rather than with the author.
DATEISH = re.compile(
    r"\b(?:"
    + "|".join(sorted(MONTHS, key=len, reverse=True))
    + r"|spring|summer|fall|autumn|winter)\b\.?,?\s*(?:(?:19|20)\d{2})?"
    r"|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)

# Titles whose author column holds a series or instalment name rather than an
# author. Checked against the whole title, never a prefix: "Monster Musume" has
# its subtitle in the author column, but "Monster Musume Everyday Life of..."
# and "Monster Musume I Heart Monster G..." correctly name Okayado and Kenkou
# Cross, who must be left alone.
ISSUE_AS_AUTHOR_TITLES = {
    "advanced d&d",
    "barbarella",
    "black book mini",
    "cum for me",
    "goat foreplay",
    "jump comics",
    "licks",
    "magic, the gathering",
    "monster musume",
    "oxford comprehensive atlas of the world",
}

# Instalment names on titles that elsewhere carry a genuine credit, so they
# cannot be moved by title: "Letters to Penthouse" is variously credited to
# "Back Door Adventures" and to Barbara Pizio, who is a real editor.
ISSUE_AS_AUTHOR_VALUES = {
    "back door adventures",
    "horny milfs and cougars",
    "she's wild! she's horny! she's married?",
}

# Titles crediting the instalment number in front of the author's own name:
# Gantz is credited "25 Hiroya Oku Works" for volume 25 by Hiroya Oku.
NUMBER_THEN_AUTHOR_TITLES = {"gantz"}
NUMBER_THEN_AUTHOR = re.compile(r"^(\d+)\s+(.+?)(?:\s+works)?$", re.IGNORECASE)

# Words that don't make a remainder an author on their own.
FILLER_WORDS = {
    "a",
    "al",
    "an",
    "and",
    "by",
    "et",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


# Typed where there is no author; an empty cell says the same thing.
NULL_AUTHORS = {"none"}

# A leading "by" is a credit marker, not part of the name. Only at the start:
# "edited by Jane Little" and "Story & Art by Reiji Suzumaru" keep theirs.
LEADING_BY = re.compile(r"^by\s+", re.IGNORECASE)


def tidy_author(author):
    """Drop a "By " prefix, and empty out a placeholder like "none"."""
    author = LEADING_BY.sub("", author).strip()
    return "" if author.strip(" .").lower() in NULL_AUTHORS else author


# What an author cell may lose on the way out: copyright years, credit markers,
# the "Works" in Gantz's "25 Hiroya Oku Works", the "none" placeholder.
DROPPABLE_AUTHOR_WORDS = {"by", "c", "copyright", "none", "works"}


def author_content_lost(raw, author, issue):
    """Whether any of the author cell reached neither `author` nor `issue`.

    Two bugs showed up as cells that were emptied rather than moved, so this
    runs on every row and reports what it finds. It is a check, not a repair.
    """

    def content(text):
        return {
            word
            for word in re.findall(r"[A-Za-z0-9]+", text.lower())
            if word not in DROPPABLE_AUTHOR_WORDS
            and not re.fullmatch(r"(?:19|20)\d{2}", word)
        }

    return bool(content(raw) - content(f"{author} {issue}"))


def _name_words(text):
    """The words in `text` that could plausibly be part of a name."""
    return [
        word
        for word in re.findall(r"[A-Za-z]{2,}", text)
        if word.lower() not in FILLER_WORDS
    ]


def split_issue_from_author(author):
    """Return (author, issue) for an author cell that holds volume info.

    Cells that are nothing but volume, issue or date material move across
    wholesale; cells that pair a designator with a name are split, so
    "Akira Hizuki Vol 1" becomes author "Akira Hizuki", issue "Vol 1".
    """
    if not author:
        return "", ""

    # A Roman numeral is an instalment number, never an author.
    if ROMAN_ONLY.fullmatch(author) or ROMAN_LEAD.match(author):
        return "", squish(author)

    if not has_designator(author):
        # No volume number, but a cell that is nothing but a publication date
        # ("Oct. 2012", "August 2012, Sept 2012 Oct 2012") is issue information
        # all the same. A date mixed in with a name is left alone: mid-cell
        # years are usually copyright or edition years, not issue dates.
        if DATEISH.search(author) and not _name_words(DATEISH.sub(" ", author)):
            return "", squish(author)
        return author, ""

    spans = [m.span() for m in ISSUE_TOKEN.finditer(author)]
    spans += [m.span() for m in EDITION_TOKEN.finditer(author)]
    spans += [m.span() for m in ISBN_TOKEN.finditer(author)]
    spans += [m.span() for m in DATEISH.finditer(author)]
    spans.sort()

    moved, remainder, cursor = [], [], 0
    for start, end in spans:
        if start < cursor:  # overlapping match, already accounted for
            continue
        remainder.append(author[cursor:start])
        moved.append(author[start:end])
        cursor = end
    remainder.append(author[cursor:])

    # Trailing periods can belong to a name ("Ph.D."), leading ones never do.
    kept = re.sub(r"\s+", " ", " ".join(remainder)).lstrip(" ,;:/&-.").rstrip(" ,;:/&-")
    if not _name_words(kept):
        # Nothing left that could be a name: the whole cell was volume info.
        return "", squish(author)
    return kept, re.sub(r"\s+", " ", " ".join(moved)).strip(" ,;:/&-")


# Publication types ------------------------------------------------------

# Used only to decide whether the Misc sheet's column B holds a type or an
# issue. The Periodicals sheet's Type column is clean and needs no vocabulary.
TYPE_VOCABULARY = {
    "book",
    "booklet",
    "brochure",
    "calendar",
    "catalog",
    "catalogue",
    "comic book",
    "flyer",
    "flyer/catalog",
    "journal",
    "letter",
    "magazine",
    "manual",
    "map",
    "newsletter",
    "newspaper",
    "pamphlet",
    "pamphlets",
    "periodical",
    "photo",
    "photos",
    "poster",
    "printed papers",
    "printed stories",
    "printed story",
    "story",
    "study guide",
    "work book",
    "workbook",
}


def title_case_type(value):
    """Normalise casing so "magazine" and "Magazine" don't split the counts."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), value)


# A handful of Criteria cells hold a publication type instead of a citation -
# the reviewer keyed the type into the wrong column. Where that happens, the
# value belongs in publication_type rather than being reported as a citation
# the parser couldn't read.
CRITERIA_TYPE_WORDS = {"magazine", "pamphlets", "book"}


# Extraction -------------------------------------------------------------


# A column boundary is drawn on nearly every row, so its rule segments add up
# to a large share of the page's tallest rule. The printouts also carry sub-
# point stubs in the middle of columns, which are not boundaries and would cut
# titles in half; they never reach a twentieth of that.
COLUMN_RULE_SHARE = 0.10


def rule_positions(page):
    """Return the (horizontal, vertical) rule positions that bound cells.

    Row boundaries are taken as they come - every horizontal rule is under some
    row, however short. Column boundaries are pooled by x first, so that a
    boundary Excel drew on most rows but not all still counts as one.
    """
    horizontal = {round(e["top"], 1) for e in page.edges if e["orientation"] == "h"}

    length = Counter()
    for edge in page.edges:
        if edge["orientation"] == "v":
            length[round(edge["x0"], 1)] += abs(edge["bottom"] - edge["top"])
    if not length:
        return sorted(horizontal), []
    floor = max(length.values()) * COLUMN_RULE_SHARE
    vertical = {x for x, total in length.items() if total >= floor}

    return sorted(horizontal), sorted(vertical)


def read_sheet(pdf_path):
    """Yield (excel_row_number, cells) for every data row in a printed sheet."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            horizontal, vertical = rule_positions(page)
            settings = dict(
                TABLE_SETTINGS,
                explicit_horizontal_lines=horizontal,
                explicit_vertical_lines=vertical,
            )
            for row in page.extract_table(settings) or []:
                # The first cell is Excel's row number; the repeated A/B/C...
                # column-letter header at the top of each page has none.
                row_number = (row[0] or "").strip()
                if not row_number.isdigit():
                    continue
                if int(row_number) < FIRST_DATA_ROW:
                    continue  # sheet banner and header row
                yield int(row_number), row[1:]


def get(cells, columns, field):
    index = columns.get(field)
    if index is None:
        return ""
    if isinstance(index, list):
        parts = [squish(cells[i]) for i in index if i < len(cells)]
        return "; ".join(part for part in parts if part)
    return squish(cells[index]) if index < len(cells) else ""


def clean_sheet(name, spec, descriptions, stats):
    columns = spec["columns"]
    records = []
    for row_number, cells in read_sheet(RAW_DIR / spec["pdf"]):
        fixes = ROW_FIXES.get((name, row_number))
        if fixes:
            cells = list(cells)
            for field, value in fixes.items():
                cells[columns[field]] = value

        title = get(cells, columns, "title")
        if not title:
            continue

        issue = get(cells, columns, "issue")
        publication_type = title_case_type(get(cells, columns, "type"))

        # On the Misc sheet, column B is a type only when it says so.
        type_or_issue = get(cells, columns, "type_or_issue")
        if type_or_issue:
            if type_or_issue.lower() in TYPE_VOCABULARY:
                publication_type = title_case_type(type_or_issue)
            else:
                issue = type_or_issue
        issue = decode_excel_serial(issue) or issue

        # Volume and issue designators turn up in the books sheet's author
        # column, which has no issue column of its own to put them in.
        author_raw = get(cells, columns, "author")
        author_serial = decode_excel_serial(author_raw)
        if author_serial:
            # An issue date that Excel reduced to a day count ("41926").
            author, author_issue = "", author_serial
        else:
            author_cell = strip_copyright_year(author_raw)
            number_then_author = (
                NUMBER_THEN_AUTHOR.match(author_cell)
                if title.lower() in NUMBER_THEN_AUTHOR_TITLES
                else None
            )
            if number_then_author:
                author_issue, author = number_then_author.groups()
            elif title.lower() in ISSUE_AS_AUTHOR_TITLES:
                # The whole cell is issue information, so it moves across
                # intact rather than being split ("Official Encyclopedia Vol 3").
                author, author_issue = "", author_cell
            else:
                author, author_issue = split_issue_from_author(author_cell)
                # Checked after the split, since these cells carry a volume
                # number too ("Back Door Adventures Vol 51"); the cell moves
                # across whole so the instalment reads in its original order.
                if author.lower() in ISSUE_AS_AUTHOR_VALUES:
                    author, author_issue = "", author_cell
            # Applied last: a split can expose the prefix ("Part 2 by Shan").
            author = tidy_author(author)
            if author_content_lost(author_raw, author, author_issue):
                stats["lost_author"].append((name, row_number, author_raw))
        if author_issue:
            issue = f"{issue}; {author_issue}" if issue else author_issue

        date_raw = get(cells, columns, "date")
        date, facility = parse_date(date_raw)
        criteria_raw = get(cells, columns, "criteria")
        if criteria_raw.lower() in CRITERIA_TYPE_WORDS:
            publication_type = title_case_type(criteria_raw)
            criteria_raw = ""
        criteria = parse_criteria(criteria_raw)
        sheet_note = get(cells, columns, "description")

        # The Description column sometimes holds criteria rather than a note:
        # either the row was keyed a column to the right, leaving page numbers
        # under Criteria and the codes in Description, or the reviewer carried
        # an extra code across into it. Where Description holds nothing but
        # codes it is read as criteria, so the output says what the code means
        # rather than printing the bare letter. The test is strict - every
        # token has to be a code - so prose notes are untouched.
        note_codes = parse_criteria(sheet_note) if sheet_note else ""
        if note_codes:
            if criteria:
                stats["extra_codes_in_description"] += 1
                criteria = f"{criteria}, {note_codes}"
            else:
                stats["criteria_in_description"] += 1
                criteria = note_codes
            sheet_note = ""
        elif criteria_raw and not criteria:
            # Not a citation the parser could read: a page range, a publication
            # type, a sentence. Nothing to expand, so the row keeps no code.
            stats["refused_criteria"][criteria_raw] += 1

        # The cited criteria are the formal reason; the sheets' own free-text
        # note, where there is one, is kept alongside rather than dropped.
        reasons = describe_criteria(criteria, descriptions, stats["unknown_codes"])
        if sheet_note:
            reasons.append(sheet_note)

        records.append(
            {
                "title": title,
                "author": author,
                "date": date,
                "publication_type": publication_type or spec["default_type"],
                "rejection_reason": "; ".join(reasons),
                "issue": issue,
                "page_numbers": get(cells, columns, "page_numbers"),
                "criteria": criteria,
                "facility": facility,
                "notes": get(cells, columns, "notes"),
                "source_list": name,
                "source_row": row_number,
                "date_raw": date_raw,
                "criteria_raw": criteria_raw,
            }
        )
    return records


# Every other field a record carries — criteria, facility, notes, date_raw,
# criteria_raw — is computed for sorting and for debugging a run, but is not
# written out. Note that dropping `criteria` drops the coded disapproval
# reason, leaving `rejection_reason` (populated for 1,159 of 6,219 rows) as the
# only reason in the output. `source_row` is kept: it is the Excel row each
# record came from, which is what makes a published row checkable against the
# printout, and what tells a genuine duplicate in the source apart from one
# this script invented.
FIELDNAMES = [
    "title",
    "author",
    "date",
    "publication_type",
    "rejection_reason",
    "issue",
    "source_list",
    "source_row",
]


def main():

    ## descriptions below from January 1, 2015 edition of Operating Procedure 803.2, Incoming Publications
    # saved from https://www.prisonpro.com/images/pdf/virginia-publications.pdf
    # There may be a more recent version to request. See documentation/virginia_notes.md

    descriptions = {
        "A": "Material that emphasizes explicit or graphic depictions or descriptions of sexual acts, including, but not limited to",
        "A1": "Actual sexual intercourse (vaginal, anal, or oral) including inanimate object penetration",
        "A2": "Secretion or excretion of bodily fluids or substances in the context of sexual activity or arousal",
        "A3": "Bondage, sadistic, masochistic, or other violent acts in the context of sexual activity or arousal",
        "A4": "Any sexual acts in violation of state or federal law",
        "A5": "Any manipulation of genitalia or buttocks",
        "B": "Material that contains solicitations for or promotes activities that are in violation of state or federal law including the abuse or sexual exploitation of children or contains nude depictions of children in the context of sexual activity",
        "C": "Instructions or information regarding",
        "C1": "Escape techniques",
        "C2": "Maps, road atlas, directions, etc. that depict a geographic region that could reasonably be construed to be a threat to security",
        "C3": "The manufacture, simulation, or concealment of weapons, ammunition, explosives, incendiaries, or escape devices",
        "C4": "The ingredients or manufacture of poisons, drugs, intoxicants, abrasives, corrosives, or other toxic or illegal substances",
        "C5": "Technical specifications for, or may be used to alter or defeat electronic, mechanical, or other security and communication devices",
        "C6": "Security techniques",
        "C7": "Training of personnel or canine units",
        "C8": "The ability to physically disable, injure, or kill a person",
        "D": "Material, documents, or photographs that emphasize depictions or promotions of violence, disorder, insurrection, terrorist, or criminal activity in violation of state or federal laws or the violation of the Offender Disciplinary Procedure",
        "E": "Material whose content could be detrimental to the offender rehabilitative efforts or the safety or health of offenders, staff, or others based on the offender's specific criminogenic needs (see Publications Detrimental to Offender Rehabilitative Efforts in this operating procedure)",
        "F": "Material that depicts, describes, or promotes gang bylaws, initiations, organizational structure, codes, or other gang-related activity or association",
        "G": "Material written or communicated in code or in a language other than English or Spanish (unless obtained from an approved vendor, see Attachment 1)",
        "H": "Books larger than 11 inches by 14 inches",
        "I": "Material that contains nudity",
    }

    stats = {
        "unknown_codes": Counter(),
        "refused_criteria": Counter(),
        "criteria_in_description": 0,
        "extra_codes_in_description": 0,
        "lost_author": [],
    }

    records = []
    for name, spec in SHEETS.items():
        sheet_records = clean_sheet(name, spec, descriptions, stats)
        print(f"{name:14} {len(sheet_records):5d} records")
        records.extend(sheet_records)

    records.sort(key=lambda r: (r["title"].lower(), r["date"], r["source_row"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    dated = sum(1 for r in records if r["date"])
    reasoned = sum(1 for r in records if r["rejection_reason"])
    print(f"{'total':14} {len(records):5d} records -> {OUT_PATH}")
    print(f"{'with a date':14} {dated:5d} ({dated / len(records):.1%})")
    print(f"{'with a reason':14} {reasoned:5d} ({reasoned / len(records):.1%})")

    unknown = stats["unknown_codes"]
    if unknown:
        codes = ", ".join(f"{c} x{n}" for c, n in sorted(unknown.items()))
        print(f"undefined codes cited (keying errors in the source): {codes}")

    if stats["criteria_in_description"]:
        print(
            f"rows keyed a column out, criteria read from Description: "
            f"{stats['criteria_in_description']}"
        )
    if stats["extra_codes_in_description"]:
        print(
            f"rows citing a further code in Description: "
            f"{stats['extra_codes_in_description']}"
        )

    refused = stats["refused_criteria"]
    if refused:
        total = sum(refused.values())
        print(f"criteria cells holding something other than a citation: {total}")
        for value, count in refused.most_common():
            suffix = f" x{count}" if count > 1 else ""
            print(f"    {value!r}{suffix}")

    # Should stay empty. Anything here is an author cell the script emptied
    # instead of moving, which is how two silent data losses were found.
    for sheet, row_number, raw in stats["lost_author"]:
        print(f"warning: {sheet} row {row_number} lost author text: {raw!r}")


if __name__ == "__main__":
    main()
