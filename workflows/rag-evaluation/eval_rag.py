#!/usr/bin/env python3
"""RAG 离线评测流水线（纯标准库，无需 API Key）。

流程：加载知识库文档 → 按标题切分为块 → 建立检索索引 → 逐条运行测试集
    → 计算检索指标、转人工指标、答案依据覆盖率 → 输出 JSON 与 Markdown 报告。

用法：
    python eval_rag.py                                  # 使用默认数据与参数
    python eval_rag.py --top-k 4 --threshold 0.15
    python eval_rag.py --baseline reports/baseline.json # 与历史结果对比
    python eval_rag.py --min-hit-rate 0.8               # 低于阈值则以退出码 2 失败（可用于 CI）

说明：
- 默认检索器为字符二元组 TF-IDF，便于离线复现。接入真实系统时，实现同样的
  `search(query, top_k) -> list[(Chunk, score)]` 接口即可替换（见 README）。
- 本脚本评测的是"检索 + 阈值转人工"这一规则，不评测大模型生成质量。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

HERE = Path(__file__).resolve().parent
DEFAULT_DOCS = HERE / "data" / "docs"
DEFAULT_TESTSET = HERE / "data" / "testset.jsonl"
DEFAULT_OUT = HERE / "reports"

REQUIRED_FIELDS = {"id", "question", "relevant_sources", "keywords", "should_transfer"}


# ---------------------------------------------------------------------------
# 数据结构与加载
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Chunk:
    text: str
    source: str


class Retriever(Protocol):
    def search(self, query: str, top_k: int) -> list[tuple[Chunk, float]]: ...


def split_markdown(text: str, source: str) -> list[Chunk]:
    """按二级标题切分；每个块保留标题，便于检索与引用。"""
    chunks: list[Chunk] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunks.append(Chunk("\n".join(current).strip(), source))
            current = []
        current.append(line)
    if current:
        chunks.append(Chunk("\n".join(current).strip(), source))
    return [c for c in chunks if c.text]


def load_docs(doc_dir: Path) -> list[Chunk]:
    files = sorted(doc_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"知识库目录中没有 .md 文件：{doc_dir}")
    chunks: list[Chunk] = []
    for path in files:
        chunks.extend(split_markdown(path.read_text(encoding="utf-8"), path.name))
    return chunks


def load_testset(path: Path) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} 不是合法 JSON：{exc}") from exc
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ValueError(f"{path}:{lineno} 缺少字段：{sorted(missing)}")
        if item["id"] in seen:
            raise ValueError(f"{path}:{lineno} 样本 id 重复：{item['id']}")
        if item["should_transfer"] and item["relevant_sources"]:
            raise ValueError(f"{path}:{lineno} 应转人工的样本不应有 relevant_sources")
        seen.add(item["id"])
        items.append(item)
    if not items:
        raise ValueError(f"测试集为空：{path}")
    return items


# ---------------------------------------------------------------------------
# 默认检索器：字符二元组 TF-IDF + 余弦相似度（纯标准库）
# ---------------------------------------------------------------------------
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = _WORD.findall(text)
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


class LexicalRetriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._tf = [Counter(tokenize(c.text)) for c in chunks]
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}
        self._vecs = [self._weight(tf) for tf in self._tf]
        self._norms = [math.sqrt(sum(w * w for w in v.values())) or 1.0 for v in self._vecs]

    def _weight(self, tf: Counter) -> dict[str, float]:
        return {t: c * self._idf.get(t, 0.0) for t, c in tf.items()}

    def search(self, query: str, top_k: int) -> list[tuple[Chunk, float]]:
        q = self._weight(Counter(tokenize(query)))
        qn = math.sqrt(sum(w * w for w in q.values())) or 1.0
        scored = []
        for i, vec in enumerate(self._vecs):
            dot = sum(w * vec.get(t, 0.0) for t, w in q.items())
            scored.append((dot / (qn * self._norms[i]), i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(self.chunks[i], round(s, 4)) for s, i in scored[:top_k] if s > 0]


# ---------------------------------------------------------------------------
# 评测
# ---------------------------------------------------------------------------
def evaluate_item(retriever: Retriever, item: dict, top_k: int, threshold: float) -> dict:
    ranked = retriever.search(item["question"], top_k)  # 排序结果，用于检索指标
    relevant = set(item["relevant_sources"])

    # 检索指标：排名前 k 中是否命中相关文档，以及第一个命中的排名
    rank = next((r for r, (c, _) in enumerate(ranked, 1) if c.source in relevant), None)
    hit = rank is not None if relevant else None
    rr = (1.0 / rank if rank else 0.0) if relevant else None

    # 转人工规则：没有任何块达到阈值则转人工
    passing = [(c, s) for c, s in ranked if s >= threshold]
    transferred = not passing

    # 答案依据覆盖率：关键词在"通过阈值的上下文"中出现的比例（仅对可回答样本计算）
    keyword_recall = None
    if not item["should_transfer"] and not transferred and item["keywords"]:
        context = "\n".join(c.text for c, _ in passing)
        found = [k for k in item["keywords"] if k in context]
        keyword_recall = len(found) / len(item["keywords"])

    return {
        "id": item["id"],
        "question": item["question"],
        "should_transfer": item["should_transfer"],
        "transferred": transferred,
        "top_sources": [c.source for c, _ in ranked],
        "top_scores": [s for _, s in ranked],
        "hit": hit,
        "hit_at_1": (rank == 1) if relevant else None,
        "rr": rr,
        "keyword_recall": keyword_recall,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def aggregate(results: list[dict]) -> dict:
    answerable = [r for r in results if not r["should_transfer"]]
    should = [r for r in results if r["should_transfer"]]
    hits = [r["hit"] for r in answerable if r["hit"] is not None]
    hits1 = [r["hit_at_1"] for r in answerable if r["hit_at_1"] is not None]
    false_transfer = [r for r in answerable if r["transferred"]]
    missed_transfer = [r for r in should if not r["transferred"]]
    return {
        "total": len(results),
        "answerable": len(answerable),
        "should_transfer": len(should),
        "hit_rate": _mean([float(h) for h in hits]),
        "hit_at_1": _mean([float(h) for h in hits1]),
        "mrr": _mean([r["rr"] for r in answerable]),
        "keyword_recall": _mean([r["keyword_recall"] for r in answerable if r["keyword_recall"] is not None]),
        "transfer_accuracy": _mean([float(r["transferred"] == r["should_transfer"]) for r in results]),
        "false_transfer_rate": round(len(false_transfer) / len(answerable), 4) if answerable else None,
        "missed_transfer_rate": round(len(missed_transfer) / len(should), 4) if should else None,
    }


METRIC_LABELS = {
    "hit_rate": "检索命中率 (Hit@k)",
    "hit_at_1": "Top-1 命中率 (Hit@1)",
    "mrr": "平均倒数排名 (MRR)",
    "keyword_recall": "依据关键词覆盖率",
    "transfer_accuracy": "转人工判断准确率",
    "false_transfer_rate": "误转人工率（可回答却转人工）",
    "missed_transfer_rate": "漏转人工率（应转却回答）",
}
HIGHER_IS_BETTER = {"hit_rate", "hit_at_1", "mrr", "keyword_recall", "transfer_accuracy"}
PERCENT_METRICS = {"hit_rate", "hit_at_1", "keyword_recall", "transfer_accuracy",
                   "false_transfer_rate", "missed_transfer_rate"}


def _fmt(key: str, val) -> str:
    if val is None:
        return "-"
    return f"{val:.2%}" if key in PERCENT_METRICS else f"{val:.4f}"


def compare(current: dict, baseline: dict) -> list[dict]:
    rows = []
    for key in METRIC_LABELS:
        cur, base = current.get(key), baseline.get(key)
        delta = None if cur is None or base is None else round(cur - base, 4)
        if delta is None:
            status = "-"
        elif delta == 0:
            status = "持平"
        else:
            better = (delta > 0) == (key in HIGHER_IS_BETTER)
            status = "提升" if better else "下降"
        rows.append({"metric": key, "baseline": base, "current": cur, "delta": delta, "status": status})
    return rows


def sweep(retriever: Retriever, items: list[dict], top_k: int, thresholds: list[float]) -> list[dict]:
    """对多个阈值分别评测，观察"命中"与"转人工"之间的取舍。"""
    rows = []
    for t in thresholds:
        m = aggregate([evaluate_item(retriever, it, top_k, t) for it in items])
        rows.append({"threshold": t, "transfer_accuracy": m["transfer_accuracy"],
                     "false_transfer_rate": m["false_transfer_rate"],
                     "missed_transfer_rate": m["missed_transfer_rate"], "hit_rate": m["hit_rate"]})
    return rows


def sweep_markdown(rows: list[dict]) -> list[str]:
    lines = ["", "## 阈值扫描", "", "| 阈值 | 转人工准确率 | 误转率 | 漏转率 | Hit@k |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['threshold']:.2f} | {_fmt('transfer_accuracy', r['transfer_accuracy'])} | "
                     f"{_fmt('false_transfer_rate', r['false_transfer_rate'])} | "
                     f"{_fmt('missed_transfer_rate', r['missed_transfer_rate'])} | {_fmt('hit_rate', r['hit_rate'])} |")
    return lines


def to_markdown(config: dict, metrics: dict, results: list[dict], comparison: list[dict] | None,
                sweep_rows: list[dict] | None = None) -> str:
    lines = ["# RAG 评测报告", "", "## 运行配置", ""]
    lines += [f"- {k}：`{v}`" for k, v in config.items()]
    lines += ["", "## 总体指标", "", "| 指标 | 数值 |", "|---|---|"]
    for key, label in METRIC_LABELS.items():
        lines.append(f"| {label} | {_fmt(key, metrics.get(key))} |")
    if comparison:
        lines += ["", "## 与基线对比", "", "| 指标 | 基线 | 当前 | 变化 | 状态 |", "|---|---|---|---|---|"]
        for row in comparison:
            label = METRIC_LABELS[row["metric"]]
            key = row["metric"]
            delta = "-" if row["delta"] is None else f"{row['delta']:+.4f}"
            lines.append(f"| {label} | {_fmt(key, row['baseline'])} | {_fmt(key, row['current'])} | {delta} | {row['status']} |")
    if sweep_rows:
        lines += sweep_markdown(sweep_rows)
    lines += ["", "## 逐条结果", "", "| 样本 | 问题 | 期望转人工 | 实际转人工 | Top-1 来源 | 命中 | 关键词覆盖 |", "|---|---|---|---|---|---|---|"]
    for r in results:
        top1 = r["top_sources"][0] if r["top_sources"] else "-"
        hit = "-" if r["hit"] is None else ("✔" if r["hit"] else "✘")
        kw = "-" if r["keyword_recall"] is None else f"{r['keyword_recall']:.0%}"
        lines.append(f"| {r['id']} | {r['question']} | {'是' if r['should_transfer'] else '否'} | "
                     f"{'是' if r['transferred'] else '否'} | {top1} | {hit} | {kw} |")
    return "\n".join(lines) + "\n"


def run(docs: Path, testset: Path, top_k: int, threshold: float) -> tuple[dict, list[dict]]:
    chunks = load_docs(docs)
    items = load_testset(testset)
    retriever = LexicalRetriever(chunks)
    results = [evaluate_item(retriever, it, top_k, threshold) for it in items]
    return aggregate(results), results


def _rel(path: Path) -> str:
    """报告中展示相对于本目录的路径，避免泄露本机绝对路径。"""
    try:
        return str(path.resolve().relative_to(HERE))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RAG 离线评测流水线")
    p.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    p.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--threshold", type=float, default=0.15)
    p.add_argument("--baseline", type=Path, help="历史 report.json，用于生成对比")
    p.add_argument("--sweep", type=str, help="逗号分隔的阈值列表，例如 0.1,0.15,0.2")
    p.add_argument("--min-hit-rate", type=float, help="Hit@k 低于该值则失败")
    p.add_argument("--min-transfer-accuracy", type=float, help="转人工准确率低于该值则失败")
    args = p.parse_args(argv)

    try:
        metrics, results = run(args.docs, args.testset, args.top_k, args.threshold)
    except (OSError, ValueError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    sweep_rows = None
    if args.sweep:
        thresholds = [float(x) for x in args.sweep.split(",") if x.strip()]
        sweep_rows = sweep(LexicalRetriever(load_docs(args.docs)), load_testset(args.testset),
                           args.top_k, thresholds)

    comparison = None
    if args.baseline:
        base = json.loads(args.baseline.read_text(encoding="utf-8"))["metrics"]
        comparison = compare(metrics, base)

    config = {"docs": _rel(args.docs), "testset": _rel(args.testset),
              "top_k": args.top_k, "threshold": args.threshold, "retriever": "lexical-tfidf-bigram"}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {"config": config, "metrics": metrics, "results": results,
              "comparison": comparison, "sweep": sweep_rows}
    (args.out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "report.md").write_text(
        to_markdown(config, metrics, results, comparison, sweep_rows), encoding="utf-8")

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"报告已写入：{args.out_dir / 'report.md'}")

    failures = []
    if args.min_hit_rate is not None and (metrics["hit_rate"] or 0) < args.min_hit_rate:
        failures.append(f"hit_rate {metrics['hit_rate']} < {args.min_hit_rate}")
    if args.min_transfer_accuracy is not None and (metrics["transfer_accuracy"] or 0) < args.min_transfer_accuracy:
        failures.append(f"transfer_accuracy {metrics['transfer_accuracy']} < {args.min_transfer_accuracy}")
    if failures:
        print("[未通过] " + "；".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
