#!/usr/bin/env python3
"""发票与合同信息抽取：OCR 文本 → 结构化字段 → 校验 → 通过则入库，失败进入人工复核。

本示例假设 OCR 已完成，输入为纯文本（data/docs/*.txt）。
- 字段通过"标签：值"规则抽取，并统一日期与金额格式。
- 校验：必填字段、日期合法性、金额为数字、金额合计 + 税额 = 价税合计（容差 0.01）。
- 任何校验失败的文档进入 review_queue.json，不会自动入库。

用法：python extract.py --docs data/docs --out reports
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 字段 → (标签候选, 类型)
INVOICE_FIELDS = {
    "invoice_no": (["发票号码"], "text"),
    "invoice_date": (["开票日期"], "date"),
    "buyer_name": (["购买方名称", "甲方（买方）"], "text"),
    "seller_name": (["销售方名称", "乙方（卖方）"], "text"),
    "currency": (["币种"], "text"),
    "subtotal": (["金额合计"], "amount"),
    "tax_amount": (["税额"], "amount"),
    "total_amount": (["价税合计", "合同金额"], "amount"),
    "contract_no": (["合同编号"], "text"),
    "sign_date": (["签订日期"], "date"),
}
REQUIRED_BY_TYPE = {
    "invoice": {"invoice_no", "invoice_date", "buyer_name", "seller_name", "total_amount"},
    "contract": {"contract_no", "sign_date", "buyer_name", "seller_name", "total_amount"},
}
TOLERANCE = Decimal("0.01")
DATE_RE = re.compile(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})日?")


def _find_value(text: str, labels: list[str]) -> str | None:
    for label in labels:
        m = re.search(rf"^{re.escape(label)}[：:]\s*(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def _parse_amount(raw: str) -> Decimal:
    cleaned = re.sub(r"[人民币元,\s]", "", raw)
    return Decimal(cleaned)


def _parse_date(raw: str) -> str:
    m = DATE_RE.search(raw)
    if not m:
        raise ValueError(f"无法识别日期：{raw}")
    return date(int(m[1]), int(m[2]), int(m[3])).isoformat()  # 非法日期会抛 ValueError


def extract_fields(text: str) -> tuple[dict, list[str]]:
    """返回 (字段字典, 错误列表)。字段解析失败时记录错误，不中断。"""
    data: dict = {}
    errors: list[str] = []
    for field, (labels, kind) in INVOICE_FIELDS.items():
        raw = _find_value(text, labels)
        if raw is None:
            continue
        try:
            if kind == "date":
                data[field] = _parse_date(raw)
            elif kind == "amount":
                data[field] = str(_parse_amount(raw))
            else:
                data[field] = raw
        except (ValueError, InvalidOperation) as exc:
            errors.append(f"{field} 解析失败：{exc}")
    return data, errors


def validate(data: dict, errors: list[str] | None = None, doc_type: str = "invoice") -> list[str]:
    problems = list(errors or [])
    for f in sorted(REQUIRED_BY_TYPE[doc_type] - data.keys()):
        problems.append(f"缺少必填字段：{f}")
    if {"subtotal", "tax_amount", "total_amount"} <= data.keys():
        diff = Decimal(data["subtotal"]) + Decimal(data["tax_amount"]) - Decimal(data["total_amount"])
        if abs(diff) > TOLERANCE:
            problems.append(f"金额勾稽失败：金额合计 + 税额 与 价税合计 相差 {diff:+.2f}")
    return problems


def process(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    kind = "invoice" if "发票" in text.splitlines()[0] or "发票号码" in text else "contract"
    data, parse_errors = extract_fields(text)
    if kind == "contract":
        data.setdefault("currency", "CNY")  # 合同金额默认人民币（示例约定）
    problems = validate(data, parse_errors, kind)
    return {"file": path.name, "doc_type": kind, "fields": data,
            "status": "ok" if not problems else "needs_review", "problems": problems}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="发票与合同信息抽取")
    p.add_argument("--docs", type=Path, default=HERE / "data" / "docs")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    args = p.parse_args(argv)
    files = sorted(args.docs.glob("*.txt"))
    if not files:
        print(f"[错误] 目录中没有 .txt 文件：{args.docs}", file=sys.stderr)
        return 1
    results = [process(f) for f in files]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "extracted.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    review = [r for r in results if r["status"] != "ok"]
    (args.out / "review_queue.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"处理 {len(results)} 份文档，通过 {len(results) - len(review)}，待复核 {len(review)}")
    for r in review:
        for prob in r["problems"]:
            print(f"  - {r['file']}: {prob}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
