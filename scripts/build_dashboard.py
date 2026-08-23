#!/usr/bin/env python3
"""Build the dashboard with ordinary-local-allocation-tax context.

The existing ``build_data.py`` remains the source-of-truth builder for the
MIC furusato-nozei workbooks.  This wrapper adds a second independently
hash-pinned official source, ordinary local allocation tax, and then embeds
both the primary actual-data fiscal-impact metric and a conservative grant
estimate into the static dashboard.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import build_data as base
import ordinary_grant

ROOT = Path(__file__).resolve().parents[1]
GRANT_MANIFEST_PATH = ROOT / "data" / "ordinary_grant_manifest.json"
MODEL_MARKER = "<!-- ordinary-grant-model-v1 -->"
LATEST_FIELDS = [
    "received", "expense", "proxy", "taxDeduction", "prefecturalTaxDeduction",
    "residentTaxDeductionTotal", "referenceBalance", "receiptSourceRow",
    "taxSourceRow", "receiptRawSourceCode6", "taxRawSourceCode6",
    "ordinaryGrantFiscalYear", "ordinaryGrantAmount", "ordinaryGrantStatus",
    "ordinaryGrantSourceStage", "ordinaryGrantSourceStageLabel",
    "ordinaryGrantSourceRow", "ordinaryGrantSourceUrl", "ordinaryGrantSourceSha256",
    "ordinaryGrantEstimate", "balanceWithOrdinaryGrantEstimate",
]


def fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"UI patch {label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        fail(f"UI patch {label}: expected exactly one regex match, got {count}")
    return updated


def replace_exact_count(text: str, old: str, new: str, label: str, expected_count: int) -> str:
    count = text.count(old)
    if count != expected_count:
        fail(f"UI patch {label}: expected exactly {expected_count} matches, got {count}")
    return text.replace(old, new, expected_count)


def patch_select(text: str, select_id: str, default: str) -> str:
    pattern = rf'(<select\s+id="{re.escape(select_id)}"[^>]*>)(.*?)(</select>)'
    match = re.search(pattern, text, flags=re.S)
    if not match:
        fail(f"select #{select_id} not found")
    body = match.group(2)
    body = re.sub(r"\s+selected(?=>)", "", body)
    replacements = {
        'value="afterGrantStatutory"': 'value="afterGrantStatutory"',
    }
    del replacements  # documentation-only guard against accidental broad replacement
    body = body.replace(
        '>財政影響参考額（市町村民税控除額×75％の制度参考値）</option>',
        '>75％制度参考加算後（参考）</option>',
    )
    body = body.replace(
        '>財政影響参考額（年度推移）</option>',
        '>財政影響額（交付税考慮前・年度推移）</option>',
    )
    body = body.replace(
        '>交付税措置を考慮しない差引参考額</option>',
        '>財政影響額（交付税考慮前・実績ベース）</option>',
    )
    if 'value="ordinaryGrantEstimate"' not in body:
        anchor = '<option value="beforeGrant"'
        idx = body.find(anchor)
        if idx < 0:
            fail(f"select #{select_id}: beforeGrant option not found")
        end = body.find('</option>', idx)
        if end < 0:
            fail(f"select #{select_id}: beforeGrant option end not found")
        end += len('</option>')
        insert = (
            '\n              <option value="ordinaryGrantEstimate">普通交付税考慮額（保守的簡便推計）</option>'
            '\n              <option value="balanceWithOrdinaryGrantEstimate">財政影響額（普通交付税考慮推計後）</option>'
        )
        body = body[:end] + insert + body[end:]
    default_token = f'value="{default}"'
    if default_token not in body:
        fail(f"select #{select_id}: default option {default} not found")
    body = body.replace(default_token, default_token + " selected", 1)
    return text[: match.start()] + match.group(1) + body + match.group(3) + text[match.end() :]


def upgrade_index_ui(text: str) -> str:
    if MODEL_MARKER in text:
        return text

    for select_id in ("metric", "distMetric", "featureY"):
        text = patch_select(text, select_id, "beforeGrant")

    text = replace_regex_once(
        text,
        r"const LABELS = \{.*?\};\nconst SIGNED_METRICS = new Set\(\[.*?\]\);",
        '''const LABELS = {
  afterGrant:"75％制度参考加算後（参考）",
  afterGrantStatutory:"75％制度参考加算後（参考）",
  beforeGrant:"財政影響額（交付税考慮前・実績ベース）",
  ordinaryGrantEstimate:"普通交付税考慮額（保守的簡便推計）",
  balanceWithOrdinaryGrantEstimate:"財政影響額（普通交付税考慮推計後）",
  received:"寄附受入額",
  taxDeduction:"市町村民税控除額（寄附暦年・翌年度課税）",
  expense:"募集に要した費用",
  historyBalance:"財政影響額（交付税考慮前・年度推移）"
};
const SIGNED_METRICS = new Set(["afterGrant","afterGrantStatutory","beforeGrant","balanceWithOrdinaryGrantEstimate","historyBalance"]);''',
        "metric labels",
    )
    text = replace_once(text, 'let currentMetric = "afterGrantStatutory";', 'let currentMetric = "beforeGrant";', "default map metric")
    text = replace_exact_count(
        text,
        'if(key==="afterGrantPerCapita")return Number.isFinite(d.afterGrant)&&Number.isFinite(d.population)&&d.population>0?d.afterGrant/d.population:null;',
        'if(key==="afterGrantPerCapita")return Number.isFinite(d.beforeGrant)&&Number.isFinite(d.population)&&d.population>0?d.beforeGrant/d.population:null;',
        "per-capita fiscal impact",
        2,
    )

    old_history_index = '''const HISTORY_INDEX = new Map(Object.entries(FIVE_YEAR_HISTORY).map(([year,rows])=>[
  Number(year),
  new Map(rows.map(r=>[r[0],{
    code5:r[0],received:r[1],expense:r[2],proxy:r[3],taxDeduction:r[4],
    prefecturalTaxDeduction:r[5],residentTaxDeductionTotal:r[6],
    historyBalance:r[7],receiptSourceRow:r[8],taxSourceRow:r[9],receiptRawSourceCode6:r[10],taxRawSourceCode6:r[11]
  }]))
]));'''
    new_history_index = '''const HISTORY_INDEX = new Map(Object.entries(FIVE_YEAR_HISTORY).map(([year,rows])=>[
  Number(year),
  new Map(rows.map(r=>[r[0],{
    code5:r[0],received:r[1],expense:r[2],proxy:r[3],taxDeduction:r[4],
    prefecturalTaxDeduction:r[5],residentTaxDeductionTotal:r[6],
    historyBalance:r[7],receiptSourceRow:r[8],taxSourceRow:r[9],receiptRawSourceCode6:r[10],taxRawSourceCode6:r[11],
    ordinaryGrantAmount:r[12],ordinaryGrantEstimate:r[13],balanceWithOrdinaryGrantEstimate:r[14],
    ordinaryGrantStatus:r[15],ordinaryGrantSourceStage:r[16],ordinaryGrantSourceStageLabel:r[17],ordinaryGrantSourceRow:r[18],
    legacyReferenceBalance:r[19]
  }]))
]));'''
    text = replace_once(text, old_history_index, new_history_index, "history schema")
    text = replace_once(text, 'LABELS.historyBalance="財政影響参考額（年度推移）";', 'LABELS.historyBalance="財政影響額（交付税考慮前・年度推移）";', "history label")
    text = replace_once(
        text,
        'LABELS.afterGrantPerCapita=`${meta.label}人口1人当たり財政影響参考額`;',
        'LABELS.afterGrantPerCapita=`${meta.label}人口1人当たり財政影響額（交付税考慮前）`;',
        "per-capita label",
    )

    old_nonlatest = '''      d.afterGrantStatutory=h.historyBalance;
      d.afterGrant=h.historyBalance;
      d.referenceBalance=h.historyBalance;
      d.expenseRate=h.received!==0?h.expense/h.received:null;
      d.balanceType=h.historyBalance>=0?"参考値プラス":"参考値マイナス";'''
    new_nonlatest = '''      d.afterGrantStatutory=h.legacyReferenceBalance;
      d.afterGrant=h.legacyReferenceBalance;
      d.referenceBalance=h.legacyReferenceBalance;
      d.expenseRate=h.received!==0?h.expense/h.received:null;
      d.balanceType=h.legacyReferenceBalance>=0?"参考値プラス":"参考値マイナス";'''
    text = replace_once(text, old_nonlatest, new_nonlatest, "historical legacy reference")
    text = replace_once(
        text,
        '''    d.historyBalance=h.historyBalance;
    d.receiptFiscalYear=year;''',
        '''    d.historyBalance=h.historyBalance;
    d.ordinaryGrantFiscalYear=meta.ordinaryGrantFiscalYear;
    d.ordinaryGrantAmount=h.ordinaryGrantAmount;
    d.ordinaryGrantEstimate=h.ordinaryGrantEstimate;
    d.balanceWithOrdinaryGrantEstimate=h.balanceWithOrdinaryGrantEstimate;
    d.ordinaryGrantStatus=h.ordinaryGrantStatus;
    d.ordinaryGrantSourceStage=h.ordinaryGrantSourceStage;
    d.ordinaryGrantSourceStageLabel=h.ordinaryGrantSourceStageLabel;
    d.ordinaryGrantSourceRow=h.ordinaryGrantSourceRow;
    d.ordinaryGrantSourceUrl=meta.ordinaryGrantUrl;
    d.ordinaryGrantSourceSha256=meta.ordinaryGrantSha256;
    d.receiptFiscalYear=year;''',
        "historical grant assignment",
    )

    old_popup = '''      <div class="label">交付税措置を考慮しない差引参考額</div><div>${oku(d.beforeGrant)}</div>
      <div class="label">市町村民税控除額×75％ <span class="value-kind kind-statutory">機械的制度参考値</span></div><div>${oku(d.grant75)}</div>
      <div class="label">財政影響参考額 <span class="value-kind kind-statutory">制度参考値を機械的に加算</span></div><div><b>${oku(d.afterGrantStatutory)}</b></div>'''
    new_popup = '''      <div class="label">財政影響額（交付税考慮前） <span class="value-kind kind-actual">実績ベース主指標</span></div><div><b>${oku(d.beforeGrant)}</b></div>
      <div class="label">市町村民税控除額×75％ <span class="value-kind kind-statutory">基準財政収入額75％反映参考</span></div><div>${oku(d.grant75)}</div>
      <div class="label">普通交付税交付決定額 <span class="value-kind kind-actual">${esc(d.ordinaryGrantSourceStageLabel||"推計対象外")}</span></div><div>${oku(d.ordinaryGrantAmount)}</div>
      <div class="label">普通交付税考慮額 <span class="value-kind kind-statutory">min（75％参考額, 交付決定額）</span></div><div>${oku(d.ordinaryGrantEstimate)}</div>
      <div class="label">財政影響額（普通交付税考慮推計後） <span class="value-kind kind-statutory">保守的簡便推計</span></div><div><b>${oku(d.balanceWithOrdinaryGrantEstimate)}</b></div>
      <div class="label">75％制度参考加算後 <span class="value-kind kind-statutory">比較用・旧参考</span></div><div>${oku(d.afterGrantStatutory)}</div>'''
    text = replace_once(text, old_popup, new_popup, "latest popup metrics")
    text = replace_once(
        text,
        '''      <div>道府県民税控除額 <span class="source-cell">${esc(source.prefecturalTax)}</span></div>
      ${d.taxSourceCode6?`<div>税控除原表コード''',
        '''      <div>道府県民税控除額 <span class="source-cell">${esc(source.prefecturalTax)}</span></div>
      <div>普通交付税 <span class="source-cell">${d.ordinaryGrantSourceRow?`${esc(activeMeta.ordinaryGrantFile)} / ${esc(activeMeta.ordinaryGrantSheet)}!D${esc(d.ordinaryGrantSourceRow)}`:"東京23特別区・個別推計対象外"}</span></div>
      ${d.taxSourceCode6?`<div>税控除原表コード''',
        "latest popup grant source",
    )
    text = replace_regex_once(
        text,
        r'<div class="popup-disclaimer">財政影響参考額は自治体決算上の実質収支ではありません。市町村民税控除額×75％は、基準財政収入額の算定に関係する制度上の要素を機械的に仮置きした参考値で、実際の普通交付税増加額や国からの現金補填を示しません。寄附受入額は\$\{esc\(activeMeta\.label\)\}の集計、市町村民税控除額は\$\{esc\(taxPeriod\)\}です。</div>',
        '<div class="popup-disclaimer">主指標は寄附受入額－募集に要した費用－代理受入額－市町村民税控除額です。普通交付税考慮額は、基準財政収入額への75％反映という制度上の関係を踏まえ、同年度の普通交付税交付決定額を上限にした保守的簡便推計であり、ふるさと納税による実際の普通交付税増加額・現金補填額を復元したものではありません。東京23特別区は区単位推計の対象外です。寄附受入額は${esc(activeMeta.label)}の集計、市町村民税控除額は${esc(taxPeriod)}です。</div>',
        "latest popup disclaimer",
    )

    old_dist = '''<th>寄附受入額</th><th>募集に要した費用</th><th>市町村民税控除額</th><th>交付税措置を考慮しない差引参考額</th><th>75％制度参考値</th><th>財政影響参考額</th>
  </tr></thead><tbody>${shown.map(d=>`<tr>
    <td>${esc(d.pref+d.name)}</td><td>${ranks.get(d.code5)??"―"}</td><td>${valueText(analysisMetricValue(d,key),key)}</td>
    <td>${oku(d.received)}</td><td>${oku(d.expense)}</td><td>${oku(d.taxDeduction)}</td><td>${oku(d.beforeGrant)}</td><td>${oku(d.grant75)}</td><td>${oku(d.afterGrantStatutory)}</td>'''
    new_dist = '''<th>寄附受入額</th><th>募集に要した費用</th><th>市町村民税控除額</th><th>財政影響額（交付税考慮前）</th><th>普通交付税交付決定額</th><th>普通交付税考慮額（推計）</th><th>推計後財政影響額</th><th>75％制度参考額</th>
  </tr></thead><tbody>${shown.map(d=>`<tr>
    <td>${esc(d.pref+d.name)}</td><td>${ranks.get(d.code5)??"―"}</td><td>${valueText(analysisMetricValue(d,key),key)}</td>
    <td>${oku(d.received)}</td><td>${oku(d.expense)}</td><td>${oku(d.taxDeduction)}</td><td>${oku(d.beforeGrant)}</td><td>${oku(d.ordinaryGrantAmount)}</td><td>${oku(d.ordinaryGrantEstimate)}</td><td>${oku(d.balanceWithOrdinaryGrantEstimate)}</td><td>${oku(d.grant75)}</td>'''
    text = replace_once(text, old_dist, new_dist, "distribution table")

    old_header = 'const header=["受入年度","寄附暦年","税課税年度","団体コード","都道府県","市区町村","寄附受入額（総務省原表掲載値）","募集に要した費用（総務省原表掲載値）","代理受入額（総務省原表掲載値）","市町村民税控除額（総務省原表掲載値）","道府県民税控除額（総務省原表掲載値）","住民税控除額合計（内訳合計）","交付税措置を考慮しない差引参考額","市町村民税控除額×75％の制度参考値","財政影響参考額（制度参考値加算後）","受入等原表行","税控除原表行","受入等原表URL","受入等原表SHA256","税控除原表URL","税控除原表SHA256","受入原表コード（6桁）","税控除原表コード（6桁）"];'
    new_header = 'const header=["受入年度","寄附暦年","税課税年度","団体コード","都道府県","市区町村","寄附受入額（総務省原表掲載値）","募集に要した費用（総務省原表掲載値）","代理受入額（総務省原表掲載値）","市町村民税控除額（総務省原表掲載値）","道府県民税控除額（総務省原表掲載値）","住民税控除額合計（内訳合計）","財政影響額（交付税考慮前・実績ベース）","市町村民税控除額×75％の制度参考値","普通交付税交付決定額（総務省原表掲載値）","普通交付税考慮額（保守的簡便推計）","財政影響額（普通交付税考慮推計後）","普通交付税公表段階","受入等原表行","税控除原表行","普通交付税原表行","受入等原表URL","受入等原表SHA256","税控除原表URL","税控除原表SHA256","普通交付税原表URL","普通交付税原表SHA256","受入原表コード（6桁）","税控除原表コード（6桁）"];'
    text = replace_once(text, old_header, new_header, "audit CSV header")
    old_csv_row = 'const row=[meta.receiptFiscalYear,meta.taxDonationCalendarYear,meta.taxAssessmentFiscalYear,d.code6,d.pref,d.name,d.received,d.expense,d.proxy,d.taxDeduction,d.prefecturalTaxDeduction,d.residentTaxDeductionTotal,d.beforeGrant,d.grant75,d.afterGrantStatutory,receiptRow,taxRow,meta.receiptUrl,meta.receiptSha256,meta.taxUrl,meta.taxSha256,receiptRawCode||d.code6,taxRawCode||d.code6];'
    new_csv_row = 'const row=[meta.receiptFiscalYear,meta.taxDonationCalendarYear,meta.taxAssessmentFiscalYear,d.code6,d.pref,d.name,d.received,d.expense,d.proxy,d.taxDeduction,d.prefecturalTaxDeduction,d.residentTaxDeductionTotal,d.beforeGrant,d.grant75,d.ordinaryGrantAmount,d.ordinaryGrantEstimate,d.balanceWithOrdinaryGrantEstimate,d.ordinaryGrantSourceStageLabel,receiptRow,taxRow,d.ordinaryGrantSourceRow,meta.receiptUrl,meta.receiptSha256,meta.taxUrl,meta.taxSha256,meta.ordinaryGrantUrl,meta.ordinaryGrantSha256,receiptRawCode||d.code6,taxRawCode||d.code6];'
    text = replace_once(text, old_csv_row, new_csv_row, "audit CSV row")
    text = replace_once(text, 'a.download="ふるさと納税_原表掲載値・制度参考値_照合.csv";', 'a.download="ふるさと納税_原表掲載値・普通交付税推計_照合.csv";', "audit CSV filename")

    old_history_table = '''$("historyTable").innerHTML=`<table><thead><tr><th>年度</th><th>寄附受入額</th><th>募集に要した費用</th><th>代理受入額</th><th>市町村民税控除額</th><th>道府県民税控除額</th><th>住民税控除額合計</th><th>市町村民税控除額×75％の制度参考値</th><th>財政影響参考額</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.year===selectedYear?"active-year":""}"><td>${esc(fiscalYearLabel(r.year))}</td><td>${yen(r.received)}</td><td>${yen(r.expense)}</td><td>${yen(r.proxy)}</td><td>${yen(r.taxDeduction)}</td><td>${yen(r.prefecturalTaxDeduction)}</td><td>${yen(r.residentTaxDeductionTotal)}</td><td>${yen(r.taxDeduction*.75)}</td><td><b>${yen(r.historyBalance)}</b></td></tr>`).join("")}</tbody></table>`;'''
    new_history_table = '''$("historyTable").innerHTML=`<table><thead><tr><th>年度</th><th>寄附受入額</th><th>募集に要した費用</th><th>代理受入額</th><th>市町村民税控除額</th><th>財政影響額（交付税考慮前）</th><th>75％制度参考額</th><th>普通交付税交付決定額</th><th>普通交付税考慮額（推計）</th><th>推計後財政影響額</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.year===selectedYear?"active-year":""}"><td>${esc(fiscalYearLabel(r.year))}</td><td>${yen(r.received)}</td><td>${yen(r.expense)}</td><td>${yen(r.proxy)}</td><td>${yen(r.taxDeduction)}</td><td><b>${yen(r.historyBalance)}</b></td><td>${yen(r.taxDeduction*.75)}</td><td>${yen(r.ordinaryGrantAmount)}</td><td>${yen(r.ordinaryGrantEstimate)}</td><td>${yen(r.balanceWithOrdinaryGrantEstimate)}</td></tr>`).join("")}</tbody></table>`;'''
    text = replace_once(text, old_history_table, new_history_table, "history table")
    text = text.replace("財政影響参考額 前年度比", "財政影響額（交付税考慮前） 前年度比")
    text = text.replace("財政影響参考額 ${firstLabel}→${latestLabel} 増減率", "財政影響額（交付税考慮前） ${firstLabel}→${latestLabel} 増減率")
    text = text.replace("の財政影響参考額年度推移", "の財政影響額（交付税考慮前）年度推移")
    text = text.replace("${latestLabel} 財政影響参考額", "${latestLabel} 財政影響額（交付税考慮前）")

    old_hist_popup_metrics = '''      <div class="label">住民税控除額合計</div><div>${yen(h.residentTaxDeductionTotal)}</div>
      <div class="label">市町村民税控除額×75％（機械的制度参考値）</div><div>${yen(h.taxDeduction*.75)}</div>
      <div class="label">財政影響参考額（制度参考値を機械的に加算）</div><div><b>${yen(h.historyBalance)}</b></div>'''
    new_hist_popup_metrics = '''      <div class="label">住民税控除額合計</div><div>${yen(h.residentTaxDeductionTotal)}</div>
      <div class="label">財政影響額（交付税考慮前・実績ベース）</div><div><b>${yen(h.historyBalance)}</b></div>
      <div class="label">市町村民税控除額×75％（制度参考）</div><div>${yen(h.taxDeduction*.75)}</div>
      <div class="label">普通交付税交付決定額（${esc(h.ordinaryGrantSourceStageLabel||"推計対象外")}）</div><div>${yen(h.ordinaryGrantAmount)}</div>
      <div class="label">普通交付税考慮額（保守的簡便推計）</div><div>${yen(h.ordinaryGrantEstimate)}</div>
      <div class="label">財政影響額（普通交付税考慮推計後）</div><div>${yen(h.balanceWithOrdinaryGrantEstimate)}</div>'''
    text = replace_once(text, old_hist_popup_metrics, new_hist_popup_metrics, "history popup metrics")
    text = replace_once(
        text,
        '<div class="popup-source"><div class="popup-source-title">原表行</div><div>受入額等：${esc(meta.label)}原表 ${h.receiptSourceRow}行</div><div>住民税控除額：翌年度課税原表 ${h.taxSourceRow}行</div></div>',
        '<div class="popup-source"><div class="popup-source-title">原表行</div><div>受入額等：${esc(meta.label)}原表 ${h.receiptSourceRow}行</div><div>住民税控除額：翌年度課税原表 ${h.taxSourceRow}行</div><div>普通交付税：${h.ordinaryGrantSourceRow?`${esc(meta.ordinaryGrantFile)} / ${esc(meta.ordinaryGrantSheet)}!D${h.ordinaryGrantSourceRow}`:"東京23特別区・個別推計対象外"}</div></div>',
        "history popup source",
    )
    text = replace_regex_once(
        text,
        r'<div class="popup-disclaimer">財政影響参考額は自治体決算上の実質収支ではありません。市町村民税控除額×75％を機械的に加算した制度参考値であり、実際の普通交付税増加額や現金補填を示しません。\$\{esc\(meta\.label\)\}の受入額と\$\{esc\(meta\.taxDonationCalendarYear\)\}年中の寄附に基づく\$\{esc\(meta\.taxAssessmentFiscalYearLabel\)\}の控除額は、集計期間が完全には一致しません。</div>',
        '<div class="popup-disclaimer">主指標は実績ベースの交付税考慮前財政影響額です。普通交付税考慮額は、市町村民税控除額×75％と同年度の普通交付税交付決定額の小さい方を用いる保守的簡便推計で、実際の普通交付税増加額・現金補填額ではありません。東京23特別区は区単位推計対象外です。${esc(meta.label)}の受入額と${esc(meta.taxDonationCalendarYear)}年中の寄附に基づく${esc(meta.taxAssessmentFiscalYearLabel)}の控除額は、集計期間が完全には一致しません。</div>',
        "history popup disclaimer",
    )

    validation_anchor = '''    if(!nearly(d.afterGrantStatutory,d.beforeGrant+d.grant75))errors.push(`${id} 財政影響参考額の式`);
    if(!nearly(d.afterGrant,d.afterGrantStatutory)||!nearly(d.referenceBalance,d.afterGrantStatutory))errors.push(`${id} 互換参照値の一致`);'''
    validation_new = '''    if(!nearly(d.afterGrantStatutory,d.beforeGrant+d.grant75))errors.push(`${id} 75％制度参考加算後の式`);
    if(!nearly(d.afterGrant,d.afterGrantStatutory)||!nearly(d.referenceBalance,d.afterGrantStatutory))errors.push(`${id} 互換参照値の一致`);
    if(d.ordinaryGrantStatus==="special_ward_na"){
      if(d.ordinaryGrantAmount!==null||d.ordinaryGrantEstimate!==null||d.balanceWithOrdinaryGrantEstimate!==null||d.ordinaryGrantSourceRow!==null)errors.push(`${id} 東京23特別区の普通交付税推計対象外`);
    }else{
      if(!Number.isFinite(d.ordinaryGrantAmount)||d.ordinaryGrantAmount<0)errors.push(`${id} 普通交付税交付決定額`);
      if(!nearly(d.ordinaryGrantEstimate,Math.min(d.grant75,d.ordinaryGrantAmount)))errors.push(`${id} 普通交付税考慮額の式`);
      if(!nearly(d.balanceWithOrdinaryGrantEstimate,d.beforeGrant+d.ordinaryGrantEstimate))errors.push(`${id} 普通交付税考慮推計後の式`);
      if(!Number.isInteger(d.ordinaryGrantSourceRow)||d.ordinaryGrantSourceRow<=0)errors.push(`${id} 普通交付税原表行`);
    }
    if(d.ordinaryGrantFiscalYear!==d.taxAssessmentFiscalYear)errors.push(`${id} 普通交付税年度対応`);'''
    text = replace_once(text, validation_anchor, validation_new, "browser validation")

    text = text.replace(
        '「財政影響参考額」は自治体決算上の実質収支ではありません。市町村民税控除額×75％は、基準財政収入額の算定に関係する制度上の要素を機械的に仮置きした制度参考値で、実際の普通交付税増加額・国からの現金補填額、交付団体・不交付団体・特別区の実際の補填の有無や額を示しません。',
        '主指標「財政影響額（交付税考慮前・実績ベース）」は自治体決算上の実質収支ではありません。普通交付税考慮額は、市町村民税控除額×75％と同年度の普通交付税交付決定額の小さい方を用いる保守的簡便推計で、実際の普通交付税増加額・国からの現金補填額を示しません。普通交付税額0円の不交付団体は推計0円、東京23特別区は区単位推計対象外です。',
    )
    text = text.replace("交付税措置を考慮しない差引参考額", "財政影響額（交付税考慮前・実績ベース）")
    text = MODEL_MARKER + "\n" + text
    return text


def build_augmented_embedded(normalized: dict, grant_manifest: dict):
    data, meta, _base_history, data_order = base.build_embedded(normalized)
    latest_year = int(normalized["period"]["end"])
    latest_records = {r["municipality_code"]: r for r in normalized["years"][str(latest_year)]["records"]}

    for row in data:
        record = latest_records[row["code5"]]
        row.update({
            "ordinaryGrantFiscalYear": record["ordinary_grant_fiscal_year"],
            "ordinaryGrantAmount": record["ordinary_grant_amount"],
            "ordinaryGrantStatus": record["ordinary_grant_status"],
            "ordinaryGrantSourceStage": record["ordinary_grant_source_stage"],
            "ordinaryGrantSourceStageLabel": record["ordinary_grant_source_stage_label"],
            "ordinaryGrantSourceRow": record["ordinary_grant_source_row"],
            "ordinaryGrantSourceUrl": record["ordinary_grant_source_url"],
            "ordinaryGrantSourceSha256": record["ordinary_grant_source_sha256"],
            "ordinaryGrantEstimate": record["ordinary_grant_estimate"],
            "balanceWithOrdinaryGrantEstimate": record["balance_with_ordinary_grant_estimate"],
        })

    history = {}
    for year_string, bucket in normalized["years"].items():
        source = bucket["source"]
        grant_fy = int(source["tax_assessment_fiscal_year"])
        grant_source = grant_manifest["sources"][str(grant_fy)]
        meta[year_string].update({
            "ordinaryGrantFiscalYear": grant_fy,
            "ordinaryGrantFiscalYearLabel": grant_source["fiscal_year_label"],
            "ordinaryGrantDecisionStage": grant_source["stage"],
            "ordinaryGrantDecisionStageLabel": grant_source["stage_label"],
            "ordinaryGrantFile": grant_source["file"],
            "ordinaryGrantUrl": grant_source["url"],
            "ordinaryGrantSha256": grant_source["sha256"],
            "ordinaryGrantSheet": grant_source["sheet"],
        })
        record_by_code = {r["municipality_code"]: r for r in bucket["records"]}
        history[year_string] = [
            [
                code,
                record_by_code[code]["received"],
                record_by_code[code]["expense"],
                record_by_code[code]["proxy"],
                record_by_code[code]["municipal_tax_deduction"],
                record_by_code[code]["prefectural_tax_deduction"],
                record_by_code[code]["resident_tax_deduction_total"],
                record_by_code[code]["balance_before_tax_adjustment"],
                record_by_code[code]["receipt_source_row"],
                record_by_code[code]["tax_source_row"],
                record_by_code[code]["receipt_raw_code6"],
                record_by_code[code]["tax_raw_code6"],
                record_by_code[code]["ordinary_grant_amount"],
                record_by_code[code]["ordinary_grant_estimate"],
                record_by_code[code]["balance_with_ordinary_grant_estimate"],
                record_by_code[code]["ordinary_grant_status"],
                record_by_code[code]["ordinary_grant_source_stage"],
                record_by_code[code]["ordinary_grant_source_stage_label"],
                record_by_code[code]["ordinary_grant_source_row"],
                record_by_code[code]["balance_with_75pct_reference"],
            ]
            for code in data_order
        ]
    return data, meta, history


def validate_augmented(normalized: dict, grant_manifest: dict) -> None:
    expected_municipalities = int(normalized["period"]["municipality_count"])
    for year_string, bucket in normalized["years"].items():
        records = bucket["records"]
        if len(records) != expected_municipalities:
            fail(f"{year_string}: municipality count mismatch")
        assessment_year = int(bucket["source"]["tax_assessment_fiscal_year"])
        if str(assessment_year) not in grant_manifest["sources"]:
            fail(f"{year_string}: ordinary-grant source for FY{assessment_year} is missing")
        for record in records:
            ordinary_grant.validate_enriched_record(record, assessment_year=assessment_year)
            source = grant_manifest["sources"][str(assessment_year)]
            if record["ordinary_grant_source_url"] != source["url"]:
                fail(f"{year_string} {record['municipality_code']}: ordinary-grant URL mismatch")
            if record["ordinary_grant_source_sha256"] != source["sha256"]:
                fail(f"{year_string} {record['municipality_code']}: ordinary-grant SHA mismatch")


def build(args: argparse.Namespace) -> None:
    base_args = argparse.Namespace(no_download=args.no_download, no_index=True, check=False)
    base.build(base_args)
    normalized = json.loads(base.PROCESSED_PATH.read_text(encoding="utf-8"))
    grant_manifest = json.loads(GRANT_MANIFEST_PATH.read_text(encoding="utf-8"))

    total_grant_rows = 0
    for year_string, bucket in normalized["years"].items():
        assessment_year = int(bucket["source"]["tax_assessment_fiscal_year"])
        source = dict(grant_manifest["sources"][str(assessment_year)])
        diagnostics = ordinary_grant.enrich_records(
            bucket["records"],
            source,
            no_download=args.no_download,
            expected_count=int(grant_manifest["expected_ordinary_municipality_count"]),
            expected_wards=int(grant_manifest["expected_special_ward_count"]),
        )
        total_grant_rows += diagnostics["ordinary_grant_source_row_count"]
        bucket["diagnostics"]["ordinary_grant"] = diagnostics
        for record in bucket["records"]:
            record["ordinary_grant_source_url"] = source["url"]
            record["ordinary_grant_source_sha256"] = source["sha256"]

    normalized["schema_version"] = 3
    normalized["ordinary_grant_manifest_schema_version"] = grant_manifest["schema_version"]
    normalized["ordinary_grant_source_page_url"] = grant_manifest["source_page_url"]
    normalized["ordinary_grant_definition"] = grant_manifest["definition"]
    validate_augmented(normalized, grant_manifest)
    base.atomic_write_text(base.PROCESSED_PATH, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")

    if args.no_index:
        print(f"built augmented {base.PROCESSED_PATH.relative_to(ROOT)}")
        return

    data, meta, history = build_augmented_embedded(normalized, grant_manifest)
    index = base.INDEX_PATH.read_text(encoding="utf-8")
    index = upgrade_index_ui(index)
    index = base.replace_const(index, "DATA", data)
    index = base.replace_const(index, "FIVE_YEAR_META", meta)
    index = base.replace_const(index, "FIVE_YEAR_HISTORY", history)
    index = base.replace_const(index, "FIVE_YEAR_FIELDS", LATEST_FIELDS)
    base.atomic_write_text(base.INDEX_PATH, index)
    print(f"built augmented {base.PROCESSED_PATH.relative_to(ROOT)}")
    print(f"embedded {len(data)} latest records and {sum(len(rows) for rows in history.values())} historical records")
    print(f"ordinary-grant official municipality rows: {total_grant_rows}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    args = parser.parse_args()
    try:
        build(args)
    except Exception as exc:
        print(f"AUGMENTED BUILD FAILED: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
