"""Add missing Unicode mappings to the Missouri log's embedded Type 3 fonts.

Called by etl/clean_missouri/run_pipeline.py for the 'repair' stage. The
included censorship_glyphs.csv already contains the manually established
character map; it must not be replaced with an empty inspector template.

    python decode_censorship_pdf.py original.pdf --glyphs censorship_glyphs.csv --out fixed.pdf

The script matches embedded glyph drawings by SHA-256 hash, adds /ToUnicode
CMaps, and writes a new PDF. It does not OCR, redraw, or modify visible pages.
"""
from __future__ import annotations
import argparse, csv, hashlib, re
from pathlib import Path
import fitz

REF = re.compile(r'/([^\s/<>\[\]]+)\s+(\d+)\s+0\s+R')

def get_character_map(doc, fontxref, known_hashes):
    cpx=doc.xref_get_key(fontxref,'CharProcs')
    enx=doc.xref_get_key(fontxref,'Encoding')
    if cpx[0]!='xref' or enx[0]!='xref':return {}
    cpdict=int(cpx[1].split()[0]);encx=int(enx[1].split()[0])
    glyph_names={name:int(xref) for name,xref in REF.findall(doc.xref_object(cpdict))}
    enc=doc.xref_object(encx)
    match=re.search(r'/Differences\s*\[(.*?)\]',enc,re.S)
    if not match: return {}
    pos=0;out={}
    for token in re.findall(r'/[^\s\[\]]+|\d+',match.group(1)):
        if token[0]=='/':
            name=token[1:]
            if name == 'i255':
                out[pos] = ' '  # blank glyph used for word separation
            if name in glyph_names:
                digest=hashlib.sha256(doc.xref_stream(glyph_names[name])).hexdigest()
                value=known_hashes.get(digest)
                if value:out[pos]=value
            pos+=1
        else:
            pos=int(token)
    return out

def cmap_for_mapping(mapping):
    pieces=["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
            "1 begincodespacerange", "<00> <FF>", "endcodespacerange"]
    entries=sorted(mapping.items())
    for i in range(0,len(entries),100):
        sub=entries[i:i+100]
        pieces.append(f'{len(sub)} beginbfchar')
        for code,ch in sub:
            utf16=ch.encode('utf-16-be').hex().upper()
            pieces.append(f'<{code:02X}> <{utf16}>')
        pieces.append('endbfchar')
    pieces.extend(['endcmap','CMapName currentdict /CMap defineresource pop','end','end',''])
    return '\n'.join(pieces).encode('ascii')

def run(pdf, csv_path, out):
    with open(csv_path,encoding='utf8',newline='') as f: rows=list(csv.DictReader(f))
    incomplete=[r['glyph_id'] for r in rows if not r['unicode_character']]
    if incomplete:
        raise ValueError(f'Untranslated glyph(s): {", ".join(incomplete[:20])} ({len(incomplete)} total)')
    mapping={r['sha256']:r['unicode_character'] for r in rows}
    doc=fitz.open(pdf)
    for page in doc:
        for fontxref, _ext, typ, _base, _res, _ in page.get_fonts():
            if typ!='Type3':continue
            transl=get_character_map(doc,fontxref,mapping)
            if not transl:continue
            x=doc.get_new_xref()
            doc.update_object(x,'<< >>')
            doc.update_stream(x,cmap_for_mapping(transl))
            doc.xref_set_key(fontxref,'ToUnicode',f'{x} 0 R')
    doc.save(out,garbage=3,deflate=True)
    doc.close()
    print('Saved',out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pdf');p.add_argument('--glyphs',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(a.pdf,a.glyphs,a.out)
