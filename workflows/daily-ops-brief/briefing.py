#!/usr/bin/env python3
"""每日运营简报：汇总指标、计算环比与 7 日均值、触发阈值告警、检查库存覆盖。

用法：python briefing.py --metrics data/daily_metrics.csv --inventory data/inventory.csv --out reports
阈值可通过参数调整（见 --help）。
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Thresholds:
    sales_drop_pct: Decimal = Decimal("0.20")     # 相对 7 日均值下降超过 20% 告警
    min_roas: Decimal = Decimal("2.0")            # 广告回报率（销售额 / 广告费）低于 2 告警
    max_refund_rate: Decimal = Decimal("0.10")    # 退款率高于 10% 告警
    min_cover_buffer_days: int = 0                # 库存覆盖天数低于补货周期 + 缓冲时告警


def _d(v: str, field: str, day: str) -> Decimal:
    try:
        return Decimal(v.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{day}: 字段 {field} 不是数字：{v!r}") from exc


def load_metrics(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            day = date.fromisoformat(r["date"].strip()).isoformat()
            rows.append({
                "date": day,
                "sales": _d(r["sales"], "sales", day),
                "orders": int(_d(r["orders"], "orders", day)),
                "ad_spend": _d(r["ad_spend"], "ad_spend", day),
                "refund_amount": _d(r["refund_amount"], "refund_amount", day),
            })
    rows.sort(key=lambda x: x["date"])
    if len(rows) < 2:
        raise ValueError("指标至少需要 2 天数据才能计算环比")
    return rows


def load_inventory(path: Path) -> list[dict]:
    items = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            sku = r["sku"].strip()
            daily = _d(r["avg_daily_units"], "avg_daily_units", sku)
            if daily <= 0:
                raise ValueError(f"{sku}: avg_daily_units 必须大于 0")
            items.append({"sku": sku, "product": r["product"].strip(),
                          "stock": int(_d(r["stock"], "stock", sku)),
                          "avg_daily_units": daily,
                          "lead_time_days": int(_d(r["lead_time_days"], "lead_time_days", sku))})
    return items


def compute_kpis(rows: list[dict]) -> dict:
    today, prev = rows[-1], rows[-2]
    window = rows[-8:-1] if len(rows) >= 8 else rows[:-1]   # 最近 7 天（不含当天）
    avg7_sales = Decimal(str(mean(r["sales"] for r in window)))
    avg7_orders = mean(r["orders"] for r in window)
    roas = today["sales"] / today["ad_spend"] if today["ad_spend"] else None
    refund_rate = today["refund_amount"] / today["sales"] if today["sales"] else Decimal(0)
    return {
        "date": today["date"],
        "sales": today["sales"],
        "orders": today["orders"],
        "sales_dod_pct": (today["sales"] - prev["sales"]) / prev["sales"],
        "sales_vs_7d_pct": (today["sales"] - avg7_sales) / avg7_sales,
        "orders_vs_7d": today["orders"] - avg7_orders,
        "roas": roas,
        "refund_rate": refund_rate,
        "window_days": len(window),
    }


def build_alerts(kpi: dict, inventory: list[dict], t: Thresholds) -> list[str]:
    alerts = []
    if kpi["sales_vs_7d_pct"] < -t.sales_drop_pct:
        alerts.append(f"销售额较近 {kpi['window_days']} 日均值下降 {abs(kpi['sales_vs_7d_pct']):.1%}，超过 {t.sales_drop_pct:.0%} 阈值")
    if kpi["roas"] is not None and kpi["roas"] < t.min_roas:
        alerts.append(f"广告回报率 {kpi['roas']:.2f}，低于 {t.min_roas}")
    if kpi["refund_rate"] > t.max_refund_rate:
        alerts.append(f"退款率 {kpi['refund_rate']:.1%}，高于 {t.max_refund_rate:.0%}")
    for item in inventory:
        cover = item["stock"] / item["avg_daily_units"]
        item["cover_days"] = cover
        if cover < item["lead_time_days"] + t.min_cover_buffer_days:
            alerts.append(f"{item['sku']}（{item['product']}）库存可售 {cover:.1f} 天，"
                          f"短于补货周期 {item['lead_time_days']} 天，需立即下单")
    return alerts


def render(kpi: dict, alerts: list[str], inventory: list[dict]) -> str:
    def pct(v):
        return f"{v:+.1%}"
    roas = "-" if kpi["roas"] is None else f"{kpi['roas']:.2f}"
    lines = [f"# 每日运营简报 {kpi['date']}", "", "## 核心指标", "",
             "| 指标 | 数值 | 对比 |", "|---|---|---|",
             f"| 销售额 | {kpi['sales']:.2f} | 环比 {pct(kpi['sales_dod_pct'])}，较近 7 日均值 {pct(kpi['sales_vs_7d_pct'])} |",
             f"| 订单数 | {kpi['orders']} | 较近 7 日均值 {kpi['orders_vs_7d']:+.1f} |",
             f"| 广告回报率 (ROAS) | {roas} | - |",
             f"| 退款率 | {kpi['refund_rate']:.1%} | - |", "", "## 告警"]
    lines += [f"- ⚠️ {a}" for a in alerts] or ["- 无告警"]
    lines += ["", "## 库存覆盖", "", "| SKU | 商品 | 库存 | 日均销量 | 可售天数 | 补货周期 |", "|---|---|---|---|---|---|"]
    lines += [f"| {i['sku']} | {i['product']} | {i['stock']} | {i['avg_daily_units']} | "
              f"{i['cover_days']:.1f} | {i['lead_time_days']} |" for i in inventory]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="每日运营简报")
    p.add_argument("--metrics", type=Path, default=HERE / "data" / "daily_metrics.csv")
    p.add_argument("--inventory", type=Path, default=HERE / "data" / "inventory.csv")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    p.add_argument("--sales-drop", type=Decimal, default=Thresholds.sales_drop_pct)
    p.add_argument("--min-roas", type=Decimal, default=Thresholds.min_roas)
    p.add_argument("--max-refund-rate", type=Decimal, default=Thresholds.max_refund_rate)
    args = p.parse_args(argv)
    t = Thresholds(sales_drop_pct=args.sales_drop, min_roas=args.min_roas,
                   max_refund_rate=args.max_refund_rate)
    try:
        rows = load_metrics(args.metrics)
        inventory = load_inventory(args.inventory)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    kpi = compute_kpis(rows)
    alerts = build_alerts(kpi, inventory, t)
    args.out.mkdir(parents=True, exist_ok=True)
    text = render(kpi, alerts, inventory)
    (args.out / f"briefing-{kpi['date']}.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
