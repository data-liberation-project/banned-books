#!/usr/bin/env python3
"""Extract readable page-by-page text from the repaired Unicode PDF."""
import argparse
from pathlib import Path
import fitz

parser=argparse.ArgumentParser()
parser.add_argument('input_pdf',type=Path)
parser.add_argument('output_txt',type=Path)
args=parser.parse_args()
with fitz.open(args.input_pdf) as pdf, args.output_txt.open('w',encoding='utf-8') as out:
    for n,page in enumerate(pdf,1):
        out.write(f'===== PDF PAGE {n} =====\n')
        out.write(page.get_text())
        out.write('\n')
print(f'Extracted {n} pages to {args.output_txt}')
