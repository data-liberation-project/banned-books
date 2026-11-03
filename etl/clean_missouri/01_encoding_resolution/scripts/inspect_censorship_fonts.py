"""Produce an atlas of unique Type 3 glyph outlines from a PDF.

Requires: PyMuPDF, Pillow, reportlab.  No OCR is used.

Each ID in the atlas identifies an actual glyph drawing (hash of its CharProc).
The CSV maps each occurrence of that drawing to the page-specific PDF code.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import re
from collections import Counter
from pathlib import Path
import fitz
from reportlab.pdfgen import canvas
from PIL import Image

REF = re.compile(r"/(\d+)\s+(\d+)\s+0\s+R")
NUM = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

def glyphs_of(doc):
    entries = []
    occurrences = []
    by_hash = {}
    for page_index, page in enumerate(doc):
        for fontxref, _ext, subtype, _basefont, _resource, _ in page.get_fonts():
            if subtype != "Type3":
                continue
            fontobj = doc.xref_get_key(fontxref, "CharProcs")
            if fontobj[0] != "xref":
                continue
            dictxref = int(fontobj[1].split()[0])
            for code, procxref in REF.findall(doc.xref_object(dictxref)):
                code, procxref = int(code), int(procxref)
                stream = doc.xref_stream(procxref)
                digest = hashlib.sha256(stream).hexdigest()
                if digest not in by_hash:
                    by_hash[digest] = len(entries)
                    entries.append({"glyph_id": f"G{len(entries):03d}", "hash": digest,
                                    "data": stream, "example_page": page_index + 1,
                                    "example_code": code})
                occurrences.append((page_index + 1, code, entries[by_hash[digest]]["glyph_id"], digest))
    return entries, occurrences

def pdf_glyph_path(pdfpath, stream: bytes):
    """Draw path commands from this PDF's glyph streams into a ReportLab path.

    This is a minimal parser for these specific Type 3 glyphs (d1/i/q/cm/m/l/c/f/Q);
    it isn't a general PDF graphics interpreter.
    """
    # Glyphs are all centered horizontally within approx 1 em (and 0.8 high).
    tokens = stream.decode('latin1').split()
    args=[]; paths=[]; cur=None; cm=(1.,0.,0.,1.,0.,0.)
    for t in tokens:
        if NUM.fullmatch(t):
            args.append(float(t)); continue
        if t == 'cm':
            cm=tuple(args[-6:]); args=[]; continue
        if t == 'm':
            if cur is None: cur = pdfpath
            x,y=args[-2:];a,b,c,d,e,f=cm
            cur.moveTo(a*x+c*y+e, b*x+d*y+f)
        elif t=='l':
            x,y=args[-2:];a,b,c,d,e,f=cm
            pdfpath.lineTo(a*x+c*y+e,b*x+d*y+f)
        elif t=='c':
            v=args[-6:]; a,b,c,d,e,f=cm
            v2=[(a*v[i]+c*v[i+1]+e,b*v[i]+d*v[i+1]+f) for i in (0,2,4)]
            pdfpath.curveTo(*(v2[0]+v2[1]+v2[2]))
        elif t == 'h': pdfpath.close()
        args=[]

def write_outputs(doc, outstem: Path):
    entries, occ=glyphs_of(doc)
    counts=Counter(x[2] for x in occ)
    # Display frequently used glyphs first
    entries.sort(key=lambda e: (-counts[e['glyph_id']], e['glyph_id']))
    lookup={e['glyph_id']: f'G{i:03}' for i,e in enumerate(entries)}
    for i,e in enumerate(entries): e['glyph_id']=f'G{i:03}'
    occ=[(p,code,lookup[g],h) for p,code,g,h in occ]
    with open(str(outstem)+'_glyphs.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['glyph_id','sha256','occurrences','example_page','example_code','unicode_character'])
        for e in entries:w.writerow([e['glyph_id'],e['hash'],counts[next(k for k,v in lookup.items() if v==e['glyph_id'])],e['example_page'],e['example_code'],''])
    with open(str(outstem)+'_page_codes.csv','w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['page_number','pdf_character_code','glyph_id','sha256']);w.writerows(occ)
    pdfpath=str(outstem)+'_atlas.pdf'
    cv=canvas.Canvas(pdfpath,pagesize=(612,792))
    cv.setTitle('PDF Type3 character atlas')
    COLS=8;ROWS=10;CELL_W=75;CELL_H=73
    for ix,e in enumerate(entries):
        pos=ix%(COLS*ROWS)
        if ix and pos==0:cv.showPage()
        col=pos%COLS;row=pos//COLS
        x=7+col*CELL_W;y=792-17-(row+1)*CELL_H
        cv.setLineWidth(.25);cv.setStrokeColorRGB(.73,.73,.73); cv.rect(x,y,CELL_W-2,CELL_H-2,fill=0,stroke=1)
        cv.setFillColorRGB(.10,.10,.10);cv.setFont('Helvetica',9);cv.drawString(x+4,y+5,f"{e['glyph_id']}  ({counts[next(k for k,v in lookup.items() if v==e['glyph_id'])]})")
        cv.saveState()
        # Normalized PDF glyph coordinates; amplify to 62pt, centered into cell
        cv.translate(x+10,y+24)
        cv.scale(72,72)
        p=cv.beginPath()
        pdf_glyph_path(p,e['data'])
        cv.setFillColorRGB(0,0,0);cv.drawPath(p,fill=1,stroke=0,fillMode=0)
        cv.restoreState()
    cv.save()
    print('Unique drawings:',len(entries),'occurrences:',len(occ),'atlas:',pdfpath)
    return pdfpath

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('pdf');ap.add_argument('--output',default='pdf_glyphs');opts=ap.parse_args()
    write_outputs(fitz.open(opts.pdf),Path(opts.output))
