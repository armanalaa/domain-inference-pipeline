"""
extract_data.py  —  TPC-DS
==========================
Generates the TPC-DS benchmark dataset using DuckDB's built-in tpcds
extension (no dsdgen download required) and exports every table to CSV.

TPC-DS: Retail data warehouse — catalog, store and web sales
24 tables, scale factor configurable (default SF=1 → ~1 GB raw data)

Usage:
    cd tpcds
    python extract_data.py              # SF=1
    python extract_data.py --sf 0.1     # ~100 MB, fast for testing
    python extract_data.py --sf 10      # ~10 GB

Output:
    tpcds/csv/<TableName>.csv           (one file per table)

Requirements:
    pip install duckdb
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# TPC-DS 24 tables
TPCDS_TABLES = [
    "call_center",
    "catalog_page",
    "catalog_returns",
    "catalog_sales",
    "customer",
    "customer_address",
    "customer_demographics",
    "date_dim",
    "household_demographics",
    "income_band",
    "inventory",
    "item",
    "promotion",
    "reason",
    "ship_mode",
    "store",
    "store_returns",
    "store_sales",
    "time_dim",
    "warehouse",
    "web_page",
    "web_returns",
    "web_sales",
    "web_site",
]


def generate_tpcds(sf: float, db_path: Path) -> None:
    """Generate TPC-DS data into a DuckDB database file."""
    import duckdb

    # Remove existing DB to avoid "table already exists" error
    if db_path.exists():
        log.info("Removing existing database: %s", db_path)
        db_path.unlink()

    log.info("Connecting to DuckDB: %s", db_path)
    con = duckdb.connect(str(db_path))

    log.info("Installing and loading TPC-DS extension ...")
    con.execute("INSTALL tpcds;")
    con.execute("LOAD tpcds;")

    log.info("Generating TPC-DS data at SF=%.2f (this may take a few minutes) ...", sf)
    t0 = time.time()
    con.execute(f"CALL dsdgen(sf={sf});")
    elapsed = round(time.time() - t0, 1)
    log.info("Data generation complete in %.1fs", elapsed)

    con.close()


def export_csvs(db_path: Path, csv_dir: Path) -> None:
    """Export every TPC-DS table from DuckDB to a CSV file."""
    import duckdb

    csv_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)

    log.info("Exporting %d tables to %s ...", len(TPCDS_TABLES), csv_dir)
    for i, table in enumerate(TPCDS_TABLES, 1):
        out = csv_dir / f"{table}.csv"
        t0  = time.time()
        con.execute(
            f"COPY {table} TO '{out.as_posix()}' (HEADER, DELIMITER ',');"
        )
        rows   = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        elapsed = round(time.time() - t0, 2)
        log.info("  [%2d/24] %-30s  %10d rows  %.2fs", i, table, rows, elapsed)

    con.close()
    log.info("All CSVs written to %s", csv_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TPC-DS data and export to CSV using DuckDB."
    )
    parser.add_argument(
        "--sf", type=float, default=1.0,
        help="Scale factor (default: 1.0 ≈ 1 GB). Use 0.1 for quick tests."
    )
    parser.add_argument(
        "--db", default="tpcds.duckdb",
        help="DuckDB database file path (default: tpcds.duckdb)"
    )
    parser.add_argument(
        "--csv_dir", default="csv",
        help="Output directory for CSV files (default: csv/)"
    )
    parser.add_argument(
        "--skip_generate", action="store_true",
        help="Skip data generation — only export CSVs from existing DB"
    )
    args = parser.parse_args()

    db_path  = Path(args.db)
    csv_dir  = Path(args.csv_dir)

    log.info("=" * 60)
    log.info("TPC-DS Data Extractor")
    log.info("  Scale factor : SF=%.2f", args.sf)
    log.info("  Database     : %s", db_path)
    log.info("  CSV output   : %s", csv_dir)
    log.info("=" * 60)

    if not args.skip_generate:
        generate_tpcds(args.sf, db_path)
    else:
        if not db_path.exists():
            raise FileNotFoundError(
                f"--skip_generate set but DB not found: {db_path}"
            )
        log.info("Skipping generation — using existing %s", db_path)

    export_csvs(db_path, csv_dir)

    log.info("=" * 60)
    log.info("Done. Next step:")
    log.info("  python ../extract_schema.py --csv_dir csv "
             "--output schema.json --database TPC-DS")
    log.info("=" * 60)


if __name__ == "__main__":
    main()