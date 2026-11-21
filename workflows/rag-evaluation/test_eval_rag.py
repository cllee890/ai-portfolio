"""eval_rag.py 的单元测试。

运行：python -m unittest test_eval_rag -v   （或 pytest）
"""
import json
import tempfile
import unittest
from pathlib import Path

import eval_rag as ev

HERE = Path(__file__).resolve().parent


class StubRetriever:
    """按预设结果返回，便于精确验证单条评测逻辑。"""

    def __init__(self, ranked):
        self.ranked = ranked

    def search(self, query, top_k):
        return self.ranked[:top_k]


def chunk(source, text="内容"):
    return ev.Chunk(text, source)


class SplitMarkdownTests(unittest.TestCase):
    def test_splits_on_level_two_headings(self):
        text = "# 标题\n\n## A\n正文A\n\n## B\n正文B\n"
        chunks = ev.split_markdown(text, "d.md")
        self.assertEqual(len(chunks), 3)  # 文档标题前言 + A + B
        self.assertIn("正文A", chunks[1].text)
        self.assertTrue(all(c.source == "d.md" for c in chunks))

    def test_empty_document_yields_no_chunks(self):
        self.assertEqual(ev.split_markdown("   \n", "e.md"), [])


class TokenizeTests(unittest.TestCase):
    def test_cjk_bigrams_and_ascii_words(self):
        tokens = ev.tokenize("退款 Refund")
        self.assertIn("退款", tokens)
        self.assertIn("refund", tokens)

    def test_single_cjk_character_kept(self):
        self.assertEqual(ev.tokenize("吗"), ["吗"])


class LexicalRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.r = ev.LexicalRetriever([
            ev.Chunk("退款政策：签收后7天内可申请退款", "refund.md"),
            ev.Chunk("物流说明：国内仓3-7个工作日送达", "shipping.md"),
        ])

    def test_most_relevant_chunk_ranks_first(self):
        hits = self.r.search("怎么申请退款", top_k=2)
        self.assertEqual(hits[0][0].source, "refund.md")

    def test_scores_sorted_and_bounded(self):
        hits = self.r.search("退款 物流", top_k=2)
        scores = [s for _, s in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 < s <= 1.0 + 1e-9 for s in scores))

    def test_no_overlap_returns_empty(self):
        self.assertEqual(self.r.search("zzzz qqqq", top_k=3), [])

    def test_top_k_limits_results(self):
        self.assertEqual(len(self.r.search("退款 物流", top_k=1)), 1)


class EvaluateItemTests(unittest.TestCase):
    def item(self, **kw):
        base = {"id": "x", "question": "q", "relevant_sources": ["a.md"],
                "keywords": ["关键词"], "should_transfer": False}
        base.update(kw)
        return base

    def test_hit_at_rank_two(self):
        r = StubRetriever([(chunk("b.md"), 0.9), (chunk("a.md", "关键词出现"), 0.8)])
        out = ev.evaluate_item(r, self.item(), top_k=4, threshold=0.1)
        self.assertTrue(out["hit"])
        self.assertFalse(out["hit_at_1"])
        self.assertAlmostEqual(out["rr"], 0.5)
        self.assertEqual(out["keyword_recall"], 1.0)
        self.assertFalse(out["transferred"])

    def test_miss_within_top_k(self):
        r = StubRetriever([(chunk("b.md"), 0.9)])
        out = ev.evaluate_item(r, self.item(), top_k=4, threshold=0.1)
        self.assertFalse(out["hit"])
        self.assertEqual(out["rr"], 0.0)

    def test_all_below_threshold_transfers(self):
        r = StubRetriever([(chunk("a.md"), 0.05)])
        out = ev.evaluate_item(r, self.item(), top_k=4, threshold=0.1)
        self.assertTrue(out["transferred"])
        self.assertIsNone(out["keyword_recall"])

    def test_out_of_scope_item_has_no_retrieval_metrics(self):
        r = StubRetriever([])
        out = ev.evaluate_item(r, self.item(relevant_sources=[], keywords=[], should_transfer=True),
                               top_k=4, threshold=0.1)
        self.assertIsNone(out["hit"])
        self.assertIsNone(out["rr"])
        self.assertTrue(out["transferred"])

    def test_keyword_recall_partial(self):
        r = StubRetriever([(chunk("a.md", "只有第一个词"), 0.9)])
        out = ev.evaluate_item(r, self.item(keywords=["第一个", "不存在"]), top_k=4, threshold=0.1)
        self.assertAlmostEqual(out["keyword_recall"], 0.5)

    def test_keyword_recall_uses_only_chunks_above_threshold(self):
        r = StubRetriever([(chunk("a.md", "无关"), 0.9), (chunk("b.md", "关键词"), 0.01)])
        out = ev.evaluate_item(r, self.item(), top_k=4, threshold=0.1)
        self.assertEqual(out["keyword_recall"], 0.0)


