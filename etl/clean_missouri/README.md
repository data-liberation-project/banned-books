# Missouri: Prison-publication censorship log ETL

This directory contains the Python pipeline for converting Missouri's
**Censorship Log** (a PDF obtained through a public-records request) into the
five-column format used by the [Data Liberation Project's banned-books
repository](https://github.com/data-liberation-project/banned-books).

The source is a 226-page, landscape/sideways PDF generated from a spreadsheet.
Its tables are visible when opened in a PDF viewer, but ordinary text
extraction produces incorrect characters because the PDF's custom Type 3 fonts
lack usable Unicode mappings. This pipeline first repairs those mappings,
then reconstructs the table from the PDF's text coordinates and gridlines,
and finally standardizes five fields. **It does not perform OCR, call an AI
service, or change the original PDF.**

## Quick start

**Requirements:** Python 3.10 or newer; the PDF source file; and dependencies
listed in `requirements.txt`. Run these commands from the repository root:

```sh
python -m pip install -r etl/clean_missouri/requirements.txt
python etl/clean_missouri/run_pipeline.py --show-paths
python etl/clean_missouri/run_pipeline.py --stage all
```

On success, the final output is **`data/processed/cleaned_missouri.csv`**.
The runner locates the repository root from the location of `run_pipeline.py`,
so the command also works when invoked from a different working directory.

The PDF should be placed at:

`data/raw/missouri/Censorship_Log-After_11-12-14_version_1.pdf`

If that filename is different and there is exactly one PDF in the source
directory, the runner uses it. With multiple PDFs, supply the intended file
explicitly:

```sh
python etl/clean_missouri/run_pipeline.py --stage all --input-pdf data/raw/missouri/filename.pdf
```

The pipeline does not download the source PDF. Anyone reproducing these
results must obtain the public-records PDF and put it in `data/raw/missouri/`
before running the workflow.

## Repository paths

```text
banned-books/
├── data/
│   ├── raw/
│   │   └── missouri/
│   │       └── Censorship_Log-After_11-12-14_version_1.pdf   [input]
│   └── processed/
│       └── cleaned_missouri.csv                            [final output]
└── etl/
    └── clean_missouri/
        ├── README.md
        ├── requirements.txt
        ├── run_pipeline.py                                  [entry point]
        ├── 01_encoding_resolution/
        │   ├── README.md
        │   ├── scripts/                                    [font repair]
        │   ├── mappings/                                   [completed glyph mapping]
        │   └── reference/                                  [glyph atlas]
        ├── 02_data_extraction/
        │   ├── README.md
        │   └── scripts/                                    [table extraction, cleanup]
        └── interim/                                        [generated, git-ignored]
            ├── Censorship_Log_unicode_repaired.pdf
            ├── Censorship_Log_structured.csv
            ├── Censorship_Log_QA_flags.csv
            └── Censorship_Log_extraction_QA.json
```

All intermediate outputs live under **`etl/clean_missouri/interim/`**, not
under `data/`. The `interim/.gitignore` file keeps these reproducible outputs
out of version control; the runner creates the directory if necessary.
No changes to the repository-level `.gitignore` are required.

## Pipeline stages

| Stage | Script | Reads | Produces |
| --- | --- | --- | --- |
| `repair` | `01_encoding_resolution/scripts/decode_censorship_pdf.py` | Original PDF; `mappings/censorship_glyphs.csv` | `interim/Censorship_Log_unicode_repaired.pdf` |
| `extract` | `02_data_extraction/scripts/extract_censorship_log.py` | Repaired PDF | `interim/Censorship_Log_structured.csv`, QA flags CSV, QA summary JSON |
| `simplify` | `02_data_extraction/scripts/simplify_censorship_log.py` | Structured CSV | `data/processed/cleaned_missouri.csv` |

For a partial rerun, select the corresponding stage:

```sh
python etl/clean_missouri/run_pipeline.py --stage repair
python etl/clean_missouri/run_pipeline.py --stage extract
python etl/clean_missouri/run_pipeline.py --stage simplify
```

The `extract` stage requires a previously repaired PDF; `simplify` requires a
previously extracted structured CSV. A full run (`--stage all`) runs all three
in order. A stage overwrites its own generated outputs, not the source PDF.

### 1. Repair the PDF character encoding

The embedded Type 3 fonts contain drawings for letters and numbers, but the
PDF does not supply the Unicode mappings needed for text extraction. The
repair script matches the embedded glyph drawing to a curated translation
using its SHA-256 hash. It adds `/ToUnicode` maps to a *new* PDF, leaving the
original untouched and retaining the original layout. This mapping was
constructed for this particular source PDF and should not be assumed to work
on unrelated PDFs.

- `mappings/censorship_glyphs.csv` contains the completed character mappings
  required to run the repair step.
- `mappings/censorship_page_codes.csv` contains a reference audit of page-level
  character codes and their glyph drawings; it is not necessary for normal
  pipeline execution.
- `reference/censorship_atlas.pdf` provides visual examples of the distinct
  glyph drawings used to establish the mapping.
- `scripts/inspect_censorship_fonts.py` is an optional diagnostic utility. It
  generates a **blank** mapping template; do not run it with an output prefix
  that would overwrite the completed mapping CSV.

See `01_encoding_resolution/README.md` for diagnostic details.

### 2. Reconstruct the spreadsheet table

The original document is a printed spreadsheet with 12 source columns.
Extraction uses the repaired PDF's character coordinates and vector gridlines
to assign text to cells, including wrapped text. Source PDF page numbers and
within-page row numbers are retained in the structured CSV for verification.
No AI-derived content is added. The source includes fields such as title,
volume/issue, publisher, sender, censorship reason, censorship letter date,
appeal/decision, comments, and policy-related fields attributed to three
reviewers.

The `interim/` files are deliberately more detailed than the final dataset:

- `Censorship_Log_structured.csv`: reconstructed original columns plus
  `Source PDF Page`, `Source Page Row`, and `QA Flags`.
- `Censorship_Log_QA_flags.csv`: subset of rows flagged by consistency checks.
- `Censorship_Log_extraction_QA.json`: page-level and overall statistics,
  including missing-field and numbering checks.

The QA flags identify potential extraction issues, not necessarily errors in
the source document. In particular, gaps in the log's numbering **are not**
evidence that records were lost from the PDF.

### 3. Produce the standardized five-column dataset

The output follows the schema in the repository's main README:

| Column | Derivation | Interpretation |
| --- | --- | --- |
| `title` | `Title of Publication`, whitespace normalized | Source title, not externally verified bibliographic metadata |
| `author` | Not provided by the dataset and intentionally left blank | Blank by default |
| `date` | `Censorship Letters Sent Out Date`, parsed as `YYYY-MM-DD` | Date of the letter, **not necessarily** the review, rejection, or final ban date |
| `publication_type` | Not provided by the dataset and intentionally left blank | Blank by default |
| `rejection_reason` | Combines the four fields below with ` \| ` separators | Source wording, not a standardized code list |

The `rejection_reason` fields are concatenated in this order:

1. `Reason for Censorship`
2. `Ryan Crews Number for Policy`
3. `Jason Lewis Number for Policy`
4. `Earl Dye Number for Policy`
5. `Justification/Comments`

Blank values are skipped. Repeated text is included once, using a
case-insensitive comparison that ignores minor trailing punctuation. The
first occurrence's wording is retained. Multiple distinct values are
separated by ` | `.

**Important:** An entry in this censorship log should not automatically be
interpreted as proof that a publication remained banned following an appeal.
The original `Appeal Ltr & Final Decision` field is retained in the interim
CSV but not the five-column output. Users needing final decision status should
review that field and the underlying document.

## Validation and known limitations

The existing reconstruction of this source produced the following checks.
These numbers are **reference values**, not hard-coded expectations; rerun
results should be compared to the source if they change.

| Check | Reference |
| --- | ---: |
| Source PDF pages | 226 |
| Structured and cleaned records | 5,138 |
| Flagged records | 36 |
| Records with distinct, pipe-separated reason entries | 5,138 |
| Records with a nonblank parsed date | 5,133 |

The 36 flagged records include 28 rows on pages 225–226 with an unusual
column grid, five records without a recorded letter date, and a small number
of numbering anomalies (categories can overlap). The extraction uses the
standard column boundaries on those final pages. Check the QA CSV against the
source PDF before publishing or using flagged records in high-stakes analysis.

The text repair avoids OCR recognition errors but does not independently
verify every recovered character, table boundary, date, or inferred author.
The script may misclassify a publication type when its title contains a media
keyword. The output retains one row per reconstructed log entry, including
entries for publications other than books.

## Maintenance and contribution notes

- Keep the PDF in `data/raw/missouri/` unchanged. The scripts do not edit it.
- Keep the completed glyph mapping in version control; it is necessary for
  a reproducible repair without repeating the manual character identification.
- Do not commit generated files under `etl/clean_missouri/interim/`.
- Commit the final `data/processed/cleaned_missouri.csv` if that is the
  repository's established practice for other state outputs.
- If updating the extraction or title/author/type inference rules, rerun the
  pipeline and examine both the QA outputs and changes to the final CSV.
- The `--show-paths` option prints all absolute paths used by the runner and
  is a useful first check when working in a fork or separate checkout.
