# Notes

California's list is `data/raw/california/Disapproved Publications - Family &
Friends Services.pdf`: 221 pages, printed from a web page on March 9, 2026. It
has four columns — Publication, Author, Publisher, Reason for Decision — and no
dates. `etl/clean_california.py` turns it into
`data/processed/cleaned_california.csv` (4,264 records), and
`data/documentation/california_working_files/qa_california.py` checks the result
against the PDF. Run the check after any change to the extraction.

## The PDF is a printed web page, not a document

The browser drew the whole table as one long strip and cut it into 792pt pages.
Where a cut crosses a row, that row is drawn on **both** pages, each copy missing
different characters: the bottom of page 8 holds `NOVEL VOLUME TWO` / `dit`, the
top of page 9 holds `NOVEL,VOLUME TWO` / `nudity`. The browser also draws a
border line where it cuts a row, which looks like a row boundary but is not one.

This breaks ordinary table extraction. PyMuPDF's table finder dropped every row
cut by a page and merged others — it found about 4,080 records, not 4,264, and
glued two *Game of Thrones* volumes into one title. So the ETL does not use it.
Instead it:

1. places every text line on the continuous strip (page index × 792 + y), so the
   two copies of a cut line land in the same place;
2. keeps, for each column, whichever copy has more text;
3. starts a record wherever the reason column begins `Title 15`,
   `CCR, Title 15`, or `Nudity – 12`, and joins each column's lines.

Text is read **without page-edge clipping** (`TEXT_MEDIABOX_CLIP` off). With
clipping on, commas and hyphens on the cut lines were silently lost — "Title 15,
Section" came out "Title 15 Section", "0421-0521" came out "0421 0521" — in 10
records. The QA check is what found this.

## How the check works

`qa_california.py` shares no code with the ETL. It reads the PDF with
`pdfplumber`, which ignores clipping, and splits records at the table's **drawn
row borders**: each row has a thin (0.8pt) green rule across the Publication
column. Neither text nor spacing decides the split, and spacing could not: a gap
inside one record can be exactly as wide as the gap between two (15.2pt).
The white page-background rectangle supplies the false border at each cut and is
ignored. Every record is then compared field by field with the CSV.

It passes with 0 failures. Ten deliberately corrupted copies of the CSV all fail
it, including the two real bugs above: a merged pair of records, and a comma lost
at a page cut.

## Fields

| Source column | Output |
|---|---|
| Publication | `title`, in the source's capitals |
| Author | `author` — 2,513 rows have one, 1,751 do not |
| Reason for Decision | `rejection_reason`, as written |
| Publisher | dropped: not in the project schema |
| — | `date` and `publication_type` are blank: the source has neither |

Inside a cell, lines are joined with a space. A line ending in a hyphen joins the
next without one: in this source every such hyphen is real (PIN-UPS,
JULY-AUGUST, JIU-JITSU), never a word broken across lines. Font ligatures are
written as plain letters ("scientiﬁc" → "scientific").

## Rejection reasons

Each reason gives the California Code of Regulations section and its wording,
e.g. `Title 15, Section 3006(c)(17) – frontal nudity`, so they are kept as
written rather than mapped from a code. By section:

| Section | Records | Wording (as most often written) |
|---|---:|---|
| 3006(c)(17) | 1,386 | frontal nudity |
| 3006(c)(15)(A) | 1,309 | lacks serious literary, artistic, political or scientific value |
| 3006(d) | 547 | presents a serious threat to facility security or the safety of incarcerated persons and staff |
| 3006(c)(1) | 255 | violence or physical harm |
| 3006(c)(15)(C)(5) | 227 | conduct which is or appears to be forceful, threatening or violent |
| 3006(c)(16) | 181 | sexually explicit images |
| 3006(c)(19) | 146 | STG members or associates |
| 3006(c)(8) | 71 | a description of the making of any weapon, explosive, poison or destructive device |
| 3006(c)(13) | 30 | contains or concerns gambling or a lottery |
| 3006(c)(15)(B)(3) | 29 | conduct which is or appears to be forceful, threatening or violent |
| 3006(c)(15)(C)(3) | 21 | contains or concerns of nudity of a minor, or person who appears to be under 18 years old |
| 3006(c)(12) | 14 | maps depicting any area within a ten mile radius of a facility |
| 3006(c)(15)(C)(6) | 14 | conduct where one of the participants is a minor, or appears to be under 18 years old |
| 3006(c)(9) | 11 | illustrations, explanations, and/or descriptions of how to sabotage or disrupt computers, communications, or electronics |
| 3006(c)(5) | 6 | plans to disrupt the order, or breach the security, of any facility |
| 3006(c)(15)(B), (c)(15)(C)(4) | 4 each | |
| 3006(c)(6) | 2 | |
| 3006(c)(2), (c)(4), (c)(15)(B)(2), (c)(15)(C)(2) | 1 each | |
| "Nudity – 12 consecutive issues – Permanently Disapproved" | 3 | *Hustler*, *Penthouse*, *Playboy* |

The same section is not always worded the same way. (c)(15)(B)(3), for one,
appears both as "conduct which is or appears to be forceful, threatening or
violent" (the wording of (c)(15)(C)(5)) and as "depicts nudity of a minor".
Worth comparing against the regulation itself before relying on the wording.

**137 reasons are cut short in the source.** They stop at "presents a serious
threat to facility security or the safety of incarcerated" (one with a full stop
after it). Both readings of the PDF agree, so the text is missing from the
printout, not lost in extraction.

**22 reasons are written irregularly in the source**, and kept that way:
18 × `Title 15, Section 3006 (c)(13)` (with a space), 1 × `CCR, Title 15,
3006(c) (13)`, and the 3 "Nudity – 12 consecutive issues" entries above.

## Other quirks

- **Source column slips.** At least one record has its author in the Publisher
  column: *100 DEADLY SKILLS, SURVIVAL EDITION* lists Clint Emerson as
  publisher and no author, so `author` is blank. Publisher is dropped, so such
  slips lose the name. Not searched for systematically.
- **Several items in one record.** Some entries list a set — e.g. *4 THE PACK
  ENTERTAINMENT PRESENTS, NUDE 5, SUPER SIZE1, ASIAN 1, ASIAN CAMEL, CAMELTOE 1,
  CAMELTOE 4, PS FELICIA 1*. They stay one record, as in the source.
- **Duplicates.** 60 records exactly repeat another (*A Gangster's Code*,
  *Adbusters, May/June 2014*, …). They are kept: removing them would misstate
  what the source says.
- **No dates.** The list gives no decision dates at all, so nothing can be said
  about when a title was disapproved.
