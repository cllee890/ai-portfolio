#!/usr/bin/env python3
"""平台结算单对账：把结算明细与订单记录逐笔比对，输出差异清单。

期望到账金额 = 订单金额 - 平台佣金 - 退款金额
实际到账金额 = 结算单 net_amount

差异类型：
- MISSING_SETTLEMENT：订单存在，但结算单中没有对应记录
- UNKNOWN_ORDER：结算单中的订单在订单表中不存在
- DUPLICATE_SETTLEMENT：同一订单出现多条结算记录
- CURRENCY_MISMATCH：结算币种与订单币种不一致
- AMOUNT_MISMATCH：实际到账与期望金额差额超过容差
- REFUND_MISMATCH：结算单退款金额与订单退款金额不一致

金额全部使用 Decimal，避免浮点误差。
用法：python reconcile.py --orders data/orders.csv --settlement data/settlement.csv --out reports
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TOLERANCE = Decimal("0.01")


def money(value: str, field: str, row_id: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{row_id}: 字段 {field} 不是合法金额：{value!r}") from exc


def load_orders(path: Path) -> dict[str, dict]:
    orders: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            oid = row["order_id"].strip()
            if oid in orders:
                raise ValueError(f"订单表中 order_id 重复：{oid}")
            orders[oid] = {
                "currency": row["currency"].strip(),
                "order_amount": money(row["order_amount"], "order_amount", oid),
                "platform_commission": money(row["platform_commission"], "platform_commission", oid),
                "refund_amount": money(row["refund_amount"], "refund_amount", oid),
            }
            o = orders[oid]
            o["expected_net"] = o["order_amount"] - o["platform_commission"] - o["refund_amount"]
    return orders


def load_settlements(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            sid = row["settlement_id"].strip()
            rows.append({
                "settlement_id": sid,
                "order_id": row["order_id"].strip(),
                "currency": row["currency"].strip(),
                "net_amount": money(row["net_amount"], "net_amount", sid),
                "refund_amount": money(row["refund_amount"], "refund_amount", sid),
            })
    return rows


def reconcile(orders: dict[str, dict], settlements: list[dict],
              tolerance: Decimal = DEFAULT_TOLERANCE) -> tuple[list[dict], dict]:
    discrepancies: list[dict] = []

    def add(kind, order_id, detail, expected="", actual=""):
        discrepancies.append({"type": kind, "order_id": order_id, "detail": detail,
                              "expected": str(expected), "actual": str(actual)})

    by_order: dict[str, list[dict]] = defaultdict(list)
    for s in settlements:
        by_order[s["order_id"]].append(s)

    for oid, lines in by_order.items():
        if oid not in orders:
            add("UNKNOWN_ORDER", oid, "结算单中的订单不在订单表中")
            continue
        if len(lines) > 1:
            ids = ", ".join(l["settlement_id"] for l in lines)
            add("DUPLICATE_SETTLEMENT", oid, f"同一订单有 {len(lines)} 条结算记录（{ids}）")

    for oid, o in orders.items():
        lines = by_order.get(oid, [])
        if not lines:
            add("MISSING_SETTLEMENT", oid, "订单未出现在结算单中", expected=o["expected_net"])
            continue
        s = lines[0]  # 重复记录已单独报告，此处以第一条比对金额
        if s["currency"] != o["currency"]:
            add("CURRENCY_MISMATCH", oid, f"订单币种 {o['currency']}，结算币种 {s['currency']}")
            continue
        diff = s["net_amount"] - o["expected_net"]
        if abs(diff) > tolerance:
            add("AMOUNT_MISMATCH", oid,
                f"差额 {diff:+.2f} {o['currency']}（容差 {tolerance}）",
                expected=o["expected_net"], actual=s["net_amount"])
        if s["refund_amount"] != o["refund_amount"]:
            add("REFUND_MISMATCH", oid, "结算单与订单的退款金额不一致",
                expected=o["refund_amount"], actual=s["refund_amount"])

    summary = {
        "orders": len(orders),
        "settlement_lines": len(settlements),
        "matched_clean": len(orders) - len({d["order_id"] for d in discrepancies if d["order_id"] in orders}),
        "discrepancies": len(discrepancies),
        "by_type": dict(sorted(_count(discrepancies).items())),
    }
    return discrepancies, summary


def _count(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it["type"]] += 1
    return counts


def write_outputs(out_dir: Path, discrepancies: list[dict], summary: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "discrepancies.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["type", "order_id", "detail", "expected", "actual"])
        w.writeheader()
        w.writerows(discrepancies)
    lines = ["# 结算对账报告", "", "## 汇总", ""]
    lines += [f"- 订单数：{summary['orders']}", f"- 结算明细行数：{summary['settlement_lines']}",
              f"- 无差异订单数：{summary['matched_clean']}", f"- 差异条数：{summary['discrepancies']}", ""]
    lines += ["## 差异类型分布", "", "| 类型 | 条数 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary["by_type"].items()] or ["| 无 | 0 |"]
    lines += ["", "## 差异明细", "", "| 类型 | 订单 | 说明 | 期望 | 实际 |", "|---|---|---|---|---|"]
    lines += [f"| {d['type']} | {d['order_id']} | {d['detail']} | {d['expected']} | {d['actual']} |"
              for d in discrepancies]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="平台结算单对账")
    p.add_argument("--orders", type=Path, default=HERE / "data" / "orders.csv")
    p.add_argument("--settlement", type=Path, default=HERE / "data" / "settlement.csv")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    p.add_argument("--tolerance", type=Decimal, default=DEFAULT_TOLERANCE)
    p.add_argument("--strict", action="store_true", help="存在差异时以退出码 2 结束（用于 CI 或定时任务）")
    args = p.parse_args(argv)
    try:
        orders = load_orders(args.orders)
        settlements = load_settlements(args.settlement)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    discrepancies, summary = reconcile(orders, settlements, args.tolerance)
    write_outputs(args.out, discrepancies, summary)
    print(f"订单 {summary['orders']} 笔，结算 {summary['settlement_lines']} 行，差异 {summary['discrepancies']} 条")
    print(f"报告已写入 {args.out / 'report.md'}")
    return 2 if (args.strict and discrepancies) else 0


if __name__ == "__main__":
    sys.exit(main())
