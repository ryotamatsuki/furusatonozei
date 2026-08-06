from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ORIGINAL = ROOT / "reference" / "original.html"


def extract_json(text: str, variable: str):
    pattern = rf"const {re.escape(variable)} = (.*?);\n"
    match = re.search(pattern, text, flags=re.S)
    if not match:
        raise AssertionError(f"{variable} was not found")
    return json.loads(match.group(1))


def close(a: float, b: float, tolerance: float = 1e-5) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=tolerance)


def main() -> None:
    index = INDEX.read_text(encoding="utf-8")
    original = ORIGINAL.read_text(encoding="utf-8")
    latest = extract_json(original, "DATA")
    history = extract_json(index, "FIVE_YEAR_HISTORY")

    expected_years = ["2020", "2021", "2022", "2023", "2024"]
    assert list(history) == expected_years, list(history)
    assert len(latest) == 1741

    latest_codes = {row["code5"] for row in latest}
    assert len(latest_codes) == 1741

    for year in expected_years:
        rows = history[year]
        assert len(rows) == 1741, (year, len(rows))
        codes = {row[0] for row in rows}
        assert codes == latest_codes, (year, len(codes), len(latest_codes - codes))
        for row in rows:
            code, received, expense, proxy, tax, balance, receipt_row, tax_row = row
            expected = received - expense - proxy - tax + tax * 0.75
            assert close(balance, expected), (year, code, balance, expected)
            assert receipt_row > 0 and tax_row > 0

    latest_by_code = {row["code5"]: row for row in latest}
    history_2024 = {row[0]: row for row in history["2024"]}
    for code, current in latest_by_code.items():
        embedded = history_2024[code]
        assert close(current["received"], embedded[1]), (code, "received")
        assert close(current["expense"], embedded[2]), (code, "expense")
        assert close(current["proxy"], embedded[3]), (code, "proxy")
        assert close(current["taxDeduction"], embedded[4]), (code, "taxDeduction")
        assert close(current["afterGrantStatutory"], embedded[5]), (code, "afterGrantStatutory")

    required_ids = [
        'id="fiscalYear"',
        'id="panel-history"',
        'id="historyMunicipality"',
        'id="historyReceivedChart"',
        'id="historyBalanceChart"',
    ]
    for item in required_ids:
        assert item in index, item

    print("VALIDATION OK")
    print("years:", ", ".join(expected_years))
    print("municipalities per year:", 1741)
    print("embedded financial records:", 1741 * 5)
    print("latest-year values match the attached original:", "yes")


if __name__ == "__main__":
    main()
