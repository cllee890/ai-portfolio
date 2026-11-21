#!/usr/bin/env python3
"""内容生产流水线：选题 → 脚本 → 配图提示词 → 文案 → 排期。

设计要点
- 每个阶段产物写入 reports/<sku>/<stage>.json，并记录输入哈希。输入未变则复用缓存，支持断点续跑。
- 闸口：标记为 review 的阶段必须在 review_approvals.json 中获批，否则流水线停在该阶段，不执行后续步骤。
- 合规检查：文案与脚本中出现违禁表述（绝对化用语、功效宣称）时阻断，并给出命中词。
- 默认生成器为离线模板，便于复现；接入大模型时替换 GENERATORS 中对应函数即可。

用法：python pipeline.py --product data/product.json --approvals data/review_approvals.json --out reports
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ["topic", "script", "image_prompt", "caption", "schedule"]
REVIEW_STAGES = {"topic", "script", "caption"}
FORBIDDEN = ["最好", "第一", "100%", "永久", "根治", "包治", "立竿见影", "绝对"]


class ComplianceError(Exception):
    pass


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def gen_topic(p: dict) -> dict:
    sp = p["selling_points"]
    return {"angles": [
        f"{p['name']}实测：{sp[0]}",
        f"{p['audience']}为什么都在换{p['name']}",
        f"{p['name']}{sp[-1]}，值不值？",
    ]}


def gen_script(p: dict, topic: dict) -> dict:
    scenes = [{"t": "0-3s", "visual": "夜间书桌，键盘在暗光中", "subtitle": topic["angles"][0]}]
    for i, point in enumerate(p["selling_points"], 1):
        scenes.append({"t": f"{3 * i}-{3 * i + 4}s", "visual": f"特写：{point}", "subtitle": point})
    scenes.append({"t": f"{3 * len(p['selling_points']) + 3}s起", "visual": "价格与活动信息",
                   "subtitle": f"{p['price']} {p['currency']}，{p['promo']}"})
    return {"scenes": scenes}


def gen_image_prompt(p: dict) -> dict:
    return {"prompts": [
        f"{p['name']}产品主图，纯白背景，柔和棚拍光，突出键帽细节",
        f"{p['audience']}的办公桌场景，{p['name']}在台灯下，温暖色调",
    ]}


def gen_caption(p: dict, topic: dict) -> dict:
    return {"title": topic["angles"][1][:40],
            "body": f"{p['name']}：{'；'.join(p['selling_points'])}。{p['promo']}。",
            "hashtags": ["#键盘", "#居家办公", f"#{p['sku'].lower()}"]}


def gen_schedule(start: date, every_days: int = 2, count: int = 3) -> dict:
    return {"slots": [(start + timedelta(days=i * every_days)).isoformat() for i in range(count)]}


def check_compliance(texts: list[str]) -> list[str]:
    hits = sorted({w for t in texts for w in FORBIDDEN if w in t})
    return hits


def _texts_of(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in _texts_of(v)]
    if isinstance(obj, list):
        return [t for v in obj for t in _texts_of(v)]
    return []


def run_stage(stage: str, out_dir: Path, digest: str, make) -> dict:
    cache = out_dir / f"{stage}.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("input_hash") == digest:
            return {**cached, "from_cache": True}
    output = make()
    record = {"stage": stage, "input_hash": digest, "output": output}
    cache.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**record, "from_cache": False}


COMPLIANCE_STAGES = {"script", "caption"}


def run_pipeline(product: dict, out_dir: Path, approvals: dict, start: date = date(2026, 11, 23)) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {"sku": product["sku"], "stages": {}, "status": "running"}
    outputs: dict = {}

    def stage(name, digest, make):
        """返回产物；若被阻断或等待审核则返回 None 并更新 state。"""
        rec = run_stage(name, out_dir, digest, make)
        info = {"from_cache": rec["from_cache"], "status": "done"}
        state["stages"][name] = info
        if name in COMPLIANCE_STAGES:
            bad = check_compliance(_texts_of(rec["output"]))
            if bad:
                info["status"] = "blocked"
                state["status"] = f"compliance_block:{name}:{','.join(bad)}"
                return None
        if name in REVIEW_STAGES and not approvals.get(name):
            info["status"] = "awaiting_review"
            state["status"] = f"waiting_for_review:{name}"
            return None
        outputs[name] = rec["output"]
        return rec["output"]

    topic = stage("topic", _hash(product), lambda: gen_topic(product))
    if topic is None:
        return state
    if stage("script", _hash([product, topic]), lambda: gen_script(product, topic)) is None:
        return state
    if stage("image_prompt", _hash(product), lambda: gen_image_prompt(product)) is None:
        return state
    if stage("caption", _hash([product, topic]), lambda: gen_caption(product, topic)) is None:
        return state
    if stage("schedule", _hash(start.isoformat()), lambda: gen_schedule(start)) is None:
        return state
    state["status"] = "complete"
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="内容生产流水线")
    p.add_argument("--product", type=Path, default=HERE / "data" / "product.json")
    p.add_argument("--approvals", type=Path, default=HERE / "data" / "review_approvals.json")
    p.add_argument("--out", type=Path, default=HERE / "reports")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 11, 23))
    args = p.parse_args(argv)
    try:
        product = json.loads(args.product.read_text(encoding="utf-8"))
        approvals = json.loads(args.approvals.read_text(encoding="utf-8")) if args.approvals.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    state = run_pipeline(product, args.out / product["sku"], approvals, args.start)
    (args.out / product["sku"] / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state["status"] == "complete" else 2


if __name__ == "__main__":
    sys.exit(main())
