#!/usr/bin/env python3
"""Validate the offline bundle against the normalized generated dataset.

This is the fast, network-free check used by ordinary CI.  The authoritative
XLSX reconciliation is implemented in validate_sources.py; this script makes
sure that its normalized output was embedded into index.html without a row,
period, code, source-row, or formula change.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
MANIFEST = ROOT / "data" / "source_manifest.json"
PROCESSED = ROOT / "data" / "processed" / "furusato_data.json"
TOLERANCE = 1e-5
MAX_AMOUNT = 10**14


def extract_json(text: str, variable: str):
    match = re.search(rf"const {re.escape(variable)} = (.*?);\n", text, flags=re.S)
    if not match:
        raise AssertionError(f"{variable} was not found")
    return json.loads(match.group(1))


def close(a, b) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=TOLERANCE)


def fail(message: str):
    raise AssertionError(message)


def compare(errors: list[dict], year: int, code: str, name: str, field: str, official, embedded):
    if isinstance(official, (int, float)) and isinstance(embedded, (int, float)):
        ok = close(official, embedded)
    else:
        ok = official == embedded
    if not ok:
        errors.append(
            {
                "year": year,
                "municipality_code": code,
                "municipality_name": name,
                "field": field,
                "official_value": official,
                "embedded_value": embedded,
            }
        )


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    processed = json.loads(PROCESSED.read_text(encoding="utf-8"))
    index_text = INDEX.read_text(encoding="utf-8")
    embedded_data = extract_json(index_text, "DATA")
    embedded_meta = extract_json(index_text, "FIVE_YEAR_META")
    embedded_history = extract_json(index_text, "FIVE_YEAR_HISTORY")
    embedded_fields = extract_json(index_text, "FIVE_YEAR_FIELDS")

    if manifest.get("schema_version") != 2:
        fail("source_manifest schema_version must be 2")
    period = manifest["period"]
    start, end = int(period["start"]), int(period["end"])
    expected_municipalities = int(period["municipality_count"])
    if int(period.get("fiscal_years", end - start + 1)) != end - start + 1:
        fail("period.fiscal_years does not match start/end")
    expected_years = [str(year) for year in range(start, end + 1)]
    if expected_years != list(processed["years"]):
        fail(f"processed years mismatch: {list(processed['years'])}")
    if expected_years != list(embedded_meta):
        fail(f"embedded metadata years mismatch: {list(embedded_meta)}")
    if expected_years != list(embedded_history):
        fail(f"embedded history years mismatch: {list(embedded_history)}")
    if embedded_fields != [
        "received",
        "expense",
        "proxy",
        "taxDeduction",
        "prefecturalTaxDeduction",
        "residentTaxDeductionTotal",
        "referenceBalance",
        "receiptSourceRow",
        "taxSourceRow",
        "receiptRawSourceCode6",
        "taxRawSourceCode6",
    ]:
        fail(f"unexpected FIVE_YEAR_FIELDS: {embedded_fields}")
    for kind, checks in manifest.get("header_validation", {}).items():
        if not isinstance(checks, dict) or not checks:
            fail(f"header_validation.{kind} must contain field checks")
    for year_text in expected_years:
        source = manifest["sources"].get(year_text)
        if not source or not source.get("retrieved_at"):
            fail(f"source {year_text} retrieved_at is missing")
        year = int(year_text)
        if int(source.get("receipt_fiscal_year", -1)) != year:
            fail(f"source {year} receipt_fiscal_year does not match its manifest key")
        if int(source.get("tax_donation_calendar_year", -1)) != year:
            fail(f"source {year} tax_donation_calendar_year does not match its receipt year")
        if int(source.get("tax_assessment_fiscal_year", -1)) != int(source.get("tax_donation_calendar_year", -2)) + 1:
            fail(f"source {year} tax_assessment_fiscal_year must be donation calendar year + 1")
        anchors = source.get("tax_header_anchors", {})
        if not anchors.get("municipal_tax_deduction") or not anchors.get("prefectural_tax_deduction"):
            fail(f"source {year} tax_header_anchors are incomplete")

    processed_years = processed["years"]
    source_fields = [
        "received",
        "expense",
        "proxy",
        "municipal_tax_deduction",
        "prefectural_tax_deduction",
        "resident_tax_deduction_total",
    ]
    derived_fields = [
        "balance_before_tax_adjustment",
        "tax_deduction_75pct_reference",
        "balance_with_75pct_reference",
    ]
    errors: list[dict] = []
    processed_by_year: dict[str, dict[str, dict]] = {}
    canonical_names: dict[str, tuple[str, str]] = {}
    for year_text in expected_years:
        year = int(year_text)
        bucket = processed_years[year_text]
        source = manifest["sources"][year_text]
        if bucket["source"] != source:
            fail(f"processed source manifest differs for {year}")
        records = bucket["records"]
        if len(records) != expected_municipalities:
            fail(f"{year} normalized record count: {len(records)}")
        by_code: dict[str, dict] = {}
        receipt_rows: set[int] = set()
        tax_rows: set[int] = set()
        for record in records:
            code = record["municipality_code"]
            if code in by_code:
                fail(f"{year} duplicate normalized municipality code {code}")
            by_code[code] = record
            if record["receipt_fiscal_year"] != year or record["receipt_fiscal_year_label"] != source["receipt_fiscal_year_label"]:
                fail(f"{year} {code} receipt fiscal-year metadata mismatch")
            if record["tax_donation_calendar_year"] != source["tax_donation_calendar_year"] or record["tax_assessment_fiscal_year"] != source["tax_assessment_fiscal_year"] or record["tax_assessment_fiscal_year_label"] != source["tax_assessment_fiscal_year_label"]:
                fail(f"{year} {code} tax-period metadata mismatch")
            if record["receipt_source_row"] in receipt_rows:
                fail(f"{year} duplicate receipt source row {record['receipt_source_row']}")
            if record["tax_source_row"] in tax_rows:
                fail(f"{year} duplicate tax source row {record['tax_source_row']}")
            receipt_rows.add(record["receipt_source_row"])
            tax_rows.add(record["tax_source_row"])
            if not re.fullmatch(r"\d{5}", code):
                fail(f"{year} invalid municipality code {code}")
            for field in source_fields + derived_fields:
                value = record[field]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                    fail(f"{year} {code} non-finite {field}: {value!r}")
                if field in source_fields and value < 0:
                    fail(f"{year} {code} negative {field}: {value}")
                if abs(float(value)) > MAX_AMOUNT:
                    fail(f"{year} {code} implausibly large {field}: {value}")
            if record["receipt_source_row"] <= 0 or record["tax_source_row"] <= 0:
                fail(f"{year} {code} non-positive source row")
            if not close(record["resident_tax_deduction_total"], record["municipal_tax_deduction"] + record["prefectural_tax_deduction"]):
                fail(f"{year} {code} resident_tax_deduction_total formula")
            if not close(record["balance_before_tax_adjustment"], record["received"] - record["expense"] - record["proxy"] - record["municipal_tax_deduction"]):
                fail(f"{year} {code} balance_before_tax_adjustment formula")
            if not close(record["tax_deduction_75pct_reference"], record["municipal_tax_deduction"] * 0.75):
                fail(f"{year} {code} 75 percent reference formula")
            if not close(record["balance_with_75pct_reference"], record["balance_before_tax_adjustment"] + record["tax_deduction_75pct_reference"]):
                fail(f"{year} {code} balance_with_75pct_reference formula")
            canonical_names.setdefault(code, (record["prefecture"], record["municipality"]))
            if canonical_names[code] != (record["prefecture"], record["municipality"]):
                fail(f"{year} {code} municipality name/prefecture differs between years")
        processed_by_year[year_text] = by_code

    code_sets = [set(rows) for rows in processed_by_year.values()]
    for year_text, codes in zip(expected_years, code_sets):
        if codes != code_sets[0]:
            fail(f"{year_text} municipality code set differs from {expected_years[0]}")

    latest_year = end
    embedded_by_code = {row["code5"]: row for row in embedded_data}
    if len(embedded_data) != expected_municipalities or len(embedded_by_code) != expected_municipalities:
        fail(f"embedded latest DATA count/uniqueness: {len(embedded_data)}/{len(embedded_by_code)}")
    latest_records = processed_by_year[str(latest_year)]
    compare_fields = {
        "municipality_code6": "code6",
        "prefecture": "pref",
        "municipality": "name",
        "received": "received",
        "expense": "expense",
        "proxy": "proxy",
        "municipal_tax_deduction": "taxDeduction",
        "prefectural_tax_deduction": "prefecturalTaxDeduction",
        "resident_tax_deduction_total": "residentTaxDeductionTotal",
        "balance_before_tax_adjustment": "beforeGrant",
        "tax_deduction_75pct_reference": "grant75",
        "balance_with_75pct_reference": "afterGrantStatutory",
        "receipt_source_row": "receiptSourceRow",
        "tax_source_row": "taxSourceRow",
        "tax_source_code6": "taxSourceCode6",
        "receipt_raw_code6": "receiptRawSourceCode6",
        "tax_raw_code6": "taxRawSourceCode6",
    }
    for code, record in latest_records.items():
        embedded = embedded_by_code.get(code)
        if embedded is None:
            errors.append({"year": latest_year, "municipality_code": code, "municipality_name": record["municipality"], "field": "row", "official_value": "present", "embedded_value": "missing"})
            continue
        for official_field, embedded_field in compare_fields.items():
            compare(errors, latest_year, code, record["municipality"], official_field, record[official_field], embedded.get(embedded_field))

    history_positions = {
        "received": 1,
        "expense": 2,
        "proxy": 3,
        "municipal_tax_deduction": 4,
        "prefectural_tax_deduction": 5,
        "resident_tax_deduction_total": 6,
        "balance_with_75pct_reference": 7,
        "receipt_source_row": 8,
        "tax_source_row": 9,
        "receipt_raw_code6": 10,
        "tax_raw_code6": 11,
    }
    for year_text in expected_years:
        rows = embedded_history[year_text]
        if len(rows) != expected_municipalities:
            fail(f"{year_text} embedded history record count: {len(rows)}")
        embedded_history_by_code = {row[0]: row for row in rows}
        if len(embedded_history_by_code) != expected_municipalities:
            fail(f"{year_text} embedded history duplicate code")
        for code, record in processed_by_year[year_text].items():
            row = embedded_history_by_code.get(code)
            if row is None:
                errors.append({"year": int(year_text), "municipality_code": code, "municipality_name": record["municipality"], "field": "row", "official_value": "present", "embedded_value": "missing"})
                continue
            for official_field, position in history_positions.items():
                compare(errors, int(year_text), code, record["municipality"], official_field, record[official_field], row[position])
        meta = embedded_meta[year_text]
        for manifest_key, embedded_key in (
            ("receipt_fiscal_year", "receiptFiscalYear"),
            ("tax_donation_calendar_year", "taxDonationCalendarYear"),
            ("tax_assessment_fiscal_year", "taxAssessmentFiscalYear"),
            ("receipts_sha256", "receiptSha256"),
            ("tax_sha256", "taxSha256"),
            ("municipality_count", "municipalityCount"),
        ):
            expected = manifest["sources"][year_text].get(manifest_key)
            if expected is not None and expected != meta.get(embedded_key):
                fail(f"{year_text} embedded metadata {embedded_key} differs")

    if errors:
        print(json.dumps(errors[:100], ensure_ascii=False, indent=2))
        fail(f"embedded reconciliation failed: {len(errors)} mismatches")
    embedded_json_text = "\n".join(
        json.dumps(value, ensure_ascii=False)
        for value in (embedded_data, embedded_meta, embedded_history)
    )
    if re.search(r"\b(?:NaN|Infinity|-Infinity)\b", embedded_json_text):
        fail("embedded data contains NaN or Infinity")
    for required in [
        'id="fiscalYear"',
        'id="panel-history"',
        'id="historyMunicipality"',
        'id="historyReceivedChart"',
        'id="historyBalanceChart"',
        'id="map"',
    ]:
        if required not in index_text:
            fail(f"missing required UI hook: {required}")

    print("VALIDATION OK")
    print("years:", ", ".join(expected_years))
    print("municipalities per year:", expected_municipalities)
    print("embedded financial records:", expected_municipalities * len(expected_years))
    print("embedded source-field comparisons:", expected_municipalities * len(expected_years) * len(source_fields))
    print("derived/formula checks: PASS")
    print("embedded reconciliation mismatches: 0")


if __name__ == "__main__":
    main()
