#!/usr/bin/env python3
"""Reconstruct Missouri Censorship Log spreadsheet rows from the repaired PDF.

Called by etl/clean_missouri/run_pipeline.py at the 'extract' stage. The source
is a sideways, spreadsheet-derived PDF whose character mapping has already
been repaired. This script uses vector gridline positions and text coordinates
instead of OCR or whitespace-only parsing.

Output: a reconstructed 12-column CSV with source page and row references,
plus QA flags and a page-level JSON summary. The output directory is supplied
by the runner (etl/clean_missouri/interim/).
Requires: PyMuPDF.
"""
import argparse
import bisect
import collections
import csv
import json
import re
from pathlib import Path
import fitz

COLUMNS = [
    "Log Number", "Title of Publication", "Volume/Issue Number", "Publisher Name",
    "Sender Name", "Reason for Censorship", "Censorship Letters Sent Out Date",
    "Appeal Ltr & Final Decision", "Justification/Comments",
    "Ryan Crews Number for Policy", "Jason Lewis Number for Policy", "Earl Dye Number for Policy"
]
META = ["Source PDF Page", "Source Page Row", "QA Flags"]
DEFAULT_Y = [922.32, 904.20, 838.92, 771.36, 705.00, 638.64,
             572.64, 496.08, 422.52, 337.32, 255.84, 174.36, 86.16]

_NUM = rb"([-+]?(?:\d+(?:\.\d*)?|\.\d+))"
_RECT = re.compile(_NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+re\s+f")

def grid_bounds(page):
    """Read vector grid rectangles directly from PDF content (avoids expensive font outlines)."""
    v=[]; h=[]
    page_height=page.rect.height
    for m in _RECT.finditer(page.read_contents()):
        x,y,w,ht=(float(z) for z in m.groups())
        if 0 < w < 0.8 and ht > 700:
            v.append(round(x + w/2,3))
        if 0 < ht < 0.8 and w > 400:
            h.append(round(page_height-y-ht/2,3))
    return sorted(set(v)),sorted(set(h),reverse=True)

def get_cell_text(characters):
    """Rebuild wrapped cell text by rotated-text baseline and visual reading order."""
    groups = []
    for x, negy, ch in sorted(characters, key=lambda z: (z[0], z[1])):
        if not groups or abs(x - groups[-1][0]) > 0.8:
            groups.append((x, [(negy, ch)]))
        else:
            groups[-1][1].append((negy, ch))
    lines=[]
    for x, pairs in groups:
        line = ''.join(ch for _,ch in sorted(pairs))
        line = re.sub(r'\s+', ' ', line).strip()
        if line:
            lines.append(line)
    return ' '.join(lines)

def extract_page(page, page_num):
    rows, columns = grid_bounds(page)
    flags=[]
    if len(rows)<3:
        return [], {"page": page_num, "error": "no row gridlines", "row_gridlines":len(rows)}
    if len(columns)!=13 or any(abs(a-b) > 2.0 for a,b in zip(columns,DEFAULT_Y)):
        flags.append('nonstandard_column_grid')
    ys=columns if len(columns)==13 else DEFAULT_Y
    cells=collections.defaultdict(list)
    ignored=collections.Counter()
    # Rotated text draws with constant x and descending y per word/line.
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                for char in span['chars']:
                    x,y = char['origin']; s=char['c']
                    ri=bisect.bisect_left(rows,x)-1
                    ci=bisect.bisect_left([-v for v in ys],-y)-1
                    if ri < 1 or ri>=len(rows)-1 or ci<0 or ci>=12:
                        if s.strip():ignored['header_or_margins']+=1
                        continue
                    cells[(ri,ci)].append((round(x,3),-y,s))
                    if s=='\ufffd':
                        ignored['replacement_character']+=1
    result=[]
    for ri in range(1,len(rows)-1):
        r=[get_cell_text(cells[(ri,c)]) for c in range(12)]
        q=[]
        if not r[0].isdigit(): q.append('missing_or_nonnumeric_log_number')
        if not r[1]: q.append('missing_title')
        if not r[6]: q.append('missing_date')
        if not r[7]: q.append('missing_decision')
        if not any(r): q.append('empty_grid_row')
        if '\ufffd' in ' '.join(r): q.append('unmapped_character')
        if flags: q.extend(flags)
        result.append(dict(zip(COLUMNS+META,r+[page_num,ri,'; '.join(q)])))
    return result, {"page":page_num,"grid_rows":len(rows)-2,"grid_columns":len(ys)-1,"ignored_header_chars":ignored['header_or_margins'],"replacement_characters":ignored['replacement_character'],"flags":flags}

def save_csv(file,records,fields):
    with open(file,'w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        writer.writeheader(); writer.writerows(records)

def run(pdf,out_dir):
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    records=[];page_stats=[]
    with fitz.open(pdf) as doc:
        for pi,page in enumerate(doc,1):
            rec,stat=extract_page(page,pi)
            records.extend(rec);page_stats.append(stat)
    # Global audits
    freq=collections.Counter(r['Log Number'] for r in records if r['Log Number'].isdigit())
    ids=[]
    prev_id=None
    for r in records:
        qa=[x.strip() for x in r['QA Flags'].split(';') if x.strip()]
        ident=r['Log Number']
        if ident.isdigit():
            n=int(ident)
            ids.append(n)
            if freq[ident]>1: qa.append('duplicate_log_number')
            if prev_id is not None and n<=prev_id: qa.append('nonincreasing_log_number')
            prev_id=n
        r['QA Flags']='; '.join(sorted(set(qa)))
    save_csv(out_dir/'Censorship_Log_structured.csv',records,COLUMNS+META)
    flagged=[r for r in records if r['QA Flags']]
    save_csv(out_dir/'Censorship_Log_QA_flags.csv',flagged,COLUMNS+META)
    audit={
        "source":str(pdf),"pdf_pages":len(page_stats),"rows_extracted":len(records),
        "numeric_log_numbers":len(ids),"unique_numeric_log_numbers":len(set(ids)),
        "smallest_log_number":min(ids) if ids else None,"largest_log_number":max(ids) if ids else None,
        "missing_numbers_within_range":(max(ids)-min(ids)+1-len(set(ids))) if ids else None,
        "rows_flagged":len(flagged),"qa_flag_counts":dict(collections.Counter(flag.strip() for r in flagged for flag in r['QA Flags'].split(';') if flag.strip())),
        "nonblank_per_field":{col:sum(bool(r[col]) for r in records) for col in COLUMNS},
        "pages_with_nonstandard_grid":[p for p in page_stats if p.get('flags')],
        "pages_with_no_grid":[p for p in page_stats if p.get('error')],
        "page_stats":page_stats,
    }
    (out_dir/'Censorship_Log_extraction_QA.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    return audit

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('pdf');ap.add_argument('--out-dir',default='.')
    a=ap.parse_args()
    audit=run(a.pdf,a.out_dir)
    for k in ['pdf_pages','rows_extracted','numeric_log_numbers','unique_numeric_log_numbers','smallest_log_number','largest_log_number','missing_numbers_within_range','rows_flagged','qa_flag_counts','nonblank_per_field','pages_with_no_grid','pages_with_nonstandard_grid']:
        print(k,':',audit[k])
