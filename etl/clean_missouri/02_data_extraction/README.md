# Table reconstruction and standardized Missouri CSV

This stage turns the Unicode-repaired Missouri censorship-log PDF into a
structured table, then into the five-column dataset specified by the
Data Liberation Project banned-books repository. It requires the preceding
font-repair stage to have completed successfully.

From the repository root:

```sh
python etl/clean_missouri/run_pipeline.py --stage extract
python etl/clean_missouri/run_pipeline.py --stage simplify
```

The `extract` script uses character coordinates and PDF vector gridlines to
reconstruct the 12 original spreadsheet columns. Its outputs stay in
`etl/clean_missouri/interim/`:

- `Censorship_Log_structured.csv` (full source columns and source references)
- `Censorship_Log_QA_flags.csv` (records flagged for review)
- `Censorship_Log_extraction_QA.json` (per-page and overall quality metrics)

The `simplify` script reads the structured CSV and writes only
`data/processed/cleaned_missouri.csv`, with the columns `title`, `author`,
`date`, `publication_type`, and `rejection_reason`.

The final `rejection_reason` combines `Reason for Censorship`,
`Ryan Crews Number for Policy`, `Jason Lewis Number for Policy`, and
`Earl Dye Number for Policy`, in that order. Duplicate nonempty text is
removed, and distinct entries are separated by ` | `.

The `date` is based on **Censorship Letters Sent Out Date**, not on a
separate confirmed ban date. Author and publication type are extracted using
conservative heuristics; they may be blank. An entry should not automatically
be treated as a final upheld ban; the structured table retains appeal and
decision information for closer review. Read `../README.md` for QA counts,
full derivations, and known limitations.
