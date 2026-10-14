"""
Add CSV header rows from a simple CREATE TABLE SQL schema.

Example:
  python extract_data.py

Default paths are resolved relative to this script:
  schema SQL : data/schematext.sql
  input CSVs : data/*.csv
  output CSVs: csv/*.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?P<table>\"?[A-Za-z_][\w]*\"?)\s*\((?P<body>.*?)\);",
    re.IGNORECASE | re.DOTALL,
)


def clean_identifier(value: str) -> str:
    value = value.strip().strip('"')
    return value


def parse_schema(sql_path: Path) -> dict[str, list[str]]:
    text = sql_path.read_text(encoding="utf-8", errors="replace")
    schema: dict[str, list[str]] = {}

    for match in CREATE_TABLE_RE.finditer(text):
        table = clean_identifier(match.group("table"))
        body = match.group("body")
        columns: list[str] = []

        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line:
                continue
            first = line.split(None, 1)[0]
            first_clean = clean_identifier(first)
            if first_clean.upper() in {
                "PRIMARY",
                "FOREIGN",
                "UNIQUE",
                "CHECK",
                "CONSTRAINT",
                "KEY",
            }:
                continue
            columns.append(first_clean)

        schema[table] = columns

    return schema


def first_csv_row_width(path: Path) -> int | None:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return len(next(reader))
        except StopIteration:
            return None


def write_with_header(input_path: Path, output_path: Path, columns: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = ",".join(columns).encode("utf-8") + b"\n"

    with input_path.open("rb") as src, output_path.open("wb") as dst:
        dst.write(header)
        shutil.copyfileobj(src, dst, length=1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepend CSV headers from CREATE TABLE SQL definitions.")
    parser.add_argument("--schema_sql", type=Path, default=Path("data/schematext.sql"), help="SQL file with CREATE TABLE statements")
    parser.add_argument("--input_dir", type=Path, default=Path("data"), help="Folder containing headerless CSV files")
    parser.add_argument("--output_dir", type=Path, default=Path("csv"), help="Folder to write CSV files with headers")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    schema_sql = args.schema_sql if args.schema_sql.is_absolute() else script_dir / args.schema_sql
    input_dir = args.input_dir if args.input_dir.is_absolute() else script_dir / args.input_dir
    output_dir = args.output_dir if args.output_dir.is_absolute() else script_dir / args.output_dir

    schema = parse_schema(schema_sql)
    if not schema:
        raise SystemExit(f"No CREATE TABLE statements found in {schema_sql}")

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        raise SystemExit(f"No CSV files found in {input_dir}")

    written = 0
    warnings: list[str] = []
    for csv_path in csv_files:
        table = csv_path.stem
        columns = schema.get(table)
        if not columns:
            warnings.append(f"No SQL table definition for CSV: {csv_path.name}")
            continue

        row_width = first_csv_row_width(csv_path)
        if row_width is not None and row_width != len(columns):
            warnings.append(
                f"Column count mismatch for {csv_path.name}: SQL has {len(columns)}, first CSV row has {row_width}"
            )

        write_with_header(csv_path, output_dir / csv_path.name, columns)
        written += 1

    csv_tables = {p.stem for p in csv_files}
    for table in sorted(set(schema) - csv_tables):
        warnings.append(f"SQL table has no CSV file: {table}")

    print(f"SQL tables : {len(schema)}")
    print(f"CSV files  : {len(csv_files)}")
    print(f"Written    : {written}")
    print(f"Output dir : {output_dir}")
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
