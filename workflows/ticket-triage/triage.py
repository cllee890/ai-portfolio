#!/usr/bin/env python3
"""工单分类与回复草稿（规则版，离线可运行）。

流程：脱敏 → 分类（关键词规则）→ 优先级判定 → 生成回复草稿
所有草稿 status 固定为 pending_review，程序不会自动发送。

用法：python triage.py --input data/tickets.jsonl --out reports
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 分类规则按顺序匹配，先命中的优先
CATEGORY_RULES = [
    ("质量投诉", ["冒烟", "坏了", "损坏", "破损", "质量", "投诉", "起火", "受伤"]),
    ("拒付纠纷", ["拒付", "不符", "起诉", "欺诈"]),
    ("退款售后", ["退款", "退货", "换货", "换成", "换一个", "退钱", "到账"]),
    ("物流查询", ["物流", "没到", "快递", "包裹", "运单", "发货"]),
    ("发票财务", ["发票", "抬头", "税号"]),
    ("合作咨询", ["合作", "推广", "经纪", "KOL", "代言"]),
    ("售前咨询", ["尺码", "颜色", "能不能", "适合", "想问", "换成", "规格"]),
]

HIGH_PRIORITY_WORDS = ["冒烟", "起火", "受伤", "拒付", "起诉", "律师", "投诉"]
TEMPLATES = {
    "质量投诉": "您好，非常抱歉给您带来不好的体验。请您提供商品问题的照片或视频及订单号，我们会优先为您处理。",
    "拒付纠纷": "您好，我们已注意到您的反馈。为了尽快核实，请提供商品照片与订单号，我们将在工作时间内给您答复。",
    "退款售后": "您好，您的退款申请我们已收到，目前状态为审核中，预计 1-3 个工作日完成审核，到账时间以支付渠道为准。",
    "物流查询": "您好，我们正在为您查询订单 {order_id} 的物流信息，稍后会把最新节点同步给您。",
    "发票财务": "您好，电子发票开具后不支持直接修改抬头，我们可以先为您作废后重新开具，请确认新的抬头信息。",
    "合作咨询": "您好，感谢您的合作意向。请您简单说明合作形式与预算，我们的商务同事会与您联系。",
    "售前咨询": "您好，感谢您的咨询。关于您的问题，我们会根据商品信息尽快为您解答，如需进一步确认请告知订单号或商品链接。",
}

PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ORDER = re.compile(r"\bSO\d{4,}\b")


def mask_pii(text: str) -> str:
    text = PHONE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)
    return EMAIL.sub(lambda m: "***@" + m.group(0).split("@", 1)[1], text)


def classify(text: str) -> str:
    for category, words in CATEGORY_RULES:
        if any(w.lower() in text.lower() for w in words):
            return category
    return "其他"


def priority(category: str, text: str) -> str:
    if any(w in text for w in HIGH_PRIORITY_WORDS) or category in ("拒付纠纷",):
        return "高"
    if category in ("退款售后", "物流查询", "质量投诉"):
        return "中"
    return "低"


def triage_ticket(ticket: dict) -> dict:
    raw = f"{ticket.get('subject', '')} {ticket.get('body', '')}"
    if not raw.strip():
        raise ValueError(f"工单 {ticket.get('id')} 内容为空")
    category = classify(raw)
    orders = ORDER.findall(raw)
    order_id = orders[0] if orders else "（未提供）"
    template = TEMPLATES.get(category, "您好，感谢您的留言，我们会尽快与您联系。")
    return {
        "id": ticket["id"],
        "channel": ticket.get("channel", ""),
        "category": category,
        "priority": priority(category, raw),
        "order_ids": orders,
        "needs_human": category in ("质量投诉", "拒付纠纷", "合作咨询") or priority(category, raw) == "高",
        "masked_text": mask_pii(raw),
        "draft_reply": template.format(order_id=order_id),
        "status": "pending_review",
    }


def load_tickets(path: Path) -> list[dict]:
    tickets = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            tickets.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{n} 不是合法 JSON：{exc}") from exc
    return tickets


def summarize(results: list[dict]) -> dict:
    return {
        "total": len(results),
        "by_category": dict(Counter(r["category"] for r in results)),
        "by_priority": dict(Counter(r["priority"] for r in results)),
        "needs_human": sum(r["needs_human"] for r in results),
    }


def write_outputs(out: Path, results: list[dict], summary: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "triage.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lines = ["# 工单分类报告", "", f"- 工单总数：{summary['total']}",
             f"- 需人工介入：{summary['needs_human']}", "", "## 分类分布", "", "| 类别 | 数量 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary["by_category"].items()]
    lines += ["", "## 工单明细", "", "| ID | 渠道 | 类别 | 优先级 | 人工介入 | 脱敏内容 |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['channel']} | {r['category']} | {r['priority']} | "
              f"{'是' if r['needs_human'] else '否'} | {r['masked_text']} |" for r in results]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="工单分类与回复草稿")
    p.add_argument("--input", type=Path, default=HERE / "data" / "tickets.jsonl")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    args = p.parse_args(argv)
    try:
        results = [triage_ticket(t) for t in load_tickets(args.input)]
    except (OSError, ValueError, KeyError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    summary = summarize(results)
    write_outputs(args.out, results, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
