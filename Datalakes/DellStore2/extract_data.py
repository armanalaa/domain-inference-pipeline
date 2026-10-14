"""
extract_csv_from_sql.py
=======================
Extracts CSV files from a PostgreSQL SQL dump (dellstore2-normal-1.0.sql).

PostgreSQL dumps store data as tab-separated COPY blocks:
    COPY tablename (col1, col2, ...) FROM stdin;
    val1\tval2\t...
    \.

This script converts each block → a proper CSV file with a header row.

Usage:
    python extract_csv_from_sql.py --sql dellstore2-normal-1.0.sql --out_dir csv/

Optional:
    --tables categories customers orders orderlines products inventory reorder
        (filter to specific tables; default: all business tables, skip pg_ts_*)
"""

import argparse
import csv
import io
import re
from pathlib import Path

# Tables to skip (PostgreSQL internal full-text search extension tables)
SKIP_TABLES = {"pg_ts_cfg", "pg_ts_cfgmap", "pg_ts_dict", "pg_ts_parser"}

# Regex to match:  COPY tablename (col1, col2, ...) FROM stdin;
COPY_RE = re.compile(
    r"^COPY\s+(\w+)\s*\(([^)]+)\)\s+FROM\s+stdin\s*;",
    re.IGNORECASE,
)


def extract_tables(sql_path: Path, out_dir: Path, only_tables: set[str] | None):
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    with sql_path.open("r", encoding="utf-8", errors="replace") as fh:
        in_copy = False
        table_name = ""
        columns: list[str] = []
        rows: list[list[str]] = []

        for raw_line in fh:
            line = raw_line.rstrip("\n")

            if not in_copy:
                m = COPY_RE.match(line)
                if m:
                    table_name = m.group(1).lower()
                    columns = [c.strip() for c in m.group(2).split(",")]
                    rows = []
                    in_copy = True
            else:
                if line == "\\.":          # end-of-COPY marker
                    in_copy = False
                    # decide whether to write this table
                    skip = table_name in SKIP_TABLES
                    if only_tables:
                        skip = skip or (table_name not in only_tables)
                    if not skip:
                        out_path = out_dir / f"{table_name}.csv"
                        _write_csv(out_path, columns, rows)
                        results.append(
                            f"  OK  {table_name}.csv  "
                            f"({len(rows):,} rows, {len(columns)} cols)"
                        )
                    else:
                        results.append(f"  --  {table_name}  (skipped)")
                else:
                    # Tab-separated values; handle \N (PostgreSQL NULL)
                    fields = [
                        "" if f == r"\N" else f.replace(r"\t", "\t").replace(r"\n", "\n")
                        for f in line.split("\t")
                    ]
                    rows.append(fields)

    return results


def _write_csv(path: Path, columns: list[str], rows: list[list[str]]):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Extract CSV files from a PostgreSQL SQL dump."
    )
    parser.add_argument(
        "--sql", required=True,
        help="Path to the .sql dump file (e.g. dellstore2-normal-1.0.sql)"
    )
    parser.add_argument(
        "--out_dir", default="csv",
        help="Output directory for CSV files (default: ./csv)"
    )
    parser.add_argument(
        "--tables", nargs="*", default=None,
        help="Specific tables to extract (default: all except pg_ts_* system tables)"
    )
    args = parser.parse_args()

    sql_path = Path(args.sql).resolve()
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    out_dir  = Path(args.out_dir).resolve()
    only     = set(t.lower() for t in args.tables) if args.tables else None

    print(f"\nDellStore2 CSV extractor")
    print(f"  SQL file : {sql_path}")
    print(f"  Out dir  : {out_dir}")
    print(f"  Filter   : {', '.join(sorted(only)) if only else 'all (skip pg_ts_*)'}\n")

    results = extract_tables(sql_path, out_dir, only)
    for r in results:
        print(r)

    written = sum(1 for r in results if r.strip().startswith("OK"))
    print(f"\n  Done — {written} CSV files written to {out_dir}\n")


if __name__ == "__main__":
    main()