#!/usr/bin/env python3
"""竞品价格监控：定时抓取、变化检测、告警去重与失败重试。

设计要点
- 抓取器可替换：SnapshotFetcher 读取本地快照（离线演示）；生产环境实现 fetch(sku) 即可接入真实页面或 API。
- 瞬时错误（TransientError）按指数退避重试，重试耗尽记为失败但不中断整批任务。
- 状态文件 state.json 记录上次价格与可售状态，用于判断"变化"，并保证同一变化只告警一次。
- 价格比较使用 Decimal。

用法：python monitor.py --snapshot data/snapshots/2026-11-21.json --state reports/state.json --out reports
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Protocol

HERE = Path(__file__).resolve().parent
PRICE_CHANGE_PCT = Decimal("0.05")   # 价格变动超过 5% 才告警
MAX_ATTEMPTS = 3


class TransientError(Exception):
    """可重试的错误（超时、限流、5xx）。"""


class PermanentError(Exception):
    """不可重试的错误（商品下架、解析失败）。"""


class Fetcher(Protocol):
    def fetch(self, sku: str) -> dict: ...


class SnapshotFetcher:
    """从快照文件读取，便于离线复现。记录中含 error 字段时模拟抓取失败。"""

    def __init__(self, path: Path):
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def fetch(self, sku: str) -> dict:
        rec = self.data.get(sku)
        if rec is None:
            raise PermanentError(f"快照中没有 {sku}")
        if "error" in rec:
            raise TransientError(rec["error"])
        try:
            price = Decimal(rec["price"])
        except (KeyError, InvalidOperation) as exc:
            raise PermanentError(f"{sku} 价格解析失败") from exc
        return {"price": price, "currency": rec.get("currency", ""), "available": bool(rec.get("available", True))}


def fetch_with_retry(fetcher: Fetcher, sku: str, *, attempts: int = MAX_ATTEMPTS,
                     base_delay: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> dict:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fetcher.fetch(sku)
        except TransientError as exc:
            last = exc
            if i < attempts - 1:
                sleep(base_delay * (2 ** i))
        except PermanentError:
            raise
    raise PermanentError(f"重试 {attempts} 次后仍失败：{last}")


def detect_changes(sku: str, old: dict | None, new: dict, pct: Decimal = PRICE_CHANGE_PCT) -> list[dict]:
    if old is None:
        return []   # 首次抓取只建立基线，不告警
    changes = []
    if Decimal(old["price"]) != Decimal(new["price"]) and Decimal(old["price"]) > 0:
        delta = (Decimal(new["price"]) - Decimal(old["price"])) / Decimal(old["price"])
        if abs(delta) >= pct:
            changes.append({"sku": sku, "kind": "PRICE", "from": str(old["price"]), "to": str(new["price"]),
                            "change_pct": f"{delta:+.1%}"})
    if old["available"] != new["available"]:
        changes.append({"sku": sku, "kind": "AVAILABILITY", "from": str(old["available"]),
                        "to": str(new["available"]), "change_pct": ""})
    return changes


def run(watchlist: list[dict], fetcher: Fetcher, state: dict, sleep=time.sleep) -> tuple[list[dict], list[dict], dict]:
    alerts, failures = [], []
    new_state = dict(state)
    for item in watchlist:
        sku = item["sku"]
        try:
            current = fetch_with_retry(fetcher, sku, sleep=sleep)
        except PermanentError as exc:
            failures.append({"sku": sku, "reason": str(exc)})
            continue
        serial = {"price": str(current["price"]), "currency": current["currency"], "available": current["available"]}
        old = state.get(sku)
        changes = detect_changes(sku, old, {"price": str(current["price"]), "available": current["available"]})
        for c in changes:
            c.update({"competitor": item["competitor"], "product": item["product"]})
        alerts.extend(changes)
        new_state[sku] = serial   # 状态只在成功抓取后更新，失败时保留旧基线
    return alerts, failures, new_state


def load_watchlist(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = [{k: v.strip() for k, v in r.items()} for r in csv.DictReader(f)]
    seen = set()
    for r in rows:
        if r["sku"] in seen:
            raise ValueError(f"监控清单中 sku 重复：{r['sku']}")
        seen.add(r["sku"])
    return rows


def write_outputs(out: Path, alerts: list[dict], failures: list[dict], state: dict, snapshot_name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# 竞品价格告警（{snapshot_name}）", "", f"- 告警数：{len(alerts)}", f"- 抓取失败：{len(failures)}", ""]
    lines += ["| SKU | 竞品 | 商品 | 类型 | 变化 |", "|---|---|---|---|---|"]
    for a in alerts:
        change = f"{a['from']} → {a['to']}" + (f"（{a['change_pct']}）" if a["change_pct"] else "")
        lines.append(f"| {a['sku']} | {a['competitor']} | {a['product']} | {a['kind']} | {change} |")
    if not alerts:
        lines.append("| - | - | - | - | 无变化 |")
    if failures:
        lines += ["", "## 抓取失败", ""] + [f"- {f['sku']}：{f['reason']}" for f in failures]
    (out / f"alerts-{snapshot_name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="竞品价格监控")
    p.add_argument("--watchlist", type=Path, default=HERE / "data" / "watchlist.csv")
    p.add_argument("--snapshot", type=Path, required=True, help="离线快照文件（模拟抓取结果）")
    p.add_argument("--state", type=Path, default=HERE / "reports" / "state.json")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    args = p.parse_args(argv)
    try:
        watchlist = load_watchlist(args.watchlist)
        fetcher = SnapshotFetcher(args.snapshot)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    alerts, failures, new_state = run(watchlist, fetcher, state, sleep=lambda s: None)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outputs(args.out, alerts, failures, new_state, args.snapshot.stem)
    print(f"告警 {len(alerts)} 条，失败 {len(failures)} 条；状态已更新：{args.state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
