"""
extract_data.py  —  airportdb
==============================
Downloads the official MySQL airportdb sample database and exports
every table to CSV — no MySQL installation required.

airportdb: Airport operations — flights, passengers, bookings,
           employees, aircraft, weather. 14 tables, ~56M rows.

Source: https://downloads.mysql.com/docs/airport-db.tar.gz
        Oracle MySQL sample database (CC BY 4.0 adapted from Flughafen DB)

The download is a MySQL Shell Schema Dump (compressed TSV + DDL).
Chunk naming conventions used by MySQL Shell:
  - Single chunk : airportdb@<table>@@0.tsv.zst
  - Multi chunk  : airportdb@<table>@0.tsv.zst, @1.tsv.zst, ...

Usage:
    cd airportdb
    python extract_data.py                  # full download (~640 MB)
    python extract_data.py --skip_download  # reuse existing airport-db/

Output:
    airportdb/csv/<table>.csv   (one file per table)

Requirements:
    pip install zstandard requests
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import tarfile
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DOWNLOAD_URL  = "https://downloads.mysql.com/docs/airport-db.tar.gz"
DUMP_DIR_NAME = "airport-db"

AIRPORTDB_TABLES = [
    "airline",
    "airplane",
    "airplane_type",
    "airport",
    "airport_geo",
    "airport_reachable",
    "booking",
    "employee",
    "flight",
    "flight_log",
    "flightschedule",
    "passenger",
    "passengerdetails",
    "weatherdata",
]


# =============================================================================
# Download
# =============================================================================

def download_dump(dest_dir: Path) -> Path:
    import requests

    tar_path = dest_dir / "airport-db.tar.gz"

    if tar_path.exists():
        log.info("Archive already exists: %s — skipping download", tar_path)
    else:
        log.info("Downloading airportdb (~640 MB) from MySQL ...")
        t0 = time.time()
        with requests.get(DOWNLOAD_URL, stream=True, timeout=300) as r:
            r.raise_for_status()
            total      = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(tar_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  {pct:5.1f}%  {downloaded >> 20} MB / "
                              f"{total >> 20} MB", end="", flush=True)
        print()
        log.info("Download complete in %.1fs  (%d MB)",
                 round(time.time() - t0, 1), tar_path.stat().st_size >> 20)

    dump_dir = dest_dir / DUMP_DIR_NAME
    if not dump_dir.exists():
        log.info("Extracting archive ...")
        t0 = time.time()
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(dest_dir)
        log.info("Extracted in %.1fs → %s", round(time.time() - t0, 1), dump_dir)
    else:
        log.info("Dump directory already exists: %s", dump_dir)

    return dump_dir


# =============================================================================
# Parse column names from DDL
# =============================================================================

def parse_columns_from_ddl(ddl_path: Path) -> list[str]:
    text = ddl_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"CREATE TABLE[^(]*\((.+?)\)\s*ENGINE",
                  text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    columns = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if re.match(r"(PRIMARY|UNIQUE|KEY|CONSTRAINT|INDEX|FULLTEXT)",
                    line, re.IGNORECASE):
            continue
        cm = re.match(r"`([^`]+)`\s+\w", line)
        if cm:
            columns.append(cm.group(1))
    return columns


# =============================================================================
# Find chunk files for a table
# =============================================================================

def find_chunks(table: str, dump_dir: Path) -> list[Path]:
    """
    MySQL Shell uses two naming conventions:
      Single chunk : airportdb@<table>@@0.tsv.zst
      Multi chunk  : airportdb@<table>@0.tsv.zst
                     airportdb@<table>@1.tsv.zst  ...

    Both patterns are tried; .idx sidecar files are excluded.
    Results are sorted numerically by chunk number.
    """
    all_zst = [
        p for p in dump_dir.iterdir()
        if p.suffix == ".zst" and f"@{table}@" in p.name
           and not p.name.endswith(".idx")
    ]

    def chunk_number(p: Path) -> int:
        # Extract the trailing integer from the stem, e.g. "@9" → 9, "@@0" → 0
        m = re.search(r"@+(\d+)\.tsv$", p.stem)
        return int(m.group(1)) if m else 0

    return sorted(all_zst, key=chunk_number)


# =============================================================================
# Convert TSV chunks → CSV
# =============================================================================

def convert_table(table: str, dump_dir: Path, csv_dir: Path) -> int:
    try:
        import zstandard as zstd
    except ImportError:
        raise ImportError("Run: pip install zstandard")

    csv_dir.mkdir(parents=True, exist_ok=True)

    # Column names from DDL
    columns: list[str] = []
    ddl_path = dump_dir / f"airportdb@{table}.sql"
    if ddl_path.exists():
        columns = parse_columns_from_ddl(ddl_path)

    # Chunk files
    chunk_files = find_chunks(table, dump_dir)
    out_path    = csv_dir / f"{table}.csv"

    if not chunk_files:
        log.warning("  No TSV chunks found for: %s", table)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            if columns:
                csv.writer(f).writerow(columns)
        return 0

    log.info("  %d chunk(s) found", len(chunk_files))

    dctx      = zstd.ZstdDecompressor()
    row_count = 0
    t0        = time.time()

    with open(out_path, "w", newline="", encoding="utf-8") as out_f:
        writer     = None
        hdr_written = False

        for chunk_path in chunk_files:
            with open(chunk_path, "rb") as zf:
                raw = dctx.stream_reader(zf).read().replace(b"\x00", b" ")

            reader = csv.reader(
                io.StringIO(raw.decode("utf-8", errors="replace")),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
                escapechar="\\",
            )

            for row in reader:
                if not hdr_written:
                    if not columns:
                        columns = [f"col{i}" for i in range(len(row))]
                    writer = csv.writer(out_f, quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(columns)
                    hdr_written = True

                cleaned = ["" if v == r"\N" else v for v in row]
                writer.writerow(cleaned)
                row_count += 1

    elapsed = round(time.time() - t0, 1)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    log.info("  %-20s  %10d rows  %6.1f MB  %.1fs",
             table, row_count, size_mb, elapsed)
    return row_count


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download airportdb and export tables to CSV."
    )
    parser.add_argument("--work_dir",      default=".",
                        help="Working directory (default: current dir)")
    parser.add_argument("--csv_dir",       default="csv",
                        help="Output CSV directory (default: csv/)")
    parser.add_argument("--skip_download", action="store_true",
                        help="Skip download — use existing airport-db/ folder")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    csv_dir  = (work_dir / args.csv_dir).resolve()

    log.info("=" * 60)
    log.info("airportdb Data Extractor")
    log.info("  Work dir   : %s", work_dir)
    log.info("  CSV output : %s", csv_dir)
    log.info("=" * 60)

    dump_dir = (work_dir / DUMP_DIR_NAME) if args.skip_download \
               else download_dump(work_dir)

    if not dump_dir.exists():
        raise FileNotFoundError(
            f"Dump folder not found: {dump_dir}\n"
            "Run without --skip_download to download it first."
        )

    log.info("Dump folder: %s  (%d files)",
             dump_dir, len(list(dump_dir.iterdir())))

    log.info("\nConverting %d tables to CSV ...", len(AIRPORTDB_TABLES))
    total_rows, failed = 0, []

    for i, table in enumerate(AIRPORTDB_TABLES, 1):
        log.info("[%2d/%d] %s", i, len(AIRPORTDB_TABLES), table)
        try:
            total_rows += convert_table(table, dump_dir, csv_dir)
        except Exception as e:
            log.error("  FAILED: %s — %s", table, e)
            failed.append(table)

    log.info("=" * 60)
    log.info("Done — %d tables, %d total rows", len(AIRPORTDB_TABLES), total_rows)
    if failed:
        log.warning("Failed tables: %s", failed)
    log.info("CSV files → %s/", csv_dir)
    log.info("Next step:")
    log.info("  python ../extract_schema.py --csv_dir csv "
             "--output schema.json --database airportdb")
    log.info("=" * 60)


if __name__ == "__main__":
    main()