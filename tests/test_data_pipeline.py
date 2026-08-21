import json
import math
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DataPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "data/source_manifest.json").read_text(encoding="utf-8"))
        cls.processed = json.loads((ROOT / "data/processed/furusato_data.json").read_text(encoding="utf-8"))
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_period_and_counts(self):
        period = self.manifest["period"]
        years = list(map(str, range(period["start"], period["end"] + 1)))
        self.assertEqual(years, list(self.processed["years"]))
        self.assertEqual(period["fiscal_years"], len(years))
        self.assertEqual(period["municipality_count"], 1741)
        for year in years:
            self.assertEqual(len(self.processed["years"][year]["records"]), period["municipality_count"])

    def test_period_keys_are_explicit_for_every_record(self):
        for year, bucket in self.processed["years"].items():
            source = bucket["source"]
            for record in bucket["records"]:
                self.assertEqual(record["receipt_fiscal_year"], int(year))
                self.assertEqual(record["tax_donation_calendar_year"], source["tax_donation_calendar_year"])
                self.assertEqual(record["tax_assessment_fiscal_year"], source["tax_assessment_fiscal_year"])
                self.assertEqual(record["tax_assessment_fiscal_year"], record["tax_donation_calendar_year"] + 1)

    def test_all_amounts_are_finite_and_formulas_hold(self):
        amount_fields = (
            "received", "expense", "proxy", "municipal_tax_deduction",
            "prefectural_tax_deduction", "resident_tax_deduction_total",
            "balance_before_tax_adjustment", "tax_deduction_75pct_reference",
            "balance_with_75pct_reference",
        )
        for bucket in self.processed["years"].values():
            for record in bucket["records"]:
                for field in amount_fields:
                    value = record[field]
                    self.assertTrue(math.isfinite(float(value)), (record["municipality_code"], field))
                self.assertGreaterEqual(record["received"], 0)
                self.assertGreaterEqual(record["expense"], 0)
                self.assertGreaterEqual(record["proxy"], 0)
                self.assertAlmostEqual(record["resident_tax_deduction_total"], record["municipal_tax_deduction"] + record["prefectural_tax_deduction"], places=5)
                self.assertAlmostEqual(record["balance_before_tax_adjustment"], record["received"] - record["expense"] - record["proxy"] - record["municipal_tax_deduction"], places=5)
                self.assertAlmostEqual(record["tax_deduction_75pct_reference"], record["municipal_tax_deduction"] * 0.75, places=5)
                self.assertAlmostEqual(record["balance_with_75pct_reference"], record["balance_before_tax_adjustment"] + record["tax_deduction_75pct_reference"], places=5)

    def test_ui_does_not_use_disallowed_indicator_labels(self):
        ui = self.index
        self.assertNotIn("実質収支額", ui)
        self.assertNotIn("5年推移", ui)
        self.assertNotIn("5年増減率", ui)
        self.assertIn("実質収支ではありません", ui)
        self.assertIn("実際の普通交付税増加額", ui)
        self.assertIn("taxPeriodSidebar", ui)
        embedded = "\n".join(
            re.findall(r"const (?:DATA|FIVE_YEAR_META|FIVE_YEAR_HISTORY) = (.*?);\n", ui, flags=re.S)
        )
        self.assertIsNone(re.search(r"\b(?:NaN|Infinity|-Infinity)\b", embedded))


if __name__ == "__main__":
    unittest.main()
