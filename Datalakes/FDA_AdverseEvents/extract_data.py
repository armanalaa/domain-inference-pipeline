"""
extract_data.py  —  FDA Adverse Drug Events (openFDA)
======================================================
Downloads the COMPLETE FDA adverse drug event dataset via openFDA
bulk downloads and normalises it into 12 relational CSV tables.

Two modes:
  --bulk   Download entire dataset via bulk JSON ZIP files (recommended)
           Full dataset: ~20M reports, ~80 quarterly files, ~30 GB unzipped
  --limit  Download N reports via paginated API (quick testing)

Source: FDA Adverse Event Reporting System (FAERS) via openFDA
        https://open.fda.gov/apis/drug/event/
        Data from 2004 to present, updated quarterly.

Schema (12 tables):
  reports          — Main adverse event reports
  patients         — Patient demographics per report
  seriousness      — Seriousness flags per report
  primary_sources  — Who submitted each report
  senders          — Sending organisation per report
  receivers        — Receiving organisation per report
  drugs            — Drugs involved per report
  drug_openfda     — OpenFDA enrichment per drug entry
  drug_brand_names — Brand names per drug entry (multi-valued)
  drug_substances  — Active substances per drug entry (multi-valued)
  reactions        — Patient reactions per report
  report_duplicates— Duplicate report tracking

Usage:
    cd FDA_AdverseEvents

    # Full dataset (bulk download — may take hours)
    python extract_data.py --bulk

    # Single quarter only (e.g. 2024Q1 — for testing)
    python extract_data.py --bulk --quarter 2024Q1

    # Quick test via API (10,000 reports)
    python extract_data.py --limit 10000

    # With API key (higher rate limits for --limit mode)
    python extract_data.py --limit 50000 --api_key YOUR_KEY

Requirements:
    pip install requests
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import time
import zipfile
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL     = "https://api.fda.gov/drug/event.json"
MANIFEST_URL = "https://api.fda.gov/download.json"
PAGE_SIZE    = 1000
RATE_DELAY   = 0.25   # between API pages (240 req/min without key)


# =============================================================================
# Table schemas
# =============================================================================

SCHEMAS = {
    "reports": [
        "safetyreportid", "safetyreportversion", "receivedate",
        "receivedateformat", "transmissiondate", "transmissiondateformat",
        "receiptdate", "receiptdateformat", "reporttype",
        "serious", "primarysourcecountry", "occurcountry",
        "companynumb", "duplicate", "fulfillexpeditecriteria",
    ],
    "patients": [
        "safetyreportid", "patientonsetage", "patientonsetageunit",
        "patientagegroup", "patientweight", "patientsex",
        "patientdeath_date",
    ],
    "seriousness": [
        "safetyreportid", "seriousnessdeath", "seriousnesslifethreatening",
        "seriousnesshospitalization", "seriousnessdisabling",
        "seriousnesscongenitalanomali", "seriousnessother",
    ],
    "primary_sources": [
        "safetyreportid", "primarysource_qualification",
        "primarysource_reportercountry",
    ],
    "senders": [
        "safetyreportid", "sender_sendertype", "sender_senderorganization",
    ],
    "receivers": [
        "safetyreportid", "receiver_receivertype",
        "receiver_receiverorganization",
    ],
    "drugs": [
        "drug_id", "safetyreportid", "drugcharacterization",
        "medicinalproduct", "drugbatchnumb", "drugauthorizationnumb",
        "drugdosagetext", "drugdosageform", "drugstartdate", "drugenddate",
        "drugindication", "actiondrug", "drugadditional",
        "drugadministrationroute",
    ],
    "drug_openfda": [
        "drug_id", "safetyreportid",
        "application_number", "generic_name", "pharm_class_cs",
        "pharm_class_epc", "product_type", "route",
    ],
    "drug_brand_names": [
        "drug_id", "safetyreportid", "brand_name",
    ],
    "drug_substances": [
        "drug_id", "safetyreportid", "substance_name",
    ],
    "reactions": [
        "reaction_id", "safetyreportid", "reactionmeddrapt",
        "reactionmeddraversionpt", "reactionoutcome",
    ],
    "report_duplicates": [
        "safetyreportid", "duplicate_safetyreportid", "duplicate_source",
    ],
}


# =============================================================================
# Normalise one report
# =============================================================================

def normalise(report: dict, drug_counter: list, rxn_counter: list) -> dict[str, list]:
    rid  = report.get("safetyreportid", "")
    pat  = report.get("patient", {}) or {}
    src  = report.get("primarysource", {}) or {}
    sndr = report.get("sender", {}) or {}
    rcvr = report.get("receiver", {}) or {}
    dup  = report.get("reportduplicate", {}) or {}

    rows: dict[str, list] = {k: [] for k in SCHEMAS}

    rows["reports"].append({
        "safetyreportid":         rid,
        "safetyreportversion":    report.get("safetyreportversion", ""),
        "receivedate":            report.get("receivedate", ""),
        "receivedateformat":      report.get("receivedateformat", ""),
        "transmissiondate":       report.get("transmissiondate", ""),
        "transmissiondateformat": report.get("transmissiondateformat", ""),
        "receiptdate":            report.get("receiptdate", ""),
        "receiptdateformat":      report.get("receiptdateformat", ""),
        "reporttype":             report.get("reporttype", ""),
        "serious":                report.get("serious", ""),
        "primarysourcecountry":   report.get("primarysourcecountry", ""),
        "occurcountry":           report.get("occurcountry", ""),
        "companynumb":            report.get("companynumb", ""),
        "duplicate":              report.get("duplicate", ""),
        "fulfillexpeditecriteria":report.get("fulfillexpeditecriteria", ""),
    })

    death = pat.get("patientdeath", {}) or {}
    rows["patients"].append({
        "safetyreportid":     rid,
        "patientonsetage":    pat.get("patientonsetage", ""),
        "patientonsetageunit":pat.get("patientonsetageunit", ""),
        "patientagegroup":    pat.get("patientagegroup", ""),
        "patientweight":      pat.get("patientweight", ""),
        "patientsex":         pat.get("patientsex", ""),
        "patientdeath_date":  death.get("patientdeathdate", ""),
    })

    rows["seriousness"].append({
        "safetyreportid":               rid,
        "seriousnessdeath":             report.get("seriousnessdeath", ""),
        "seriousnesslifethreatening":   report.get("seriousnesslifethreatening", ""),
        "seriousnesshospitalization":   report.get("seriousnesshospitalization", ""),
        "seriousnessdisabling":         report.get("seriousnessdisabling", ""),
        "seriousnesscongenitalanomali": report.get("seriousnesscongenitalanomali", ""),
        "seriousnessother":             report.get("seriousnessother", ""),
    })

    rows["primary_sources"].append({
        "safetyreportid":                rid,
        "primarysource_qualification":   src.get("qualification", ""),
        "primarysource_reportercountry": src.get("reportercountry", ""),
    })

    rows["senders"].append({
        "safetyreportid":           rid,
        "sender_sendertype":        sndr.get("sendertype", ""),
        "sender_senderorganization":sndr.get("senderorganization", ""),
    })

    rows["receivers"].append({
        "safetyreportid":                rid,
        "receiver_receivertype":         rcvr.get("receivertype", ""),
        "receiver_receiverorganization": rcvr.get("receiverorganization", ""),
    })

    for drug in (pat.get("drug") or []):
        drug_counter[0] += 1
        did     = drug_counter[0]
        openfda = drug.get("openfda", {}) or {}

        rows["drugs"].append({
            "drug_id":               did,
            "safetyreportid":        rid,
            "drugcharacterization":  drug.get("drugcharacterization", ""),
            "medicinalproduct":      drug.get("medicinalproduct", ""),
            "drugbatchnumb":         drug.get("drugbatchnumb", ""),
            "drugauthorizationnumb": drug.get("drugauthorizationnumb", ""),
            "drugdosagetext":        drug.get("drugdosagetext", ""),
            "drugdosageform":        drug.get("drugdosageform", ""),
            "drugstartdate":         drug.get("drugstartdate", ""),
            "drugenddate":           drug.get("drugenddate", ""),
            "drugindication":        drug.get("drugindication", ""),
            "actiondrug":            drug.get("actiondrug", ""),
            "drugadditional":        drug.get("drugadditional", ""),
            "drugadministrationroute":drug.get("drugadministrationroute", ""),
        })

        rows["drug_openfda"].append({
            "drug_id":          did,
            "safetyreportid":   rid,
            "application_number":(openfda.get("application_number") or [""])[0],
            "generic_name":     (openfda.get("generic_name") or [""])[0],
            "pharm_class_cs":   (openfda.get("pharm_class_cs") or [""])[0],
            "pharm_class_epc":  (openfda.get("pharm_class_epc") or [""])[0],
            "product_type":     (openfda.get("product_type") or [""])[0],
            "route":            (openfda.get("route") or [""])[0],
        })

        for bn in (openfda.get("brand_name") or []):
            rows["drug_brand_names"].append({
                "drug_id": did, "safetyreportid": rid, "brand_name": bn,
            })

        for sn in (openfda.get("substance_name") or []):
            rows["drug_substances"].append({
                "drug_id": did, "safetyreportid": rid, "substance_name": sn,
            })

    for rxn in (pat.get("reaction") or []):
        rxn_counter[0] += 1
        rows["reactions"].append({
            "reaction_id":            rxn_counter[0],
            "safetyreportid":         rid,
            "reactionmeddrapt":       rxn.get("reactionmeddrapt", ""),
            "reactionmeddraversionpt":rxn.get("reactionmeddraversionpt", ""),
            "reactionoutcome":        rxn.get("reactionoutcome", ""),
        })

    if dup:
        for entry in (dup if isinstance(dup, list) else [dup]):
            rows["report_duplicates"].append({
                "safetyreportid":           rid,
                "duplicate_safetyreportid": entry.get("duplicatesafetyreportid", ""),
                "duplicate_source":         entry.get("duplicatesource", ""),
            })

    return rows


# =============================================================================
# CSV writers (append mode for bulk streaming)
# =============================================================================

def open_writers(csv_dir: Path, append: bool = False) -> tuple[dict, dict]:
    csv_dir.mkdir(parents=True, exist_ok=True)
    mode    = "a" if append else "w"
    files   = {}
    writers = {}
    for table, columns in SCHEMAS.items():
        f = open(csv_dir / f"{table}.csv", mode, newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=columns,
                           extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        if not append:
            w.writeheader()
        files[table]   = f
        writers[table] = w
    return files, writers


def close_writers(files: dict) -> None:
    for f in files.values():
        f.close()


def flush_rows(all_rows: dict, writers: dict) -> int:
    total = 0
    for table, rows in all_rows.items():
        if rows:
            writers[table].writerows(rows)
            total += len(rows)
    return total


# =============================================================================
# Bulk download mode
# =============================================================================

def get_bulk_file_urls(quarter_filter: str | None) -> list[str]:
    """Fetch openFDA download manifest and return drug/event file URLs."""
    log.info("Fetching download manifest from %s ...", MANIFEST_URL)
    resp = requests.get(MANIFEST_URL, timeout=30)
    resp.raise_for_status()
    manifest = resp.json()

    files = (manifest
             .get("results", {})
             .get("drug", {})
             .get("event", {})
             .get("partitions", []))

    if not files:
        raise RuntimeError(
            "No drug/event partitions found in manifest. "
            "Check https://api.fda.gov/download.json manually."
        )

    urls = [f["file"] for f in files if "file" in f]

    if quarter_filter:
        urls = [u for u in urls if quarter_filter in u]
        if not urls:
            raise ValueError(
                f"No files found for quarter: {quarter_filter}\n"
                f"Available quarters are in the URL patterns like 2024Q1"
            )

    log.info("Found %d bulk file(s) to download", len(urls))
    return urls


def process_bulk_file(
    url: str,
    writers: dict,
    drug_counter: list,
    rxn_counter: list,
) -> int:
    """Download one bulk ZIP, parse JSON, normalise, write rows. Returns record count."""
    log.info("  Downloading: %s", url.split("/")[-1])
    t0 = time.time()

    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    raw = io.BytesIO(resp.content)
    total_records = 0

    with zipfile.ZipFile(raw) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            with zf.open(name) as jf:
                data    = json.load(jf)
                records = data.get("results", [])
                all_rows = {k: [] for k in SCHEMAS}

                for report in records:
                    row_sets = normalise(report, drug_counter, rxn_counter)
                    for table, rows in row_sets.items():
                        all_rows[table].extend(rows)

                flush_rows(all_rows, writers)
                total_records += len(records)

    elapsed = round(time.time() - t0, 1)
    log.info("    → %d records  %.1fs", total_records, elapsed)
    return total_records


def run_bulk(csv_dir: Path, quarter_filter: str | None) -> None:
    urls         = get_bulk_file_urls(quarter_filter)
    drug_counter = [0]
    rxn_counter  = [0]
    total        = 0

    files, writers = open_writers(csv_dir, append=False)

    try:
        for i, url in enumerate(urls, 1):
            log.info("[%d/%d] %s", i, len(urls), url.split("/")[-1])
            count = process_bulk_file(url, writers, drug_counter, rxn_counter)
            total += count
            log.info("  Running total: %d reports", total)
    finally:
        close_writers(files)

    log.info("=" * 60)
    log.info("Bulk download complete — %d total reports", total)
    _print_csv_sizes(csv_dir)


# =============================================================================
# API pagination mode
# =============================================================================

def run_api(csv_dir: Path, limit: int, api_key: str | None) -> None:
    params       = {"limit": PAGE_SIZE}
    drug_counter = [0]
    rxn_counter  = [0]
    total        = 0
    pages        = (limit + PAGE_SIZE - 1) // PAGE_SIZE

    if api_key:
        params["api_key"] = api_key

    files, writers = open_writers(csv_dir, append=False)

    try:
        for page in range(pages):
            skip  = page * PAGE_SIZE
            fetch = min(PAGE_SIZE, limit - skip)
            params.update({"limit": fetch, "skip": skip})

            try:
                r = requests.get(BASE_URL, params=params, timeout=30)
                r.raise_for_status()
                records  = r.json().get("results", [])
                all_rows = {k: [] for k in SCHEMAS}

                for report in records:
                    row_sets = normalise(report, drug_counter, rxn_counter)
                    for table, rows in row_sets.items():
                        all_rows[table].extend(rows)

                flush_rows(all_rows, writers)
                total += len(records)
                log.info("  Page %d/%d  +%d records (total %d)",
                         page + 1, pages, len(records), total)

                if not records:
                    break

            except requests.HTTPError as e:
                if r.status_code == 404:
                    log.warning("No more results at skip=%d", skip)
                    break
                raise

            if page < pages - 1:
                time.sleep(RATE_DELAY)
    finally:
        close_writers(files)

    log.info("=" * 60)
    log.info("API download complete — %d total reports", total)
    _print_csv_sizes(csv_dir)


def _print_csv_sizes(csv_dir: Path) -> None:
    log.info("\nCSV files:")
    for table in SCHEMAS:
        p = csv_dir / f"{table}.csv"
        if p.exists():
            mb = p.stat().st_size / (1024 * 1024)
            log.info("  %-22s  %7.1f MB", table, mb)
    log.info("\nNext step:")
    log.info("  python ../extract_schema.py --csv_dir csv "
             "--output schema.json --database FDA_AdverseEvents")


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download openFDA adverse drug events and export to 12 CSV tables."
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--bulk", action="store_true",
        help="Download entire dataset via bulk ZIP files (recommended for full data)"
    )
    mode.add_argument(
        "--limit", type=int, default=10_000,
        help="Download N reports via paginated API (default: 10000)"
    )

    parser.add_argument(
        "--quarter", default=None,
        help="Bulk mode only: download a single quarter e.g. --quarter 2024Q1"
    )
    parser.add_argument(
        "--api_key", default=None,
        help="openFDA API key (free at https://open.fda.gov/apis/authentication/)"
    )
    parser.add_argument(
        "--csv_dir", default="csv",
        help="Output directory (default: csv/)"
    )
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)

    log.info("=" * 60)
    log.info("openFDA Adverse Drug Events Extractor")
    if args.bulk:
        log.info("  Mode      : BULK DOWNLOAD (full dataset)")
        log.info("  Quarter   : %s", args.quarter or "ALL")
        log.info("  Warning   : Full dataset is ~20M reports (~30 GB)")
        log.info("              Use --quarter 2024Q1 for a single quarter")
    else:
        log.info("  Mode      : API pagination")
        log.info("  Reports   : %d", args.limit)
        log.info("  API key   : %s", "yes" if args.api_key else "no (rate-limited)")
    log.info("  CSV dir   : %s", csv_dir)
    log.info("=" * 60)

    if args.bulk:
        run_bulk(csv_dir, args.quarter)
    else:
        run_api(csv_dir, args.limit, args.api_key)


if __name__ == "__main__":
    main()