class AggregateTests(unittest.TestCase):
    def results(self):
        return [
            {"should_transfer": False, "transferred": False, "hit": True, "hit_at_1": True,
             "rr": 1.0, "keyword_recall": 1.0},
            {"should_transfer": False, "transferred": False, "hit": True, "hit_at_1": False,
             "rr": 0.5, "keyword_recall": 0.5},
            {"should_transfer": False, "transferred": True, "hit": False, "hit_at_1": False,
             "rr": 0.0, "keyword_recall": None},
            {"should_transfer": True, "transferred": True, "hit": None, "hit_at_1": None,
             "rr": None, "keyword_recall": None},
            {"should_transfer": True, "transferred": False, "hit": None, "hit_at_1": None,
             "rr": None, "keyword_recall": None},
        ]

    def test_metric_formulas(self):
        m = ev.aggregate(self.results())
        self.assertEqual(m["total"], 5)
        self.assertEqual(m["answerable"], 3)
        self.assertEqual(m["should_transfer"], 2)
        self.assertAlmostEqual(m["hit_rate"], 2 / 3, places=4)
        self.assertAlmostEqual(m["hit_at_1"], 1 / 3, places=4)
        self.assertAlmostEqual(m["mrr"], 0.5, places=4)
        self.assertAlmostEqual(m["keyword_recall"], 0.75, places=4)
        self.assertAlmostEqual(m["transfer_accuracy"], 3 / 5, places=4)
        self.assertAlmostEqual(m["false_transfer_rate"], 1 / 3, places=4)
        self.assertAlmostEqual(m["missed_transfer_rate"], 1 / 2, places=4)

    def test_no_answerable_items_yields_none(self):
        m = ev.aggregate([{"should_transfer": True, "transferred": True, "hit": None,
                           "hit_at_1": None, "rr": None, "keyword_recall": None}])
        self.assertIsNone(m["hit_rate"])
        self.assertIsNone(m["false_transfer_rate"])
        self.assertEqual(m["transfer_accuracy"], 1.0)


class CompareTests(unittest.TestCase):
    def test_status_respects_metric_direction(self):
        rows = {r["metric"]: r for r in ev.compare(
            {"hit_rate": 0.9, "missed_transfer_rate": 0.1},
            {"hit_rate": 0.8, "missed_transfer_rate": 0.3})}
        self.assertEqual(rows["hit_rate"]["status"], "提升")
        self.assertEqual(rows["missed_transfer_rate"]["status"], "提升")  # 越低越好

    def test_missing_values_yield_dash(self):
        rows = {r["metric"]: r for r in ev.compare({"hit_rate": None}, {})}
        self.assertEqual(rows["hit_rate"]["status"], "-")
        self.assertIsNone(rows["hit_rate"]["delta"])


