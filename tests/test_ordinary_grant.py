import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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


class OrdinaryGrantModelTests(unittest.TestCase):
    def test_estimate_is_capped_by_actual_ordinary_grant(self):
        records = [normal("38201", "松山市")]
        with patch.object(
            ordinary_grant,
            "parse_source",
            return_value={"38201": {"source_row": 10, "amount": 40}},
        ):
            diagnostics = ordinary_grant.enrich_records(
                records, source(), no_download=True, expected_count=1, expected_wards=0
            )
        row = records[0]
        self.assertEqual(row["ordinary_grant_amount"], 40)
        self.assertEqual(row["ordinary_grant_estimate"], 40)
        self.assertEqual(row["balance_with_ordinary_grant_estimate"], -10)
        self.assertEqual(diagnostics["ordinary_grant_estimate_capped_count"], 1)
        ordinary_grant.validate_enriched_record(row, assessment_year=2026)

    def test_nonrecipient_estimate_is_zero(self):
        records = [normal("38201", "松山市")]
        with patch.object(
            ordinary_grant,
            "parse_source",
            return_value={"38201": {"source_row": 10, "amount": 0}},
        ):
            ordinary_grant.enrich_records(
                records, source(), no_download=True, expected_count=1, expected_wards=0
            )
        row = records[0]
        self.assertEqual(row["ordinary_grant_status"], "non_recipient")
        self.assertEqual(row["ordinary_grant_estimate"], 0)
        self.assertEqual(row["balance_with_ordinary_grant_estimate"], -50)

    def test_special_ward_is_explicitly_out_of_scope(self):
        records = [ward()]
        with patch.object(ordinary_grant, "parse_source", return_value={}):
            ordinary_grant.enrich_records(
                records, source(), no_download=True, expected_count=0, expected_wards=1
            )
        row = records[0]
        self.assertEqual(row["ordinary_grant_status"], "special_ward_na")
        self.assertIsNone(row["ordinary_grant_amount"])
        self.assertIsNone(row["ordinary_grant_estimate"])
        self.assertIsNone(row["balance_with_ordinary_grant_estimate"])
        ordinary_grant.validate_enriched_record(row, assessment_year=2026)

    def test_wrong_fiscal_year_is_rejected(self):
        records = [normal("38201", "松山市")]
        with patch.object(
            ordinary_grant,
            "parse_source",
            return_value={"38201": {"source_row": 10, "amount": 100}},
        ):
            ordinary_grant.enrich_records(
                records, source(), no_download=True, expected_count=1, expected_wards=0
            )
        with self.assertRaisesRegex(RuntimeError, "tax assessment year"):
            ordinary_grant.validate_enriched_record(records[0], assessment_year=2025)


if __name__ == "__main__":
    unittest.main()
