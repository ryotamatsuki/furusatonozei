#!/usr/bin/env python3
"""Independently reconcile the embedded bundle with every official workbook.

This validator deliberately does not call ``build_data.join_year``. It reads
the manifest, verifies raw workbook hashes, extracts configured cells with its
own parser, performs the code/name join, and compares those values with both
``data/processed`` and the JavaScript bundle. A shared parser could otherwise
reproduce its own bug while still reporting zero mismatches.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, urlopen

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "source_manifest.json"
PROCESSED_PATH = ROOT / "data" / "processed" / "furusato_data.json"
INDEX_PATH = ROOT / "index.html"
RAW_DIR = ROOT / "data" / "raw"
TOLERANCE = 1e-5
MAX_AMOUNT = 10**14

SOURCE_FIELDS = (
    "receipt_fiscal_year",
    "receipt_fiscal_year_label",
    "tax_donation_calendar_year",
    "tax_assessment_fiscal_year",
    "tax_assessment_fiscal_year_label",
    "municipality_code",
    "municipality_code6",
    "prefecture",
    "municipality",
    "received",
    "expense",
    "proxy",
    "municipal_tax_deduction",
    "prefectural_tax_deduction",
    "resident_tax_deduction_total",
    "receipt_source_row",
    "tax_source_row",
    "tax_source_code6",
    "receipt_raw_code6",
    "tax_raw_code6",
    "tax_source_prefecture",
    "tax_source_municipality",
)
DERIVED_FIELDS = (
    "balance_before_tax_adjustment",
    "tax_deduction_75pct_reference",
    "balance_with_75pct_reference",
)


def fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def normalize_text(value) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_code(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        digits = str(int(value)) if float(value).is_integer() else str(value).split(".", 1)[0]
    else:
        digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    digits = digits.zfill(6)
    return digits if len(digits) == 6 else None


def amount(value, *, field: str, row: int, allow_blank: bool = False) -> int | float:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return 0
        fail(f"{field}: blank amount at source row {row}")
    if isinstance(value, bool):
        fail(f"{field}: boolean amount at source row {row}")
    try:
        dec = Decimal(str(value).replace(",", "").replace("円", "").strip())
    except (InvalidOperation, ValueError) as exc:
        fail(f"{field}: non-numeric amount {value!r} at source row {row}: {exc}")
    if not dec.is_finite() or dec < 0 or dec > MAX_AMOUNT:
        fail(f"{field}: invalid amount {value!r} at source row {row}")
    return int(dec) if dec == dec.to_integral_value() else float(dec)


def column_number(value: str) -> int:
    result = 0
    for char in value.upper():
        if not "A" <= char <= "Z":
            fail(f"invalid Excel column: {value}")
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def check_tax_header_layout(sheet, source: dict) -> None:
    """Independently verify tax group anchors and configured column order."""
    anchors = source.get("tax_header_anchors", {})
    columns = source["tax_columns"]
    municipal = anchors.get("municipal_tax_deduction")
    prefectural = anchors.get("prefectural_tax_deduction")
    if not municipal or not prefectural:
        fail("tax_header_anchors must define both tax deduction groups")
    municipal_anchor = column_number(municipal["column"])
    prefectural_anchor = column_number(prefectural["column"])
    municipal_column = column_number(columns["municipal_tax_deduction"])
    prefectural_column = column_number(columns["prefectural_tax_deduction"])
    if not municipal_anchor < municipal_column < prefectural_anchor:
        fail("municipal tax column is not between the municipal and prefectural header anchors")
    if not prefectural_column > prefectural_anchor:
        fail("prefectural tax column is not to the right of the prefectural header anchor")
    start = int(source["tax_row_start"])
    for field, anchor in (("municipal_tax_deduction", municipal), ("prefectural_tax_deduction", prefectural)):
        anchor_column = anchor.get("column")
        column = column_number(anchor_column)
        values = []
        for row_number in range(max(1, start - 8), start):
            value = sheet.cell(row_number, column).value
            if value is not None:
                values.append(normalize_text(value) or "")
        header_text = " ".join(values)
        if not all(token in header_text for token in anchor.get("tokens", [])):
            fail(f"tax header anchor mismatch for {field} ({anchor_column}): {values!r}")


def read_source(source: dict, key: str, *, no_download: bool) -> bytes:
    path = RAW_DIR / source[f"{key}_file"]
    if path.exists():
        data = path.read_bytes()
    elif no_download:
        fail(f"missing cached source: {path}; run without --no-download")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        request = Request(
            source[f"{key}_url"],
            headers={"User-Agent": "furusato-source-reconciliation/2.0 (+https://github.com/ryotamatsuki/furusatonozei)"},
        )
        with urlopen(request, timeout=120) as response:
            data = response.read()
        path.write_bytes(data)
    actual = hashlib.sha256(data).hexdigest()
    expected = source[f"{key}_sha256"].lower()
    if actual != expected:
        fail(f"{key} SHA-256 mismatch for {source[f'{key}_url']}: expected {expected}, got {actual}")
    return data


def workbook_sheet(data: bytes, name: str):
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if name not in workbook.sheetnames:
        fail(f"sheet {name!r} not found; available={workbook.sheetnames}")
    return workbook[name]


def check_headers(sheet, source: dict, manifest: dict, kind: str) -> None:
    manifest_kind = "receipts" if kind == "receipt" else "tax"
    start = int(source[f"{manifest_kind}_row_start"])
    columns = source[f"{manifest_kind}_columns"]
    for field, tokens in manifest.get("header_validation", {}).get(manifest_kind, {}).items():
        column = columns.get(field)
        if not column:
            continue
        index = column_number(column)
        values = []
        for row_number in range(max(1, start - 5), start):
            value = sheet.cell(row_number, index).value
            if value is not None:
                values.append(normalize_text(value) or "")
        header_text = " ".join(values)
        if not any(token in header_text for token in tokens):
            fail(f"{kind} header mismatch for {field} ({column}): {values!r}")
    if kind == "tax":
        check_tax_header_layout(sheet, source)


def parse_official_rows(source: dict, manifest: dict, kind: str, data: bytes) -> dict[str, dict]:
    manifest_kind = "receipts" if kind == "receipt" else "tax"
    sheet_name = source[f"{manifest_kind}_sheet"]
    start = int(source[f"{manifest_kind}_row_start"])
    columns = source[f"{manifest_kind}_columns"]
    sheet = workbook_sheet(data, sheet_name)
    check_headers(sheet, source, manifest, kind)
    code_index = None if columns.get("municipality_code") is None else column_number(columns["municipality_code"]) - 1
    pref_index = column_number(columns["prefecture"]) - 1
    name_index = column_number(columns["municipality"]) - 1
    if kind == "receipt":
        value_fields = {"received": "received", "proxy": "proxy", "expense": "expense"}
    else:
        value_fields = {"municipal_tax_deduction": "municipal_tax_deduction", "prefectural_tax_deduction": "prefectural_tax_deduction"}
    indexes = {field: column_number(columns[field]) - 1 for field in value_fields}

    code_master: dict[tuple[str | None, str], str] = {}
    master_seen: dict[tuple[str | None, str], list[tuple[str, int]]] = defaultdict(list)
    code_sheet_key = f"{manifest_kind}_code_sheet"
    if source.get(code_sheet_key):
        code_sheet = workbook_sheet(data, source[code_sheet_key])
        master_columns = source[f"{manifest_kind}_code_columns"]
        master_code_index = column_number(master_columns["municipality_code"]) - 1
        master_pref_index = column_number(master_columns["prefecture"]) - 1
        master_name_index = column_number(master_columns["municipality"]) - 1
        required = max(master_code_index, master_pref_index, master_name_index)
        for master_row_number, row in enumerate(code_sheet.iter_rows(values_only=True), start=1):
            if len(row) <= required:
                continue
            code = normalize_code(row[master_code_index])
            pref = normalize_text(row[master_pref_index])
            name = normalize_text(row[master_name_index])
            if code and name and name not in {"0", "-", "—", "―"}:
                key = (pref, name)
                master_seen[key].append((code, master_row_number))
                code_master[key] = code
    duplicate_master_keys = {key: values for key, values in master_seen.items() if len(values) > 1}
    if duplicate_master_keys:
        fail(f"{kind} code master duplicate keys: {list(duplicate_master_keys.items())[:5]}")

    rows: dict[str, dict] = {}
    max_required = max([pref_index, name_index, *indexes.values(), *([code_index] if code_index is not None else [])])
    for source_row, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        if source_row < start:
            continue
        if len(row) <= max_required:
            visible = [value for value in row[: max(pref_index, name_index) + 1] if value not in (None, "")]
            if visible:
                fail(f"{kind} short municipality row at source row {source_row}: {visible!r}")
            continue
        pref = normalize_text(row[pref_index])
        name = normalize_text(row[name_index])
        if not name or name in {"0", "-", "—", "―"}:
            continue
        if not pref:
            fail(f"{kind} blank prefecture at source row {source_row}")
        raw_code6 = normalize_code(row[code_index]) if code_index is not None else None
        code6 = code_master.get((pref, name)) or raw_code6
        if kind == "receipt" and not code6:
            fail(f"receipt missing municipality code at source row {source_row}: {pref}{name}")
        code5 = code6[:5] if code6 else None
        key = code5 or f"{pref}|{name}"
        if key in rows:
            fail(f"{kind} duplicate municipality key {key}: rows {rows[key]['source_row']} and {source_row}")
        parsed = {"code5": code5, "code6": code6, "raw_code6": raw_code6, "pref": pref, "name": name, "source_row": source_row}
        for field, index in indexes.items():
            parsed[field] = amount(row[index], field=field, row=source_row, allow_blank=(field == "proxy"))
        rows[key] = parsed
    return rows


def short_name(name: str) -> str:
    return re.sub(r"^.+?郡", "", name)


def join_official(source: dict, manifest: dict, receipt_data: bytes, tax_data: bytes, year: int) -> tuple[list[dict], dict]:
    receipt_rows = parse_official_rows(source, manifest, "receipt", receipt_data)
    tax_rows = parse_official_rows(source, manifest, "tax", tax_data)
    expected_count = int(source["municipality_count"])
    if len(receipt_rows) != expected_count or len(tax_rows) != expected_count:
        fail(f"{year} source count mismatch: receipt={len(receipt_rows)} tax={len(tax_rows)} expected={expected_count}")
    tax_by_code = {row["code5"]: row for row in tax_rows.values() if row["code5"]}
    tax_by_name: dict[tuple[str | None, str], list[dict]] = defaultdict(list)
    tax_by_short_name: dict[tuple[str | None, str], list[dict]] = defaultdict(list)
    for row in tax_rows.values():
        tax_by_name[(row["pref"], row["name"])].append(row)
        tax_by_short_name[(row["pref"], short_name(row["name"]))].append(row)

    records: list[dict] = []
    fallback_corrections: list[dict] = []
    allowed_name_mismatches = {
        (item["municipality_code"], item["receipt_name"], item["tax_name"]): item
        for item in source.get("allowed_code_name_mismatches", [])
    }
    code_corrections = []
    for kind, rows in (("receipt", receipt_rows), ("tax", tax_rows)):
        for row in rows.values():
            if row.get("raw_code6") and row.get("code6") and row["raw_code6"] != row["code6"]:
                code_corrections.append({"kind": kind, "source_row": row["source_row"], "prefecture": row["pref"], "municipality": row["name"], "raw_code6": row["raw_code6"], "canonical_code6": row["code6"]})
    for code5, receipt in receipt_rows.items():
        tax = tax_by_code.get(code5)
        if tax is not None and (tax["pref"], tax["name"]) != (receipt["pref"], receipt["name"]):
            allowed = allowed_name_mismatches.get((code5, receipt["name"], tax["name"]))
            if allowed is None:
                tax = None
            else:
                fallback_corrections.append({"receipt_code6": receipt["code6"], "tax_code6": tax["code6"], "receipt_name": receipt["name"], "tax_name": tax["name"], "reason": "manifest-allowed official code/name correction"})
        if tax is None:
            candidates = tax_by_name.get((receipt["pref"], receipt["name"]), [])
            if not candidates:
                candidates = tax_by_short_name.get((receipt["pref"], short_name(receipt["name"])), [])
            if len(candidates) != 1:
                fail(f"{year} tax code/name join is not unique for {receipt['pref']}{receipt['name']} ({code5}): {len(candidates)} candidates")
            tax = candidates[0]
            fallback_corrections.append({"receipt_code6": receipt["code6"], "tax_code6": tax["code6"], "receipt_name": receipt["name"], "tax_name": tax["name"], "reason": "official code/name join fallback"})
        municipal = tax["municipal_tax_deduction"]
        prefectural = tax["prefectural_tax_deduction"]
        before = receipt["received"] - receipt["expense"] - receipt["proxy"] - municipal
        reference75 = municipal * 0.75
        reference = before + reference75
        records.append({
            "receipt_fiscal_year": year,
            "receipt_fiscal_year_label": source["receipt_fiscal_year_label"],
            "tax_donation_calendar_year": int(source["tax_donation_calendar_year"]),
            "tax_assessment_fiscal_year": int(source["tax_assessment_fiscal_year"]),
            "tax_assessment_fiscal_year_label": source["tax_assessment_fiscal_year_label"],
            "municipality_code": code5,
            "municipality_code6": receipt["code6"],
            "prefecture": receipt["pref"],
            "municipality": receipt["name"],
            "received": receipt["received"],
            "expense": receipt["expense"],
            "proxy": receipt["proxy"],
            "municipal_tax_deduction": municipal,
            "prefectural_tax_deduction": prefectural,
            "resident_tax_deduction_total": municipal + prefectural,
            "balance_before_tax_adjustment": before,
            "tax_deduction_75pct_reference": reference75,
            "balance_with_75pct_reference": reference,
            "receipt_source_row": receipt["source_row"],
            "tax_source_row": tax["source_row"],
            "tax_source_code6": tax["code6"],
            "receipt_raw_code6": receipt.get("raw_code6"),
            "tax_raw_code6": tax.get("raw_code6"),
            "tax_source_prefecture": tax["pref"],
            "tax_source_municipality": tax["name"],
        })
    if len(records) != expected_count:
        fail(f"{year} joined record count: {len(records)} != {expected_count}")
    return records, {"tax_code_join_corrections": fallback_corrections, "code_normalization_corrections": code_corrections}


def extract_json(text: str, variable: str):
    match = re.search(rf"const {re.escape(variable)} = (.*?);\n", text, flags=re.S)
    if not match:
        raise AssertionError(f"{variable} was not found")
    return json.loads(match.group(1))


def equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=TOLERANCE)
    return a == b


def add_error(errors: list[dict], year: int, code: str, name: str, field: str, official, embedded):
    if not equal(official, embedded):
        errors.append({"year": year, "municipality_code": code, "municipality_name": name, "field": field, "official_value": official, "embedded_value": embedded})


def checked_map(rows: list[dict], code_field: str, *, year: int, errors: list[dict], label: str) -> dict:
    result = {}
    for row in rows:
        code = row.get(code_field)
        if code in result:
            errors.append({"year": year, "municipality_code": code or "*", "municipality_name": row.get("municipality", "*"), "field": f"{label}_duplicate_code", "official_value": code, "embedded_value": "duplicate"})
        result[code] = row
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-download", action="store_true", help="require all official workbooks in data/raw")
    parser.add_argument("--report", type=Path, help="write the complete mismatch report as JSON")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    normalized = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    index_text = INDEX_PATH.read_text(encoding="utf-8")
    embedded_data_list = extract_json(index_text, "DATA")
    errors: list[dict] = []
    embedded_data = checked_map(embedded_data_list, "code5", year=int(manifest["period"]["end"]), errors=errors, label="embedded_data")
    embedded_history = extract_json(index_text, "FIVE_YEAR_HISTORY")
    embedded_meta = extract_json(index_text, "FIVE_YEAR_META")
    reconciled_records = 0
    reconciled_fields = 0
    correction_count = 0
    code_sets: list[set[str]] = []

    for year in range(int(manifest["period"]["start"]), int(manifest["period"]["end"]) + 1):
        year_text = str(year)
        source = manifest["sources"][year_text]
        if int(source.get("receipt_fiscal_year", -1)) != year:
            fail(f"source {year} receipt_fiscal_year does not match its key")
        if int(source.get("tax_donation_calendar_year", -1)) != year:
            fail(f"source {year} tax_donation_calendar_year does not match its receipt year")
        if int(source.get("tax_assessment_fiscal_year", -1)) != int(source.get("tax_donation_calendar_year", -2)) + 1:
            fail(f"source {year} tax_assessment_fiscal_year must be donation calendar year + 1")
        receipt_bytes = read_source(source, "receipts", no_download=args.no_download)
        tax_bytes = read_source(source, "tax", no_download=args.no_download)
        official_records, diagnostics = join_official(source, manifest, receipt_bytes, tax_bytes, year)
        correction_count += len(diagnostics["tax_code_join_corrections"]) + len(diagnostics["code_normalization_corrections"])
        official_by_code = checked_map(official_records, "municipality_code", year=year, errors=errors, label="official")
        normalized_by_code = checked_map(normalized["years"][year_text]["records"], "municipality_code", year=year, errors=errors, label="normalized")
        code_sets.append(set(official_by_code))
        if set(official_by_code) != set(normalized_by_code):
            errors.append({"year": year, "municipality_code": "*", "municipality_name": "*", "field": "municipality_code_set", "official_value": sorted(set(official_by_code) - set(normalized_by_code)), "embedded_value": sorted(set(normalized_by_code) - set(official_by_code))})

        receipt_rows: set[int] = set()
        tax_rows: set[int] = set()
        for code, official in official_by_code.items():
            normalized_row = normalized_by_code.get(code)
            if normalized_row is None:
                continue
            if official["receipt_source_row"] in receipt_rows:
                errors.append({"year": year, "municipality_code": code, "municipality_name": official["municipality"], "field": "receipt_source_row_duplicate", "official_value": official["receipt_source_row"], "embedded_value": "duplicate"})
            if official["tax_source_row"] in tax_rows:
                errors.append({"year": year, "municipality_code": code, "municipality_name": official["municipality"], "field": "tax_source_row_duplicate", "official_value": official["tax_source_row"], "embedded_value": "duplicate"})
            receipt_rows.add(official["receipt_source_row"])
            tax_rows.add(official["tax_source_row"])
            for field in SOURCE_FIELDS + DERIVED_FIELDS:
                add_error(errors, year, code, official["municipality"], field, official.get(field), normalized_row.get(field))
                reconciled_fields += 1
            if year == int(manifest["period"]["end"]):
                embedded_fields = {
                    "municipality_code": "code5", "municipality_code6": "code6", "prefecture": "pref", "municipality": "name",
                    "received": "received", "expense": "expense", "proxy": "proxy", "municipal_tax_deduction": "taxDeduction",
                    "prefectural_tax_deduction": "prefecturalTaxDeduction", "resident_tax_deduction_total": "residentTaxDeductionTotal",
                    "receipt_source_row": "receiptSourceRow", "tax_source_row": "taxSourceRow", "tax_source_code6": "taxSourceCode6",
                    "receipt_raw_code6": "receiptRawSourceCode6", "tax_raw_code6": "taxRawSourceCode6",
                    "receipt_fiscal_year": "receiptFiscalYear", "tax_donation_calendar_year": "taxDonationCalendarYear", "tax_assessment_fiscal_year": "taxAssessmentFiscalYear",
                }
                for official_field, embedded_field in embedded_fields.items():
                    add_error(errors, year, code, official["municipality"], f"embedded.{official_field}", official[official_field], embedded_data.get(code, {}).get(embedded_field))
                for official_field, embedded_field in {"balance_before_tax_adjustment": "beforeGrant", "tax_deduction_75pct_reference": "grant75", "balance_with_75pct_reference": "afterGrantStatutory"}.items():
                    add_error(errors, year, code, official["municipality"], f"embedded.{official_field}", official[official_field], embedded_data.get(code, {}).get(embedded_field))
            reconciled_records += 1

        if len(receipt_rows) != len(official_by_code) or len(tax_rows) != len(official_by_code):
            errors.append({"year": year, "municipality_code": "*", "municipality_name": "*", "field": "source_row_coverage", "official_value": len(official_by_code), "embedded_value": {"receipt_rows": len(receipt_rows), "tax_rows": len(tax_rows)}})

        history_rows = embedded_history.get(year_text, [])
        history_by_code = checked_map([{"code5": row[0], "row": row} for row in history_rows], "code5", year=year, errors=errors, label="embedded_history")
        for code, official in official_by_code.items():
            wrapped = history_by_code.get(code)
            if wrapped is None:
                errors.append({"year": year, "municipality_code": code, "municipality_name": official["municipality"], "field": "embedded_history_row", "official_value": "present", "embedded_value": "missing"})
                continue
            row = wrapped["row"]
            for field, position in {"received": 1, "expense": 2, "proxy": 3, "municipal_tax_deduction": 4, "prefectural_tax_deduction": 5, "resident_tax_deduction_total": 6, "balance_with_75pct_reference": 7, "receipt_source_row": 8, "tax_source_row": 9, "receipt_raw_code6": 10, "tax_raw_code6": 11}.items():
                add_error(errors, year, code, official["municipality"], f"embedded_history.{field}", official[field], row[position] if len(row) > position else None)

        meta = embedded_meta.get(year_text, {})
        for field, expected_value, embedded_value in (
            ("receiptFiscalYear", year, meta.get("receiptFiscalYear")),
            ("taxDonationCalendarYear", int(source["tax_donation_calendar_year"]), meta.get("taxDonationCalendarYear")),
            ("taxAssessmentFiscalYear", int(source["tax_assessment_fiscal_year"]), meta.get("taxAssessmentFiscalYear")),
            ("receiptUrl", source["receipts_url"], meta.get("receiptUrl")),
            ("taxUrl", source["tax_url"], meta.get("taxUrl")),
            ("receiptSha256", source["receipts_sha256"], meta.get("receiptSha256")),
            ("taxSha256", source["tax_sha256"], meta.get("taxSha256")),
            ("municipalityCount", int(source["municipality_count"]), meta.get("municipalityCount")),
        ):
            add_error(errors, year, "*", "*", f"embedded_meta.{field}", expected_value, embedded_value)

    if any(code_set != code_sets[0] for code_set in code_sets[1:]):
        errors.append({"year": "all", "municipality_code": "*", "municipality_name": "*", "field": "municipality_code_set_between_years", "official_value": "same set required", "embedded_value": [len(code_set) for code_set in code_sets]})

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        print(json.dumps(errors[:100], ensure_ascii=False, indent=2))
        print(f"SOURCE RECONCILIATION FAIL: {len(errors)} mismatches", file=sys.stderr)
        return 1
    print("SOURCE RECONCILIATION OK")
    print("official source rows:", reconciled_records)
    print("official source-field comparisons:", reconciled_fields)
    print("embedded historical rows:", reconciled_records)
    print("join corrections audited:", correction_count)
    print("mismatches: 0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SOURCE RECONCILIATION FAILED: {exc}", file=sys.stderr)
        raise