class LoadTests(unittest.TestCase):
    def write_tmp(self, lines):
        d = tempfile.mkdtemp()
        p = Path(d) / "t.jsonl"
        p.write_text("\n".join(lines), encoding="utf-8")
        return p

    def base_item(self, **kw):
        item = {"id": "a", "question": "q", "relevant_sources": ["x.md"],
                "keywords": [], "should_transfer": False}
        item.update(kw)
        return json.dumps(item, ensure_ascii=False)

    def test_bad_json_reports_line(self):
        with self.assertRaisesRegex(ValueError, ":2 不是合法 JSON"):
            ev.load_testset(self.write_tmp([self.base_item(), "{oops"]))

    def test_missing_field_rejected(self):
        bad = json.dumps({"id": "a", "question": "q"})
        with self.assertRaisesRegex(ValueError, "缺少字段"):
            ev.load_testset(self.write_tmp([bad]))

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "id 重复"):
            ev.load_testset(self.write_tmp([self.base_item(), self.base_item()]))

    def test_transfer_item_with_sources_rejected(self):
        with self.assertRaisesRegex(ValueError, "不应有 relevant_sources"):
            ev.load_testset(self.write_tmp([self.base_item(should_transfer=True)]))

    def test_empty_testset_rejected(self):
        with self.assertRaisesRegex(ValueError, "测试集为空"):
            ev.load_testset(self.write_tmp(["", "  "]))

    def test_missing_docs_directory_rejected(self):
        with self.assertRaises(FileNotFoundError):
            ev.load_docs(Path(tempfile.mkdtemp()))


class SweepTests(unittest.TestCase):
    def test_higher_threshold_transfers_more(self):
        docs = ev.load_docs(HERE / "data" / "docs")
        items = ev.load_testset(HERE / "data" / "testset.jsonl")
        rows = ev.sweep(ev.LexicalRetriever(docs), items, top_k=4, thresholds=[0.05, 0.3, 0.6])
        missed = [r["missed_transfer_rate"] for r in rows]
        self.assertEqual(missed, sorted(missed, reverse=True))


class EndToEndTests(unittest.TestCase):
    """对随仓库提供的知识库与测试集运行完整流程。"""

    def test_shipped_dataset_meets_baseline_quality(self):
        metrics, results = ev.run(ev.DEFAULT_DOCS, ev.DEFAULT_TESTSET, top_k=4, threshold=0.15)
        self.assertEqual(metrics["total"], 20)
        self.assertGreaterEqual(metrics["hit_rate"], 0.9)
        self.assertGreaterEqual(metrics["transfer_accuracy"], 0.8)
        self.assertEqual(metrics["false_transfer_rate"], 0.0)
        self.assertEqual(len(results), 20)

    def test_cli_writes_reports_and_gate_passes(self):
        out = Path(tempfile.mkdtemp())
        code = ev.main(["--out-dir", str(out), "--min-hit-rate", "0.5"])
        self.assertEqual(code, 0)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertIn("hit_rate", report["metrics"])
        self.assertTrue((out / "report.md").read_text(encoding="utf-8").startswith("# RAG 评测报告"))

    def test_cli_gate_failure_returns_2(self):
        out = Path(tempfile.mkdtemp())
        code = ev.main(["--out-dir", str(out), "--min-hit-rate", "1.01"])
        self.assertEqual(code, 2)

    def test_cli_missing_input_returns_1(self):
        code = ev.main(["--docs", tempfile.mkdtemp(), "--out-dir", tempfile.mkdtemp()])
        self.assertEqual(code, 1)

    def test_cli_baseline_comparison(self):
        out = Path(tempfile.mkdtemp())
        ev.main(["--out-dir", str(out)])
        base = out / "report.json"
        out2 = Path(tempfile.mkdtemp())
        self.assertEqual(ev.main(["--out-dir", str(out2), "--baseline", str(base)]), 0)
        report = json.loads((out2 / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["comparison"]), len(ev.METRIC_LABELS))
        self.assertTrue(all(r["status"] in ("持平", "-") for r in report["comparison"]))


if __name__ == "__main__":
    unittest.main()
