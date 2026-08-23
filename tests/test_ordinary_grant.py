import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ordinary_grant  # noqa: E402


def source():
    return {
        "fiscal_year": 2026,
        "stage": "initial",
        "stage_label": "当初決定額",
        "url": "https://example.invalid/grant.xlsx",
        "file": "grant.xlsx",
        "sha256": "0" * 64,
        "sheet": "市町村分",
        "row_start": 7,
        "columns": {"prefecture": "B", "municipality": "C", "amount_thousand_yen": "D"},
        "unit_multiplier": 1000,
    }


def normal(code, name, tax=100.0, before=-50.0):
    return {
        "municipality_code": code,
        "prefecture": "愛媛県",
        "municipality": name,
        "tax_deduction_75pct_reference": tax * 0.75,
        "balance_before_tax_adjustment": before,
    }


def ward(code="13101", name="千代田区"):
    return {
        "municipality_code": code,
        "prefecture": "東京都",
        "municipality": name,
        "tax_deduction_75pct_reference": 75.0,
        "balance_before_tax_adjustment": -50.0,
    }


def test_estimate_is_capped_by_actual_ordinary_grant(monkeypatch):
    records = [normal("38201", "松山市")]
    monkeypatch.setattr(
        ordinary_grant,
        "parse_source",
        lambda *_args, **_kwargs: {"38201": {"source_row": 10, "amount": 40}},
    )
    diagnostics = ordinary_grant.enrich_records(records, source(), no_download=True, expected_count=1, expected_wards=0)
    row = records[0]
    assert row["ordinary_grant_amount"] == 40
    assert row["ordinary_grant_estimate"] == 40
    assert row["balance_with_ordinary_grant_estimate"] == -10
    assert diagnostics["ordinary_grant_estimate_capped_count"] == 1
    ordinary_grant.validate_enriched_record(row, assessment_year=2026)


def test_nonrecipient_estimate_is_zero(monkeypatch):
    records = [normal("38201", "松山市")]
    monkeypatch.setattr(
        ordinary_grant,
        "parse_source",
        lambda *_args, **_kwargs: {"38201": {"source_row": 10, "amount": 0}},
    )
    ordinary_grant.enrich_records(records, source(), no_download=True, expected_count=1, expected_wards=0)
    row = records[0]
    assert row["ordinary_grant_status"] == "non_recipient"
    assert row["ordinary_grant_estimate"] == 0
    assert row["balance_with_ordinary_grant_estimate"] == -50


def test_special_ward_is_explicitly_out_of_scope(monkeypatch):
    records = [ward()]
    monkeypatch.setattr(ordinary_grant, "parse_source", lambda *_args, **_kwargs: {})
    ordinary_grant.enrich_records(records, source(), no_download=True, expected_count=0, expected_wards=1)
    row = records[0]
    assert row["ordinary_grant_status"] == "special_ward_na"
    assert row["ordinary_grant_amount"] is None
    assert row["ordinary_grant_estimate"] is None
    assert row["balance_with_ordinary_grant_estimate"] is None
    ordinary_grant.validate_enriched_record(row, assessment_year=2026)


def test_wrong_fiscal_year_is_rejected(monkeypatch):
    records = [normal("38201", "松山市")]
    monkeypatch.setattr(
        ordinary_grant,
        "parse_source",
        lambda *_args, **_kwargs: {"38201": {"source_row": 10, "amount": 100}},
    )
    ordinary_grant.enrich_records(records, source(), no_download=True, expected_count=1, expected_wards=0)
    with pytest.raises(RuntimeError, match="tax assessment year"):
        ordinary_grant.validate_enriched_record(records[0], assessment_year=2025)
