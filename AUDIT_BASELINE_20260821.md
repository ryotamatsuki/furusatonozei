# Baseline audit (2026-08-21 JST)

This file records the pre-change state used for the data-integrity update.

## Git

- Remote: `https://github.com/ryotamatsuki/furusatonozei.git`
- `origin/main` at start: `151d43be718ce9d4ef5487283ff6cc249b0659bc`
- Starting worktree: clean, checked out at the same SHA
- Feature branch: `feature/furusato-data-integrity-v2`

## Repository snapshot

- Files: `README.md`, `VALIDATION.txt`, `data/source_manifest.json`, `index.html`, `open_dashboard.bat`, `reference/original.html`, `scripts/validate_repository.py`
- `index.html` size: 2,214,820 bytes
- `FIVE_YEAR_HISTORY`: 2020, 2021, 2022, 2023, 2024
- Rows per history year: 1,741
- Embedded financial history rows: 8,705
- `DATA` rows: 1,741
- `source_manifest.json`: five source-year entries (2020–2024), with receipt/tax URLs and SHA-256 values; no machine-readable three-year period mapping

## Pre-change validator

Command:

```text
python scripts/validate_repository.py
```

Result:

```text
VALIDATION OK
years: 2020, 2021, 2022, 2023, 2024
municipalities per year: 1741
embedded financial records: 8705
latest-year values match the attached original: yes
```

The pre-change validator checks embedded shape, the five-year formula, selected latest-year consistency with `reference/original.html`, and required DOM IDs. It does not download or reconcile the embedded records against every official workbook row.

## Known pre-change UI terminology

- History tab: `5年推移`
- Main history metric: `実質収支額（5年比較用・75％相当額反映後）`
- The formula and UI combine fiscal-year receipt data with the following fiscal year's tax-assessment data without exposing the three period keys as a data model.
- Browser baseline was not yet automated; the existing `VALIDATION.txt` contains a manually recorded smoke-test result only.
