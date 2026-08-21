import json
import base64
import gzip
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
        cls.data_bundle = (ROOT / "data/embedded_data.js").read_text(encoding="utf-8")
        cls.history_bundle = (ROOT / "data/embedded_history.js").read_text(encoding="utf-8")

    @staticmethod
    def decode_bundle(text, variable):
        match = re.search(rf'const {re.escape(variable)} = "([^"]+)";', text)
        if match is None:
            raise AssertionError(f"missing {variable}")
        return json.loads(gzip.decompress(base64.b64decode(match.group(1))).decode("utf-8"))

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
            manifest_source = self.manifest["sources"][year]
            self.assertEqual(manifest_source["receipt_fiscal_year"], int(year))
            self.assertEqual(manifest_source["tax_donation_calendar_year"], int(year))
            self.assertEqual(manifest_source["tax_assessment_fiscal_year"], manifest_source["tax_donation_calendar_year"] + 1)
            self.assertIn("municipal_tax_deduction", manifest_source["tax_header_anchors"])
            self.assertIn("prefectural_tax_deduction", manifest_source["tax_header_anchors"])
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
        self.assertIn("src=\"vendor/chart.umd.min.js\"", ui)
        self.assertIn("src=\"vendor/pako_inflate.min.js\"", ui)
        self.assertIn("src=\"data/embedded_data.js\"", ui)
        self.assertIn("src=\"data/embedded_history.js\"", ui)
        self.assertNotIn("cdn.jsdelivr.net/npm/chart.js", ui)
        data = self.decode_bundle(self.data_bundle, "FURUSATO_DATA_GZIP_B64")
        history = self.decode_bundle(self.history_bundle, "FURUSATO_HISTORY_GZIP_B64")
        embedded = json.dumps({"data": data, "history": history}, ensure_ascii=False)
        self.assertIsNone(re.search(r"\b(?:NaN|Infinity|-Infinity)\b", embedded))


if __name__ == "__main__":
    unittest.main()
