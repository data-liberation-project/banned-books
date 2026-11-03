#!/usr/bin/env python3
"""Run the Missouri censorship-log extraction and cleaning pipeline.

Run from any working directory, after placing the original public-records PDF
under data/raw/missouri/ in the banned-books repository:

    python etl/clean_missouri/run_pipeline.py --stage all

The three stages are:
    repair    Add Unicode mappings to the PDF's embedded Type 3 fonts.
    extract   Recover the spreadsheet-style table and create QA files.
    simplify  Produce the repository's five-column standardized CSV.

Generated working files stay under etl/clean_missouri/interim/. Only the final
CSV is written to data/processed/cleaned_missouri.csv. No OCR or API is used.
The original PDF is always read-only and never overwritten.

See README.md in this directory for source, limitations, and validation details.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ETL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ETL_ROOT.parents[1]  # .../repo/etl/clean_missouri -> .../repo
ENCODING = ETL_ROOT / "01_encoding_resolution"
EXTRACTION = ETL_ROOT / "02_data_extraction"
RAW_DIR = REPO_ROOT / "data" / "raw" / "missouri"
INTERIM_DIR = ETL_ROOT / "interim"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

EXPECTED_SOURCE_NAME = "Censorship_Log-After_11-12-14_version_1.pdf"
GLYPHS = ENCODING / "mappings" / "censorship_glyphs.csv"
FIXED = INTERIM_DIR / "Censorship_Log_unicode_repaired.pdf"
STRUCTURED = INTERIM_DIR / "Censorship_Log_structured.csv"
CLEANED = PROCESSED_DIR / "cleaned_missouri.csv"


def raw_source(override: str | None) -> Path:
    """Prefer original filename; accept a sole renamed PDF or explicit override."""
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if not candidate.is_file():
            raise FileNotFoundError(f"Specified source PDF does not exist: {candidate}")
        return candidate.resolve()
    expected = RAW_DIR / EXPECTED_SOURCE_NAME
    if expected.is_file():
        return expected
    available = sorted(RAW_DIR.glob("*.pdf")) if RAW_DIR.is_dir() else []
    if len(available) == 1:
        return available[0]
    if not available:
        raise FileNotFoundError(
            f"No input PDF found in {RAW_DIR}. Place the FOIA PDF there "
            "or specify --input-pdf data/raw/missouri/your_file.pdf"
        )
    raise ValueError(
        f"Multiple PDFs found in {RAW_DIR}. Specify --input-pdf to choose one. "
        f"Candidates: {', '.join(p.name for p in available)}"
    )


def command(script: Path, *arguments: object) -> None:
    cmd = [sys.executable, str(script), *(str(x) for x in arguments)]
    print("> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def repair(source_pdf: Path) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    temporary = FIXED.with_name(FIXED.stem + "_building.pdf")
    try:
        command(
            ENCODING / "scripts" / "decode_censorship_pdf.py",
            source_pdf, "--glyphs", GLYPHS, "--out", temporary,
        )
        os.replace(temporary, FIXED)
    finally:
        temporary.unlink(missing_ok=True)


def extract() -> None:
    if not FIXED.is_file():
        raise FileNotFoundError(
            f"Repaired PDF missing: {FIXED}. Run --stage repair first."
        )
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    command(
        EXTRACTION / "scripts" / "extract_censorship_log.py",
        FIXED, "--out-dir", INTERIM_DIR,
    )


def simplify() -> None:
    if not STRUCTURED.is_file():
        raise FileNotFoundError(
            f"Structured CSV missing: {STRUCTURED}. Run --stage extract first."
        )
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    command(
        EXTRACTION / "scripts" / "simplify_censorship_log.py",
        STRUCTURED, CLEANED,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--stage", choices=("all", "repair", "extract", "simplify"), default="all",
        help="Run the full ETL or only one stage (default: all).",
    )
    parser.add_argument(
        "--input-pdf", default=None,
        help="Optional PDF path, absolute or relative to the repository root.",
    )
    parser.add_argument(
        "--show-paths", action="store_true",
        help="Print resolved paths without running the pipeline.",
    )
    args = parser.parse_args()
    if args.show_paths:
        for label, path in (
            ("Repository root", REPO_ROOT),
            ("Raw PDF directory", RAW_DIR),
            ("Encoding mapping", GLYPHS),
            ("Repaired PDF", FIXED),
            ("Structured CSV", STRUCTURED),
            ("QA flags CSV", INTERIM_DIR / "Censorship_Log_QA_flags.csv"),
            ("QA summary JSON", INTERIM_DIR / "Censorship_Log_extraction_QA.json"),
            ("Final cleaned CSV", CLEANED),
        ):
            print(f"{label}: {path}")
        return
    if args.stage in ("all", "repair"):
        repair(raw_source(args.input_pdf))
    if args.stage in ("all", "extract"):
        extract()
    if args.stage in ("all", "simplify"):
        simplify()
    if args.stage in ("all", "simplify"):
        print(f"Completed stage '{args.stage}'. Final CSV: {CLEANED}")
    else:
        print(f"Completed stage '{args.stage}'. Intermediate files: {INTERIM_DIR}")


if __name__ == "__main__":
    main()
