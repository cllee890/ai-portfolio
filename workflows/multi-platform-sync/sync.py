#!/usr/bin/env python3
"""多平台商品同步：以 ERP 为主数据，同步价格与库存到平台。

规则
- 标题等文案不同步（平台可自定义）；价格与库存以 ERP 为准。
- 以上次成功同步的基线（sync_state.json）判断谁改过：
  * 平台与 ERP 相同 → NOOP
  * 只有 ERP 变化（或首次同步）→ PUSH
  * 平台被手工修改且 ERP 也变化、两者不一致 → CONFLICT，不自动写入，转人工
  * 平台被手工修改而 ERP 未变 → PUSH（以 ERP 覆盖），并记录 OVERWRITE_PLATFORM_EDIT 供复核
- 平台存在但 ERP 无对应 SKU → ORPHAN_PLATFORM_LISTING，只报告，不删除。
- ERP 有 SKU 但平台没有映射 → UNMAPPED_ERP_SKU，只报告。
- 默认 dry-run；加 --apply 才会调用平台写接口。仅成功写入的 SKU 更新基线。

用法：python sync.py                # 只生成计划
      python sync.py --apply        # 执行并更新基线
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

HERE = Path(__file__).resolve().parent


class PlatformClient(Protocol):
    def update(self, platform_sku: str, price: Decimal, stock: int) -> None: ...


class FilePlatform:
    """离线占位实现：把写入记录到列表中，不访问真实平台。"""

    def __init__(self):
        self.writes: list[tuple[str, Decimal, int]] = []

    def update(self, platform_sku: str, price: Decimal, stock: int) -> None:
        self.writes.append((platform_sku, price, stock))


def _dec(v: str, field: str, key: str) -> Decimal:
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{key}: 字段 {field} 不是数字：{v!r}") from exc


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def norm(rec: dict) -> dict:
    """统一为字符串表示，避免 "120" 与 120、"129" 与 "129.00" 被误判为变化。"""
    price = Decimal(str(rec["price"])).quantize(Decimal("0.01"))
    return {"price": f"{price:.2f}", "stock": str(int(Decimal(str(rec["stock"]))))}


def plan(erp: dict[str, dict], mapping: dict[str, str], platform: dict[str, dict],
         baseline: dict[str, dict]) -> list[dict]:
    """erp: sku → {price, stock}；mapping: sku → platform_sku；platform: platform_sku → {price, stock}。"""
    erp = {k: norm(v) for k, v in erp.items()}
    platform = {k: norm(v) for k, v in platform.items()}
    baseline = {k: norm(v) for k, v in baseline.items()}
    actions = []
    mapped_platform_skus = set()
    for sku, e in sorted(erp.items()):
        psku = mapping.get(sku)
        if not psku or psku not in platform:
            actions.append({"sku": sku, "platform_sku": psku or "", "action": "UNMAPPED_ERP_SKU",
                            "reason": "平台没有对应商品", "price": "", "stock": ""})
            continue
        mapped_platform_skus.add(psku)
        p = platform[psku]
        if e["price"] == p["price"] and e["stock"] == p["stock"]:
            actions.append({"sku": sku, "platform_sku": psku, "action": "NOOP", "reason": "已一致",
                            "price": e["price"], "stock": e["stock"]})
            continue
        base = baseline.get(sku)
        erp_changed = base is None or base["price"] != e["price"] or base["stock"] != e["stock"]
        plat_changed = base is not None and (base["price"] != p["price"] or base["stock"] != p["stock"])
        if base is not None and plat_changed and erp_changed:
            action, reason = "CONFLICT", "平台与 ERP 同时变化，需人工确认"
        elif plat_changed:
            action, reason = "OVERWRITE_PLATFORM_EDIT", "平台被手工修改，以 ERP 覆盖（需复核）"
        else:
            action, reason = "PUSH", "ERP 已变化" if base is not None else "首次同步"
        actions.append({"sku": sku, "platform_sku": psku, "action": action, "reason": reason,
                        "price": e["price"], "stock": e["stock"]})
    for psku in sorted(set(platform) - mapped_platform_skus):
        actions.append({"sku": "", "platform_sku": psku, "action": "ORPHAN_PLATFORM_LISTING",
                        "reason": "平台商品在 ERP 中没有对应 SKU", "price": "", "stock": ""})
    return actions


def apply(actions: list[dict], client: PlatformClient, baseline: dict[str, dict]) -> tuple[dict, list[dict]]:
    errors = []
    new_baseline = dict(baseline)
    for a in actions:
        if a["action"] == "NOOP":
            new_baseline[a["sku"]] = {"price": a["price"], "stock": a["stock"]}  # 一致也要刷新基线
            continue
        if a["action"] not in ("PUSH", "OVERWRITE_PLATFORM_EDIT"):
            continue
        try:
            client.update(a["platform_sku"], Decimal(a["price"]), int(a["stock"]))
        except Exception as exc:  # 单条失败不中断整批
            errors.append({"sku": a["sku"], "error": str(exc)})
            continue
        new_baseline[a["sku"]] = {"price": a["price"], "stock": a["stock"]}
    return new_baseline, errors


def write_report(out: Path, actions: list[dict], errors: list[dict], applied: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for a in actions:
        counts[a["action"]] = counts.get(a["action"], 0) + 1
    lines = ["# 多平台同步计划" + ("（已执行）" if applied else "（dry-run）"), "", "## 统计", ""]
    lines += [f"- {k}：{v}" for k, v in sorted(counts.items())]
    lines += ["", "## 明细", "", "| SKU | 平台SKU | 动作 | 价格 | 库存 | 原因 |", "|---|---|---|---|---|---|"]
    lines += [f"| {a['sku'] or '-'} | {a['platform_sku']} | {a['action']} | {a['price'] or '-'} | "
              f"{a['stock'] or '-'} | {a['reason']} |" for a in actions]
    if errors:
        lines += ["", "## 写入失败", ""] + [f"- {e['sku']}：{e['error']}" for e in errors]
    (out / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="多平台商品同步")
    p.add_argument("--erp", type=Path, default=HERE / "data" / "erp_products.csv")
    p.add_argument("--mapping", type=Path, default=HERE / "data" / "mapping_amazon.csv")
    p.add_argument("--platform", type=Path, default=HERE / "data" / "platform_amazon.csv")
    p.add_argument("--state", type=Path, default=HERE / "data" / "sync_state.json")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    try:
        erp = {r["sku"]: {"price": str(_dec(r["price"], "price", r["sku"])),
                          "stock": str(int(_dec(r["stock"], "stock", r["sku"])))} for r in load_csv(args.erp)}
        mapping = {r["sku"]: r["platform_sku"] for r in load_csv(args.mapping)}
        platform = {r["platform_sku"]: {"price": str(_dec(r["price"], "price", r["platform_sku"])),
                                        "stock": str(int(_dec(r["stock"], "stock", r["platform_sku"])))}
                    for r in load_csv(args.platform)}
        baseline = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
        baseline = {k: norm(v) for k, v in baseline.items()}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    actions = plan(erp, mapping, platform, baseline)
    errors: list[dict] = []
    if args.apply:
        client = FilePlatform()  # 替换为真实平台客户端
        new_baseline, errors = apply(actions, client, baseline)
        args.state.write_text(json.dumps(new_baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.out, actions, errors, args.apply)
    summary = {a["action"] for a in actions}
    print(f"动作类型：{sorted(summary)}；写入失败 {len(errors)} 条；报告：{args.out / 'plan.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
