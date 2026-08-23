#!/usr/bin/env python3
"""Validate processed JSON -> offline UI embedding for every record.

Official XLSX reconciliation is handled separately by validate_sources.py and
validate_ordinary_grant.py. This validator checks that the fully augmented
processed dataset is embedded into index.html without changing source values,
derived values, ordinary-grant metadata, history positions, or year metadata.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SOURCE_MANIFEST = ROOT / "data" / "source_manifest.json"
GRANT_MANIFEST = ROOT / "data" / "ordinary_grant_manifest.json"
PROCESSED = ROOT / "data" / "processed" / "furusato_data.json"
TOLERANCE = 1e-5
SPECIAL_WARDS = {f"131{i:02d}" for i in range(1, 24)}

EXPECTED_FIELDS = [
    "received", "expense", "proxy", "taxDeduction",
    "prefecturalTaxDeduction", "residentTaxDeductionTotal",
    "referenceBalance", "receiptSourceRow", "taxSourceRow",
    "receiptRawSourceCode6", "taxRawSourceCode6",
    "ordinaryGrantFiscalYear", "ordinaryGrantAmount", "ordinaryGrantStatus",
    "ordinaryGrantSourceStage", "ordinaryGrantSourceStageLabel",
    "ordinaryGrantSourceRow", "ordinaryGrantSourceUrl",
    "ordinaryGrantSourceSha256", "ordinaryGrantEstimate",
    "balanceWithOrdinaryGrantEstimate",
]

HISTORY_POSITIONS = {
    "received": 1,
    "expense": 2,
    "proxy": 3,
    "municipal_tax_deduction": 4,
    "prefectural_tax_deduction": 5,
    "resident_tax_deduction_total": 6,
    "balance_before_tax_adjustment": 7,
    "receipt_source_row": 8,
    "tax_source_row": 9,
    "receipt_raw_code6": 10,
    "tax_raw_code6": 11,
    "ordinary_grant_amount": 12,
    "ordinary_grant_estimate": 13,
    "balance_with_ordinary_grant_estimate": 14,
    "ordinary_grant_status": 15,
    "ordinary_grant_source_stage": 16,
    "ordinary_grant_source_stage_label": 17,
    "ordinary_grant_source_row": 18,
    "balance_with_75pct_reference": 19,
}


def fail(message: str) -> "NoReturn":
    raise AssertionError(message)


def extract_json(text: str, variable: str):
    match = re.search(rf"const {re.escape(variable)} = (.*?);\n", text, flags=re.S)
    if not match:
        fail(f"{variable} was not found")
    return json.loads(match.group(1))


def equal(a, b) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=TOLERANCE)
    return a == b


def compare(errors: list[dict], year: int, code: str, field: str, expected, actual) -> None:
    if not equal(expected, actual):
        errors.append({"year": year, "municipality_code": code, "field": field, "expected": expected, "actual": actual})


def validate_record_formula(record: dict, year: int) -> None:
    code = record["municipality_code"]
    before = record["received"] - record["expense"] - record["proxy"] - record["municipal_tax_deduction"]
    reference75 = record["municipal_tax_deduction"] * 0.75
    if not equal(record["resident_tax_deduction_total"], record["municipal_tax_deduction"] + record["prefectural_tax_deduction"]):
        fail(f"{year} {code}: resident tax total formula")
    if not equal(record["balance_before_tax_adjustment"], before):
        fail(f"{year} {code}: before-grant formula")
    if not equal(record["tax_deduction_75pct_reference"], reference75):
        fail(f"{year} {code}: 75-percent reference formula")
    if not equal(record["balance_with_75pct_reference"], before + reference75):
        fail(f"{year} {code}: legacy 75-percent balance formula")
    if record["ordinary_grant_fiscal_year"] != record["tax_assessment_fiscal_year"]:
        fail(f"{year} {code}: ordinary-grant fiscal-year alignment")
    if code in SPECIAL_WARDS:
        if record["ordinary_grant_status"] != "special_ward_na":
            fail(f"{year} {code}: special ward status")
        for field in ("ordinary_grant_amount", "ordinary_grant_estimate", "balance_with_ordinary_grant_estimate", "ordinary_grant_source_row"):
            if record[field] is not None:
                fail(f"{year} {code}: special ward must have null {field}")
    else:
        amount = record["ordinary_grant_amount"]
        expected_estimate = min(reference75, amount)
        if record["ordinary_grant_status"] != ("recipient" if amount > 0 else "non_recipient"):
            fail(f"{year} {code}: ordinary-grant status")
        if not equal(record["ordinary_grant_estimate"], expected_estimate):
            fail(f"{year} {code}: ordinary-grant estimate formula")
        if not equal(record["balance_with_ordinary_grant_estimate"], before + expected_estimate):
            fail(f"{year} {code}: grant-adjusted balance formula")


def main() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    grant_manifest = json.loads(GRANT_MANIFEST.read_text(encoding="utf-8"))
    processed = json.loads(PROCESSED.read_text(encoding="utf-8"))
    index_text = INDEX.read_text(encoding="utf-8")
    data = extract_json(index_text, "DATA")
    meta = extract_json(index_text, "FIVE_YEAR_META")
    history = extract_json(index_text, "FIVE_YEAR_HISTORY")
    fields = extract_json(index_text, "FIVE_YEAR_FIELDS")

    if processed.get("schema_version") != 3:
        fail(f"processed schema_version must be 3, got {processed.get('schema_version')}")
    if fields != EXPECTED_FIELDS:
        fail(f"unexpected FIVE_YEAR_FIELDS: {fields}")

    start, end = int(manifest["period"]["start"]), int(manifest["period"]["end"])
    years = [str(y) for y in range(start, end + 1)]
    count = int(manifest["period"]["municipality_count"])
    if list(processed["years"]) != years or list(meta) != years or list(history) != years:
        fail("year keys differ between manifest, processed data and UI embedding")

    processed_by_year: dict[str, dict[str, dict]] = {}
    canonical_names: dict[str, tuple[str, str]] = {}
    for ys in years:
        year = int(ys)
        bucket = processed["years"][ys]
        if bucket["source"] != manifest["sources"][ys]:
            fail(f"{year}: processed source metadata differs from manifest")
        records = bucket["records"]
        if len(records) != count:
            fail(f"{year}: processed count {len(records)} != {count}")
        by_code = {r["municipality_code"]: r for r in records}
        if len(by_code) != count:
            fail(f"{year}: duplicate municipality code")
        for code, record in by_code.items():
            if not re.fullmatch(r"\d{5}", code):
                fail(f"{year}: invalid municipality code {code}")
            validate_record_formula(record, year)
            name = (record["prefecture"], record["municipality"])
            if code in canonical_names and canonical_names[code] != name:
                fail(f"{year} {code}: canonical name changed between years")
            canonical_names[code] = name
            grant_source = grant_manifest["sources"][str(record["ordinary_grant_fiscal_year"])]
            if record["ordinary_grant_source_url"] != grant_source["url"] or record["ordinary_grant_source_sha256"] != grant_source["sha256"]:
                fail(f"{year} {code}: ordinary-grant provenance mismatch")
        processed_by_year[ys] = by_code

    code_sets = [set(rows) for rows in processed_by_year.values()]
    if any(s != code_sets[0] for s in code_sets[1:]):
        fail("municipality code set differs between years")

    errors: list[dict] = []
    latest_by_code = {d["code5"]: d for d in data}
    if len(data) != count or len(latest_by_code) != count:
        fail("latest DATA count/uniqueness mismatch")
    latest_map = {
        "municipality_code6": "code6", "prefecture": "pref", "municipality": "name",
        "received": "received", "expense": "expense", "proxy": "proxy",
        "municipal_tax_deduction": "taxDeduction", "prefectural_tax_deduction": "prefecturalTaxDeduction",
        "resident_tax_deduction_total": "residentTaxDeductionTotal",
        "balance_before_tax_adjustment": "beforeGrant", "tax_deduction_75pct_reference": "grant75",
        "balance_with_75pct_reference": "afterGrantStatutory", "receipt_source_row": "receiptSourceRow",
        "tax_source_row": "taxSourceRow", "tax_source_code6": "taxSourceCode6",
        "receipt_raw_code6": "receiptRawSourceCode6", "tax_raw_code6": "taxRawSourceCode6",
        "receipt_fiscal_year": "receiptFiscalYear", "tax_donation_calendar_year": "taxDonationCalendarYear",
        "tax_assessment_fiscal_year": "taxAssessmentFiscalYear", "ordinary_grant_fiscal_year": "ordinaryGrantFiscalYear",
        "ordinary_grant_amount": "ordinaryGrantAmount", "ordinary_grant_status": "ordinaryGrantStatus",
        "ordinary_grant_source_stage": "ordinaryGrantSourceStage", "ordinary_grant_source_stage_label": "ordinaryGrantSourceStageLabel",
        "ordinary_grant_source_row": "ordinaryGrantSourceRow", "ordinary_grant_source_url": "ordinaryGrantSourceUrl",
        "ordinary_grant_source_sha256": "ordinaryGrantSourceSha256", "ordinary_grant_estimate": "ordinaryGrantEstimate",
        "balance_with_ordinary_grant_estimate": "balanceWithOrdinaryGrantEstimate",
    }
    for code, record in processed_by_year[str(end)].items():
        embedded = latest_by_code.get(code)
        if embedded is None:
            errors.append({"year": end, "municipality_code": code, "field": "latest row", "expected": "present", "actual": "missing"})
            continue
        for source_field, ui_field in latest_map.items():
            compare(errors, end, code, f"DATA.{source_field}", record[source_field], embedded.get(ui_field))

    for ys in years:
        year = int(ys)
        rows = history[ys]
        if len(rows) != count:
            fail(f"{year}: history count {len(rows)} != {count}")
        history_by_code = {row[0]: row for row in rows}
        if len(history_by_code) != count:
            fail(f"{year}: duplicate history code")
        for code, record in processed_by_year[ys].items():
            row = history_by_code.get(code)
            if row is None:
                errors.append({"year": year, "municipality_code": code, "field": "history row", "expected": "present", "actual": "missing"})
                continue
            if len(row) < 20:
                errors.append({"year": year, "municipality_code": code, "field": "history row length", "expected": 20, "actual": len(row)})
                continue
            for field, position in HISTORY_POSITIONS.items():
                compare(errors, year, code, f"HISTORY.{field}", record[field], row[position])
        source = manifest["sources"][ys]
        grant_source = grant_manifest["sources"][str(source["tax_assessment_fiscal_year"])]
        expected_meta = {
            "receiptFiscalYear": year,
            "taxDonationCalendarYear": int(source["tax_donation_calendar_year"]),
            "taxAssessmentFiscalYear": int(source["tax_assessment_fiscal_year"]),
            "receiptSha256": source["receipts_sha256"],
            "taxSha256": source["tax_sha256"],
            "municipalityCount": count,
            "ordinaryGrantFiscalYear": int(grant_source["fiscal_year"]),
            "ordinaryGrantDecisionStage": grant_source["stage"],
            "ordinaryGrantDecisionStageLabel": grant_source["stage_label"],
            "ordinaryGrantFile": grant_source["file"],
            "ordinaryGrantUrl": grant_source["url"],
            "ordinaryGrantSha256": grant_source["sha256"],
            "ordinaryGrantSheet": grant_source["sheet"],
        }
        for key, expected in expected_meta.items():
            if meta[ys].get(key) != expected:
                errors.append({"year": year, "municipality_code": "*", "field": f"META.{key}", "expected": expected, "actual": meta[ys].get(key)})

    if errors:
        print(json.dumps(errors[:100], ensure_ascii=False, indent=2))
        fail(f"processed-to-UI reconciliation failed: {len(errors)} mismatches")
    embedded_json = json.dumps([data, meta, history], ensure_ascii=False)
    if re.search(r"\b(?:NaN|Infinity|-Infinity)\b", embedded_json):
        fail("embedded data contains NaN/Infinity")
    for hook in ('id="fiscalYear"', 'id="panel-history"', 'id="historyMunicipality"', 'id="historyReceivedChart"', 'id="historyBalanceChart"', 'id="map"'):
        if hook not in index_text:
            fail(f"missing required UI hook {hook}")

    history_comparisons = count * len(years) * len(HISTORY_POSITIONS)
    print("VALIDATION OK")
    print("years:", ", ".join(years))
    print("municipalities per year:", count)
    print("processed records:", count * len(years))
    print("history field comparisons:", history_comparisons)
    print("latest DATA comparisons:", count * len(latest_map))
    print("processed-to-UI mismatches: 0")


if __name__ == "__main__":
    main()
