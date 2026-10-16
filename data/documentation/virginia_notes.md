# Notes

Virginia released its "Disapproved Publications List December 2010 - June 2025"
as three Excel sheets printed to PDF. `etl/clean_virginia.py` extracts them by
following Excel's own gridlines, and `source_row` on every record is the
spreadsheet row it came from, so any row can be checked against the printout.

Excel did not border every cell, and where a border is missing the gridlines
run two cells together — quietly, and in a way that looks like ordinary data
coming out. `working/qa_virginia.py` guards against it: it reads the same three
PDFs a second time with a different library and a different method, diffs the
two readings cell by cell, and fails on anything it cannot account for. Run it
after any change to the extraction.

The `working/` directory beside the source PDFs holds everything that supports
the release without being part of it — that harness, the operating procedure
the criteria come from, and the script that reads it. All paths below are
relative to `data/raw/virginia/`, and every script runs from the repository
root.

**The release appears to be truncated.** All three sheets stop partway through
the alphabet — books at "She Comes First", periodicals at "Tight", misc. at
"Tools for Freedom". Worth going back to VADOC for the rest, and ideally for the
spreadsheet rather than a printout.

## Rejection reasons

Virginia states its reason as a code — `A1`, `C3`, `D` — in the sheets'
"Criteria" column, and only sometimes writes a note in the free-text
"Description" column (1,159 of 6,219 rows). `rejection_reason` combines the two:
the text of each criterion cited, followed by the sheet's own note where there is
one. 6,155 rows (99.0%) carry a reason.

The key to the codes comes from the January 1, 2015 edition of Operating
Procedure 803.2, Incoming Publications, saved as
`working/virginia-publications.pdf` (source:
[prisonpro.com](https://www.prisonpro.com/images/pdf/virginia-publications.pdf)).
That edition spells out all 22 criteria — A and A1-A5, B, C and C1-C8, D, E, F,
G, H, I — in its "Specific Criteria for Publication Disapproval" section. **Later
editions moved the list into a separate Attachment 1 that VADOC does not
publish**, so [the current
803.2](https://vadoc.virginia.gov/files/operating-procedures/800/vadoc-op-803-2.pdf)
does not document the codes; neither does 803.1, which covers Offender
Correspondence. Worth requesting the current Attachment 1 to check whether the
criteria have changed since 2015.

`working/extract_criteria.py` pulls the definitions out of that PDF into
`working/rejection_reasons.csv` (`code,description`), which `clean_virginia.py`
reads.

Seven citations use codes the procedure never defines — `A7` (x2), `A11`, `B4`,
`D7`, `D8`, `J1`, `L`. They are keying errors: A stops at 5, C at 8, and B, D and
the rest have no sub-items. They contribute no text to `rejection_reason`, and
the script lists them when it runs.

## Dates

"Date of Review" is typed a couple hundred ways (`2/10/2020`, `Apr-22`,
`December 2018`, `Sept/Oct 2013`). `date` keeps whatever precision the source
offers, so it mixes `YYYY-MM-DD` (2,062 rows) and `YYYY-MM` (4,044 rows). For a
range of months, the first is used.

113 rows have no date: 92 cells held a facility name instead ("Augusta", "River
North"), 11 were blank, and 10 are unrecoverable typos (`12/16`, `2/12/20201`,
and dates outside the Dec 2010 - June 2025 window such as `5/1/2107`). A further
30 cells name a facility *alongside* a date; the name is stripped so the date
parses, but is not written out.

## Issues typed as dates

72 issues were typed into Excel as dates, which stored them as a count of days
from 1899-12-30 and printed them raw: Rolling Stone's issue reads `42117`.
`issue` gives these back as ISO dates — `42117` becomes `2015-04-23` — and every
one lands on or before its own review date, which is the check that they are
being read right. **The original precision is gone**: "October 2012" and
"10/1/2012" both serialize to 41183, and both come back as `2012-10-01`.

Three more went the other way, from a pair of numbers into a day and a month,
and cannot be recovered at all: `12-May` was either issue 5/12 or issue 12/5.

## Authors

The books sheet's author column collects anything but authors, so the script
cleans it three ways. 1,595 of 1,920 books keep an author. Nothing is deleted
along the way: every run checks that each author cell's contents reached either
`author` or `issue`, and reports any that did not.

- **Copyright years removed** from marked cells ("Owen Brooks ©2019", "Dark
  House Copyright 2018") and bare ones ("Terry Moore 2022"). Cells holding
  nothing but a year are now empty. Years mid-cell are left alone, and so is a
  trailing year sitting beside a volume or edition number ("Akira Hizuki Vol 1
  2018"), where the year dates the issue and travels with it.
- **Moved to `issue`**: volume designators ("Vol 4, 5, 6", "#27, #28", "Issue
  288"), designators split from a name ("Akira Hizuki Vol 1" → author "Akira
  Hizuki", issue "Vol 1"), editions ("2nd Edition", "Eleventh Edition Robert
  Crooks Karla Baur"), bare publication dates ("Oct. 2012", "Fall/Winter"),
  Roman numerals, which serials use for instalment numbers and never for an
  author ("Letters To Penthouse" / "XXXVI"), ISBNs ("Sylvia Day ISBN
  9780425273869"), which the source already files under Issue elsewhere, and
  issue dates Excel reduced to a day count ("41926" → `2014-10-14`).
- **A leading "By " removed** ("by Marvin Dunn" → "Marvin Dunn"). Only at the
  start: "edited by Jane Little" and "Story & Art by Reiji Suzumaru" keep theirs.
  The placeholder "none" is emptied out as well.

An edition has to say "Edition" outright, or "Ed" behind an ordinal ("Barron's
10th Ed"). Bare "Ed" is left alone — in this data it is a name or an editor
credit ("Ed Wheat", "Edited by Alison Tyler", "John T. Moore Ed.D"). So are the
seven cells mixing a date into a name ("Campesato July 2015"), where the year is
more likely a copyright than an issue date.

Some serial titles put the instalment name in the author column in a form no
rule can spot, so they are listed by hand in `ISSUE_AS_AUTHOR_TITLES` — "Magic,
The Gathering" ("Official Encyclopedia Vol 3"), "Monster Musume" ("I Heart
Monster Girls 4"), "Black Book Mini" ("Latina"), "Goat Foreplay" ("Platinum Vol.
4"), "Barbarella" ("Volume One Red Hot Gospel"), "Jump Comics", "Licks",
"Advanced D&D" and "Cum For Me". The match is on the
whole title, never a prefix: "Monster Musume Everyday Life of..." and "Monster
Musume I Heart Monster Girls" correctly credit Okayado and Kenkou Cross.

Two more hand-kept lists handle what a title match cannot:

- `ISSUE_AS_AUTHOR_VALUES` moves instalment names on titles that *elsewhere*
  carry a real credit. "Letters to Penthouse" is variously credited to "Back Door
  Adventures" and to Barbara Pizio, so only the named values move and Pizio, the
  "Editors of Penthouse Magazine" and the rest stay put.
- `NUMBER_THEN_AUTHOR_TITLES` splits a title that leads with its instalment
  number: Gantz is credited "25 Hiroya Oku Works", which becomes author "Hiroya
  Oku", issue "25".

## Duplicates

33 records repeat another record exactly — "HD Products & Services" five times,
"Celebrity Skin #11" three. The duplication is Virginia's: each copy occupies
its own spreadsheet row, which `source_row` shows. They are left in, since
removing them would misstate what the source says.
