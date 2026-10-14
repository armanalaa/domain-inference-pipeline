"""
mondial_to_csv.py
-----------------
Downloads the Mondial database SQL files directly from GitHub,
loads them into a local SQLite database, and exports each table to CSV.

No MySQL/PostgreSQL installation required — uses SQLite only.

Usage:
    pip install requests
    python mondial_to_csv.py --out_dir Mondial/csv
"""

import argparse
import csv
import os
import re
import sqlite3
import urllib.request

# Raw GitHub URLs for the MySQL/MariaDB version
SCHEMA_URL = "https://raw.githubusercontent.com/ullenboom/mondial-database/main/mondial-schema-mysql.sql"
DATA_URL   = "https://raw.githubusercontent.com/ullenboom/mondial-database/main/mondial-inputs-mysql.sql"


def download(url: str, label: str) -> str:
    print(f"Downloading {label} ...")
    with urllib.request.urlopen(url) as r:
        content = r.read().decode("utf-8", errors="replace")
    print(f"  ✓ {len(content):,} chars")
    return content


def mysql_to_sqlite(sql: str) -> str:
    """Best-effort conversion of MySQL DDL/DML to SQLite-compatible SQL."""
    # Remove ENGINE=, CHARSET=, AUTO_INCREMENT= clauses
    sql = re.sub(r"\s+ENGINE\s*=\s*\w+", "", sql)
    sql = re.sub(r"\s+DEFAULT\s+CHARSET\s*=\s*\w+", "", sql)
    sql = re.sub(r"\s+AUTO_INCREMENT\s*=\s*\d+", "", sql)
    sql = re.sub(r"\s+COLLATE\s*=?\s*\w+", "", sql)
    # Remove KEY / INDEX lines inside CREATE TABLE
    sql = re.sub(r",\s*(KEY|INDEX|UNIQUE KEY)\s+`?\w+`?\s*\([^)]*\)", "", sql)
    # Remove CONSTRAINT lines that reference other tables (FK) — SQLite ignores them anyway
    sql = re.sub(r",\s*CONSTRAINT\s+`?\w+`?\s+FOREIGN KEY[^,)]+", "", sql)
    # Convert backtick identifiers (MySQL) — SQLite supports them but let's keep for safety
    # Convert MySQL data types to SQLite equivalents
    sql = re.sub(r"\bDOUBLE(\s+PRECISION)?\b", "REAL", sql)
    sql = re.sub(r"\bFLOAT\b", "REAL", sql)
    sql = re.sub(r"\bMEDIUMINT\b", "INTEGER", sql)
    sql = re.sub(r"\bTINYINT\b", "INTEGER", sql)
    sql = re.sub(r"\bSMALLINT\b", "INTEGER", sql)
    sql = re.sub(r"\bBIGINT\b", "INTEGER", sql)
    sql = re.sub(r"\bDECIMAL\s*\([^)]*\)", "REAL", sql)
    sql = re.sub(r"\bNUMERIC\s*\([^)]*\)", "REAL", sql)
    sql = re.sub(r"\bVARCHAR\s*\(\d+\)", "TEXT", sql)
    sql = re.sub(r"\bCHAR\s*\(\d+\)", "TEXT", sql)
    sql = re.sub(r"\bTEXT\b", "TEXT", sql)
    # Remove MySQL-specific SET statements
    sql = re.sub(r"^SET\s+\w+\s*=.*;$", "", sql, flags=re.MULTILINE)
    # Remove LOCK/UNLOCK TABLE statements
    sql = re.sub(r"^(LOCK|UNLOCK)\s+TABLES.*;$", "", sql, flags=re.MULTILINE)
    # Remove USE database statement
    sql = re.sub(r"^USE\s+`?\w+`?\s*;$", "", sql, flags=re.MULTILINE)
    # Remove DROP TABLE IF EXISTS (we recreate anyway)
    # Keep CREATE TABLE IF NOT EXISTS → SQLite supports this
    return sql


def load_sql(conn: sqlite3.Connection, sql: str, label: str):
    """Execute SQL statements one by one, skipping errors gracefully."""
    # Split on semicolons (simple split — good enough for Mondial's clean SQL)
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    ok, skipped = 0, 0
    for stmt in statements:
        try:
            conn.execute(stmt)
            ok += 1
        except sqlite3.Error as e:
            skipped += 1
            # Uncomment to debug skipped statements:
            # print(f"  SKIP: {e} — {stmt[:80]}")
    conn.commit()
    print(f"  {label}: {ok} statements executed, {skipped} skipped")


def export_tables(conn: sqlite3.Connection, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    print(f"\nExporting {len(tables)} tables to {os.path.abspath(out_dir)}\n")
    for table in tables:
        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
        cols = [d[0] for d in conn.execute(f'SELECT * FROM "{table}" LIMIT 0').description or []]
        if cols is None:
            cols = []
        out_path = os.path.join(out_dir, f"{table}.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)
        print(f"  ✓ {table:<30} {len(rows):>6} rows")
    print(f"\nDone. {len(tables)} CSV files written.")


def main():
    parser = argparse.ArgumentParser(description="Download Mondial DB and export to CSV")
    parser.add_argument("--out_dir", default="Mondial/csv", help="Output directory for CSV files")
    parser.add_argument("--db_file", default=":memory:", help="SQLite DB file (default: in-memory)")
    args = parser.parse_args()

    schema_sql = download(SCHEMA_URL, "schema")
    data_sql   = download(DATA_URL,   "data")

    print("\nConverting MySQL SQL to SQLite ...")
    schema_sqlite = mysql_to_sqlite(schema_sql)
    data_sqlite   = mysql_to_sqlite(data_sql)

    print("Loading into SQLite ...")
    conn = sqlite3.connect(args.db_file)
    conn.execute("PRAGMA foreign_keys = OFF")
    load_sql(conn, schema_sqlite, "schema")
    load_sql(conn, data_sqlite,   "data")

    export_tables(conn, args.out_dir)
    conn.close()


if __name__ == "__main__":
    main()