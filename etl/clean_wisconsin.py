#!/usr/bin/env python3
"""Wisconsin DOC reviewed-publications PDFs -> DLP five-column CSV.

The archived (2025) PDF is a printout of an Excel review log, with approval and
rejection X columns and occasional STRUCK THROUGH decisions/dates/comments.
This script reconstructs rows from the positions of the X's and review dates,
then detects struck-out words using the source's drawn lines. The newer (2026)
PDF has an actual grid that provides row boundaries, and explicit status and
publication type columns.

The output is EXACTLY:
    title,author,date,publication_type,rejection_reason

Only unambiguously active denied decisions enter the main CSV. Blank dates/types
are retained if not supplied; duplicates in one source or repeat decisions on separate dates remain. Confirmed identical cross-document review events may be
collapsed, favoring the newer record; ambiguous overlaps and conflicting
revisions are flagged in the audit CSV rather than silently decided.

The clean five column csv does include some duplicates where titles are imperfectly replicated.
There are also at least a few instances where publishing companies are attributed as authors.  

If you want to examine the inclusion/exclusion decisions, run the cleaning script
with the review flag. 

Usage:
    python -m pip install pymupdf
    python etl/clean_wisconsin/extract.py
    python etl/clean_wisconsin/extract.py --review data/processed/wisconsin_review.csv
    python etl/clean_wisconsin/extract.py --archived path/a.pdf --current path/b.pdf --output path/out.csv

Exit codes: 0 successful write; 1 file/extraction error.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from collections import Counter, defaultdict
import re
import sys
import unicodedata

import fitz

ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_DEFAULT = ROOT / "data" / "raw" / "wisconsin" / "ARCHIVED_Books_and_Publications_Final_update_on_09.23.2025.pdf"
CURRENT_DEFAULT = ROOT / "data" / "raw" / "wisconsin" / "DAI_Reviewed_Publications_List_-_Published_01.23.2026.pdf"
OUTPUT_DEFAULT = ROOT / "data" / "processed" / "cleaned_wisconsin.csv"
COLUMNS = ("title", "author", "date", "publication_type", "rejection_reason")
AUDIT_COLUMNS = (
    "source", "pdf_page", "source_title", "source_subtitle", "source_volume",
    "title", "author", "original_dates", "date", "status", "original_status",
    "publication_type", "rejection_reason", "original_reason", "crossed_out_fields",
    "source_reviewer", "pages_reviewed", "flags", "decision", "duplicate_of",
)
ARCHIVE_BOUNDS = (50.0, 216.0, 301.0, 356.0, 408.0, 450.0,
                  536.0, 599.0, 643.0, 985.0)
NEW_BOUNDS = (18.0, 157.0, 297.0, 352.5, 369.5, 510.0,
              540.0, 686.0, 706.0, 728.5, 871.0, 892.0, 979.0)
DATE_RE = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2}|\d{4})\b")
EMPTY = {"n/a", "na", "unknown", "none", "null"}


def tidy(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def clean_blank(value: str) -> str:
    value = tidy(value)
    return "" if value.lower() in EMPTY else value


def normal_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def iso_date(value: str) -> str:
    match = DATE_RE.search(value)
    if not match:
        return ""
    mo, day, yr = match.groups()
    year = int(yr)
    if len(yr) == 2:
        year += 2000 if year <= 30 else 1900
    try:
        return date(year, int(mo), int(day)).isoformat()
    except ValueError:
        return ""


def get_lines(page: fitz.Page) -> list[tuple[float, float, float]]:
    """Source strikethroughs are short drawn strokes, not text styles.

    Retain horizontal strokes only. The vertical intersection test is applied
    separately to the *middle* of each word, excluding usual table borders.
    """
    output = []
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1:3]
            if abs(p1.y - p2.y) > 0.22:
                continue
            x0, x1 = sorted((p1.x, p2.x))
            if 2 < x1 - x0 < 500:
                output.append((x0, x1, (p1.y + p2.y) / 2))
    return output


def strike(word: tuple, lines: list[tuple[float, float, float]]) -> bool:
    x0, y0, x1, y1 = word[:4]
    for sx0, sx1, sy in lines:
        overlap = max(0., min(x1, sx1) - max(x0, sx0))
        if overlap >= (x1 - x0) * 0.58 and (y0 + .25 * (y1-y0)) <= sy <= (y0 + .75 * (y1-y0)):
            return True
    return False


def column(x: float, bounds: tuple[float, ...]) -> int | None:
    for i in range(len(bounds)-1):
        if bounds[i] <= x < bounds[i+1]:
            return i
    return None


def words_to_text(words: list[tuple]) -> str:
    """Reconstruct reading order from PDF coordinates without inventing text."""
    if not words:
        return ""
    words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[list[tuple]] = []
    for word in words:
        if lines and abs(word[1] - lines[-1][0][1]) <= 1.8:
            lines[-1].append(word)
        else:
            lines.append([word])
    return tidy(" ".join(" ".join(str(w[4]) for w in sorted(group,key=lambda z:z[0])) for group in lines))


def words_with_strikes(words: list[tuple], strokes: list[tuple]) -> tuple[str, str, bool]:
    """Return active words, full source words, and whether crossed words exist."""
    active = [w for w in words if not strike(w, strokes)]
    return words_to_text(active), words_to_text(words), len(active) != len(words)


def archive_centers(words: list[tuple]) -> list[float]:
    # Both approval and denial marks can appear in the SAME row (revision).
    # Use a single center for such instances and add date-only rows when an
    # entire status field is missing in the source.
    marks = sorted((w[1] + w[3])/2 for w in words
                   if w[4].lower() == 'x' and (362 < w[0] < 394 or 421 < w[0] < 444))
    groups: list[list[float]] = []
    for y in marks:
        if groups and abs(y - groups[-1][-1]) < 2.1:
            groups[-1].append(y)
        else:
            groups.append([y])
    centers = [sum(g)/len(g) for g in groups]
    for w in words:
        if not (539 < w[0] < 598):
            continue
        if not (DATE_RE.fullmatch(w[4]) or w[4].lower() == 'unknown'):
            continue
        y = (w[1]+w[3])/2
        if min((abs(y-v) for v in centers), default=999) > 10:
            centers.append(y)
    # Some entries explicitly say 'Needs to be reviewed' rather than providing
    # an X or a review date. Without detecting those, their titles get appended
    # to the neighboring approved/denied book. A title line with an author on
    # the SAME baseline is a conservative additional anchor. Do not add a line
    # near any existing marker/date, nor treat a title wrap without an author
    # as a separate record.
    titles = sorted({round(w[1],2) for w in words if 51.0 < w[0] < 54.5 and w[1] > 50})
    authors = [w[1] for w in words if 222.0 < w[0] < 300.0]
    for ty in titles:
        if min((abs(ty-ay) for ay in authors), default=999) > 5.6:
            continue
        center=ty+5.0
        if min((abs(center-c) for c in centers), default=999) > 13.2:
            centers.append(center)
    return sorted(centers)


def archive_heights(centers: list[float]) -> list[float]:
    """Estimate Excel row heights from center-to-center differences.

    Excel centers rows vertically. Adjacent center difference is approximately
    (height_i + height_i+1)/2. Estimate heights using relaxed constraints, with
    a preference for ordinary 13-point rows, and forbid negative heights.
    """
    n=len(centers)
    if n==0: return []
    if n==1: return [19.]
    h=[13.5]*n
    for _ in range(500):
        mx=0.
        for i in range(n):
            neighbors=[]
            if i>0: neighbors.append(2*(centers[i]-centers[i-1])-h[i-1])
            if i<n-1: neighbors.append(2*(centers[i+1]-centers[i])-h[i+1])
            target=(sum(neighbors)+0.045*13.5)/(len(neighbors)+0.045)
            new=max(10.,target)
            mx=max(mx,abs(new-h[i]));h[i]=new
        if mx<.0001: break
    return h


@dataclass
class Record:
    source: str
    pdf_page: int
    source_title: str = ""
    source_subtitle: str = ""
    source_volume: str = ""
    title: str = ""
    author: str = ""
    original_dates: str = ""
    date: str = ""
    status: str = ""
    original_status: str = ""
    publication_type: str = ""
    rejection_reason: str = ""
    original_reason: str = ""
    crossed_out_fields: str = ""
    source_reviewer: str = ""
    pages_reviewed: str = ""
    flags: list[str] = field(default_factory=list)
    decision: str = ""
    duplicate_of: str = ""

    def audit(self) -> dict:
        d={key:getattr(self,key) for key in AUDIT_COLUMNS}
        d['flags']=' | '.join(sorted(set(self.flags)))
        return d

    def output(self) -> dict:
        return {k:getattr(self,k) for k in COLUMNS}


def convert_date(active: str, all_dates: str, rec: Record) -> str:
    dates=DATE_RE.findall(active)
    if not dates:
        if DATE_RE.search(all_dates): rec.flags.append('date_crossed_or_unreadable')
        else: rec.flags.append('date_missing')
        return ""
    normalized=[iso_date('/'.join(x)) for x in dates]
    normalized=[x for x in normalized if x]
    if len(set(normalized))>1:
        rec.flags.append('multiple_active_dates')
        return ''
    return normalized[0] if normalized else ''


def merge_title(title: str, subtitle: str, volume: str) -> str:
    parts=[clean_blank(title),clean_blank(subtitle)]
    result=': '.join(p for p in parts if p)
    vol=clean_blank(volume)
    if vol and normal_key(vol) not in normal_key(result):
        label=vol if re.search(r'(?i)\b(vol(?:ume)?|issue|edition|#)\b',vol) else f'Vol./Issue {vol}'
        result += f' ({label})'
    return tidy(result)


def parse_archive(source: Path) -> list[Record]:
    all_rows=[]
    with fitz.open(source) as doc:
        for pi,page in enumerate(doc):
            words=page.get_text('words')
            strokes=get_lines(page)
            centers=archive_centers(words)
            if not centers:
                continue
            heights=archive_heights(centers)
            # Midpoint between adjacent inferred row edges; prevents tiny
            # floating-point gaps/overlaps at the shared boundary.
            bounds=[max(45.,centers[0]-heights[0]/2)]
            for i in range(len(centers)-1):
                bounds.append((centers[i]+heights[i]/2 + centers[i+1]-heights[i+1]/2)/2)
            bounds.append(min(page.rect.height-7,centers[-1]+heights[-1]/2))
            # Page 1 has a tall title header; the first data row's legal
            # citation starts at y=164, above its vertically centered X.
            if pi == 0:
                bounds[0] = min(bounds[0], 160.0)
            # Detect possible source/row ambiguity when centers don't admit a
            # clean 13pt+ row partition.
            residuals=[abs((heights[i]+heights[i+1])/2-(centers[i+1]-centers[i]))
                       for i in range(len(centers)-1)]
            for i,c in enumerate(centers):
                cell=[[] for _ in range(9)]
                for w in words:
                    # For this Excel export, a title in an exceptionally
                    # tall row may be printed near the bottom of its cell.
                    # Its PDF word box can straddle the row border; the
                    # text top is a more reliable assignment than midpoint.
                    col=column(w[0],ARCHIVE_BOUNDS)
                    if col is None:continue
                    cy=w[1] if col == 0 else (w[1]+w[3])/2
                    if bounds[i]-.1<=cy<bounds[i+1]+.1:
                        cell[col].append(w)
                rec=Record('archived_2025',pi+1)
                names=['title','author','volume','approved','denied','pages','date','reviewer','reason']
                active={}; raw={}; struck=[]
                for j,name in enumerate(names):
                    active[name],raw[name],hit=words_with_strikes(cell[j],strokes)
                    if hit:struck.append(name)
                rec.source_title=active['title'];rec.source_volume=clean_blank(active['volume'])
                rec.title=merge_title(rec.source_title,'',rec.source_volume)
                rec.author=clean_blank(active['author'])
                rec.original_dates=raw['date']
                rec.date=convert_date(active['date'],raw['date'],rec)
                rec.pages_reviewed=clean_blank(active['pages'])
                rec.source_reviewer=clean_blank(active['reviewer'])
                rec.original_reason=raw['reason'];rec.rejection_reason=active['reason']
                rec.crossed_out_fields=' | '.join(struck)
                rec.original_status='approved='+raw['approved']+'; denied='+raw['denied']
                approved=any(w[4].lower()=='x' and not strike(w,strokes) for w in cell[3])
                denied=any(w[4].lower()=='x' and not strike(w,strokes) for w in cell[4])
                # Correct the case where 'X' is crossed out by line and its
                # overlapping label is not; status is computed word-by-word.
                if approved and denied:
                    rec.status='conflict';rec.flags.append('two_active_status_marks')
                elif denied:rec.status='denied'
                elif approved:rec.status='approved'
                else:
                    rec.status='unknown';rec.flags.append('missing_active_status_mark')
                if struck: rec.flags.append('strikethrough_present')
                if not rec.title:rec.flags.append('title_missing')
                if not rec.rejection_reason and rec.status=='denied':rec.flags.append('reason_missing')
                if (i>0 and residuals[i-1]>3) or (i<len(residuals) and residuals[i]>3):
                    rec.flags.append('row_boundary_uncertain')
                if len(centers)>1 and bounds[i+1]-bounds[i]<8.5:
                    rec.flags.append('short_source_row')
                if rec.status=='denied' and rec.title:
                    rec.decision='included'
                else:
                    rec.decision='excluded'
                all_rows.append(rec)
    return all_rows


def new_row_edges(page: fitz.Page) -> list[float]:
    # The SharePoint PDF draws a thin (0.24pt) full-width rectangle at EVERY
    # row boundary; its alternating filled background is not the row itself.
    ys=set()
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]!='re':continue
            r=item[1]
            if r.width>950 and r.height<.38 and 50<r.y0<570:
                ys.add(round((r.y0+r.y1)/2,2))
    edges=sorted(ys)
    if not edges:
        raise ValueError(f'Grid borders not found on page {page.number+1}; inspect PDF')
    return edges


def extract_new_fragment(page: fitz.Page, top:float,bottom:float,words:list[tuple]) -> dict:
    cell=[[] for _ in range(len(NEW_BOUNDS)-1)]
    for w in words:
        cy=(w[1]+w[3])/2
        if top-.1<=cy<bottom+.1:
            c=column(w[0],NEW_BOUNDS)
            if c is not None:cell[c].append(w)
    return {k:words_to_text(part) for k,part in zip(
        ('title','subtitle','volume','status','author','publication_type',
         'pages','date','reviewer','reason','item','path'),cell)}


def parse_current(source:Path) ->list[Record]:
    rows=[]; previous=None
    with fitz.open(source) as doc:
        for pi,page in enumerate(doc):
            words=page.get_text('words')
            edges=new_row_edges(page)
            for low,high in zip(edges,edges[1:]):
                f=extract_new_fragment(page,low,high,words)
                if not any(f.values()): continue
                if normal_key(f['status'])=='status' and normal_key(f['title'])=='title':
                    continue  # Printed header on the first page.
                status=normal_key(f['status'])
                # A tall Excel cell may continue on the next printed page.
                # Only merge fully anchorless fragments; do not merge a blank
                # status on a newly headed title without review.
                if not status and not f['title'] and not f['date'] and not f['author'] and previous is not None:
                    if f['reason']:
                        previous.rejection_reason=tidy(previous.rejection_reason+' '+f['reason'])
                        previous.original_reason=previous.rejection_reason
                        previous.flags.append('reason_continued_across_page')
                    continue
                rec=Record(source='current_2026',pdf_page=pi+1)
                rec.source_title=f['title'];rec.source_subtitle=f['subtitle'];rec.source_volume=f['volume']
                rec.title=merge_title(f['title'],f['subtitle'],f['volume'])
                rec.author=clean_blank(f['author']);rec.publication_type=clean_blank(f['publication_type'])
                rec.original_dates=f['date'];rec.date=convert_date(f['date'],f['date'],rec)
                rec.source_reviewer=clean_blank(f['reviewer']);rec.pages_reviewed=clean_blank(f['pages'])
                rec.rejection_reason=f['reason'];rec.original_reason=f['reason']
                rec.original_status=f['status']
                if status in ('denied','approved'):
                    rec.status=status
                else:
                    rec.status='unknown';rec.flags.append('unexpected_status')
                if not rec.title:rec.flags.append('title_missing')
                if not rec.rejection_reason and rec.status=='denied':rec.flags.append('reason_missing')
                rec.decision='included' if rec.status=='denied' and rec.title else 'excluded'
                rows.append(rec);previous=rec
    return rows


def reconcile(archive:list[Record],current:list[Record]) ->tuple[list[Record],list[Record]]:
    """Conservative cross-source reconciliation of identical review events.

    Same exact normalized title AND same nonempty date + same active denial
    => one output record; prefer structured newer record. Different dates are
    separate decisions. Missing/ambiguous dates aren't used to deduplicate.
    """
    def core_title(r: Record) -> str:
        # Match title+subtitle in a newer list with a single title string
        # from the archived list. Ignore volume only for candidate discovery,
        # not for final reconciliation.
        return normal_key(' '.join((r.source_title,r.source_subtitle)))

    index=defaultdict(list)
    for r in current:
        if r.decision=='included' and r.date:
            index[(core_title(r),r.date)].append(r)
    # No rewriting of within-source duplicates; source records are retained.
    for r in archive:
        if r.decision!='included' or not r.date:continue
        hits=index.get((core_title(r),r.date),[])
        if r.source_volume:
            hits=[x for x in hits if normal_key(x.source_volume)==normal_key(r.source_volume)]
        if len(hits)==1:
            match=hits[0]
            # Conflicting explicit author/reason warrants manual review.
            reason_a=normal_key(r.rejection_reason)
            reason_b=normal_key(match.rejection_reason)
            if r.author and match.author and normal_key(r.author)!=normal_key(match.author):
                r.flags.append('cross_source_author_conflict')
                match.flags.append('cross_source_author_conflict')
            if reason_a and reason_b and reason_a!=reason_b:
                # In a few original archive cells the PDF pagination clipped
                # the final words; an otherwise identical, longer version in
                # the newer extract is stronger evidence than a conflict.
                if len(reason_a)>60 and reason_b.startswith(reason_a):
                    r.flags.append('archived_reason_prefix_of_current')
                    match.flags.append('archived_reason_prefix_of_current')
                else:
                    r.flags.append('cross_source_reason_difference')
                    match.flags.append('cross_source_reason_difference')
            # Conflicting source explanations are not silently discarded.
            if ('cross_source_author_conflict' not in r.flags
                    and 'cross_source_reason_difference' not in r.flags):
                r.decision='deduplicated'
                r.duplicate_of=f'current_2026 page {match.pdf_page}'
                match.flags.append('also_in_archived_2025')
        elif len(hits)>1:
            r.flags.append('multiple_possible_cross_source_matches')
    selected=[r for r in archive+current if r.decision=='included']
    return selected,archive+current


def save_csv(path:Path,rows:list[dict],columns:tuple[str,...]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as fh:
        writer=csv.DictWriter(fh,fieldnames=columns)
        writer.writeheader();writer.writerows(rows)


def main(argv=None)->int:
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--archived',type=Path,default=ARCHIVED_DEFAULT)
    ap.add_argument('--current',type=Path,default=CURRENT_DEFAULT)
    ap.add_argument('--output',type=Path,default=OUTPUT_DEFAULT)
    ap.add_argument('--review',type=Path,help='Optional full audit CSV (includes approvals and exclusions)')
    args=ap.parse_args(argv)
    try:
        for src in (args.archived,args.current):
            if not src.is_file():raise FileNotFoundError(f'Missing source PDF: {src}')
        a=parse_archive(args.archived)
        b=parse_current(args.current)
        selected,audit=reconcile(a,b)
        if not selected: raise ValueError('No denials extracted')
        save_csv(args.output,[r.output() for r in selected],COLUMNS)
        if args.review:save_csv(args.review,[r.audit() for r in audit],AUDIT_COLUMNS)
        print(f'Archived: {len(a)} records; active denied: {sum(r.status=="denied" for r in a)}')
        print(f'Current: {len(b)} records; active denied: {sum(r.status=="denied" for r in b)}')
        print(f'Cross-source exact review events deduplicated: {sum(r.decision=="deduplicated" for r in a)}')
        print(f'Output: {len(selected)} denied review rows -> {args.output}')
        print(f'Strikethrough affected rows: {sum(bool(r.crossed_out_fields) for r in a)}')
        print(f'Records with flags: {sum(bool(r.flags) for r in audit)}')
        if args.review:print(f'Audit: {args.review}')
        return 0
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
