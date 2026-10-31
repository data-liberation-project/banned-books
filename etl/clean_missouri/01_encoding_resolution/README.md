# PDF character-encoding repair

This stage repairs the text layer in Missouri's public-records censorship-log
PDF without rasterization or OCR. The original PDF visually displays readable
characters, but ordinary text extraction is garbled because its Type 3 fonts
lack a usable Unicode character map. The font repair script adds `/ToUnicode`
character maps to a new copy of the PDF based on a curated mapping of distinct
glyph drawings. No text is composed or inferred from the printed pages.

Run from the banned-books repository root, after installing dependencies
(`etl/clean_missouri/requirements.txt`) and placing the source PDF in
`data/raw/missouri/`:

```sh
python etl/clean_missouri/run_pipeline.py --stage repair
```

**Output:** `etl/clean_missouri/interim/Censorship_Log_unicode_repaired.pdf`

## Included files

- `scripts/decode_censorship_pdf.py`: reads the original PDF and completed
  `mappings/censorship_glyphs.csv`; writes a copy with Unicode mapping streams.
- `mappings/censorship_glyphs.csv`: **completed** translations
  from character-drawing hashes to Unicode characters; essential to run.
- `mappings/censorship_page_codes.csv`: auxiliary list of character code
  occurrences on each page, for mapping provenance and investigation.
- `reference/censorship_atlas.pdf`: visual contact sheet of the distinct glyphs.
- `scripts/inspect_censorship_fonts.py`: optional utility to regenerate a glyph
  atlas and **blank** mapping template for a PDF; this is not part of the
  standard run. Use an output prefix in a scratch location so it cannot
  overwrite the completed mapping.
- `scripts/export_decoded_text.py`: optional plain-text inspection utility.

The mapping uses the glyph stream's SHA-256 digest, not the byte value of a
character code, because the same code may mean different characters on
different pages. The map is source-specific. The reconstructed spreadsheet
remains a separate stage; repairing the text layer alone does not recover
column structure.

See `../README.md` for complete workflow and caveats.
