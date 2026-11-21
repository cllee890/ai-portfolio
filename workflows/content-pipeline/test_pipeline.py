"""pipeline.py 的单元测试。运行：python -m unittest test_pipeline -v"""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pipeline as pl

PRODUCT = json.loads((pl.HERE / "data" / "product.json").read_text(encoding="utf-8"))


def tmpdir():
    return Path(tempfile.mkdtemp())


class GeneratorTests(unittest.TestCase):
    def test_topic_has_three_angles_using_product_name(self):
        t = pl.gen_topic(PRODUCT)
        self.assertEqual(len(t["angles"]), 3)
        self.assertTrue(all(PRODUCT["name"] in a for a in t["angles"][:1]))

    def test_script_has_scene_per_selling_point_plus_cta(self):
        s = pl.gen_script(PRODUCT, pl.gen_topic(PRODUCT))
        self.assertEqual(len(s["scenes"]), len(PRODUCT["selling_points"]) + 2)

    def test_caption_title_within_40_chars(self):
        c = pl.gen_caption(PRODUCT, pl.gen_topic(PRODUCT))
        self.assertLessEqual(len(c["title"]), 40)

    def test_schedule_spacing(self):
        s = pl.gen_schedule(date(2026, 11, 1), every_days=2, count=3)
        self.assertEqual(s["slots"], ["2026-11-01", "2026-11-03", "2026-11-05"])


class ComplianceTests(unittest.TestCase):
    def test_forbidden_words_detected(self):
        self.assertEqual(pl.check_compliance(["全网最好，100%有效"]), ["100%", "最好"])

    def test_clean_text_passes(self):
        self.assertEqual(pl.check_compliance(["静音按键，夜间打字不扰民"]), [])

    def test_texts_walk_nested_structures(self):
        texts = pl._texts_of({"a": ["x", {"b": "y"}], "c": 1})
        self.assertEqual(sorted(texts), ["x", "y"])


class CacheTests(unittest.TestCase):
    def test_second_run_reuses_cache_when_input_unchanged(self):
        out = tmpdir()
        pl.run_pipeline(PRODUCT, out, {"topic": True, "script": True, "caption": True})
        state = pl.run_pipeline(PRODUCT, out, {"topic": True, "script": True, "caption": True})
        self.assertTrue(all(v["from_cache"] for k, v in state["stages"].items() if k != "schedule"))

    def test_changed_input_invalidates_cache(self):
        out = tmpdir()
        pl.run_pipeline(PRODUCT, out, {"topic": True, "script": True, "caption": True})
        changed = copy.deepcopy(PRODUCT)
        changed["name"] = "新名称"
        state = pl.run_pipeline(changed, out, {"topic": True, "script": True, "caption": True})
        self.assertFalse(state["stages"]["topic"]["from_cache"])


class GateTests(unittest.TestCase):
    def test_stops_at_unapproved_review_stage(self):
        state = pl.run_pipeline(PRODUCT, tmpdir(), {"topic": True})
        self.assertEqual(state["status"], "waiting_for_review:script")
        self.assertNotIn("caption", state["stages"])

    def test_completes_when_all_reviews_approved(self):
        state = pl.run_pipeline(PRODUCT, tmpdir(), {"topic": True, "script": True, "caption": True})
        self.assertEqual(state["status"], "complete")
        self.assertIn("schedule", state["stages"])

    def test_compliance_blocks_before_review(self):
        bad = copy.deepcopy(PRODUCT)
        bad["selling_points"][0] = "全网最好的键盘"
        state = pl.run_pipeline(bad, tmpdir(), {"topic": True, "script": True, "caption": True})
        self.assertTrue(state["status"].startswith("compliance_block:script:"))
        self.assertEqual(state["stages"]["script"]["status"], "blocked")
        self.assertNotIn("image_prompt", state["stages"])


class CliTests(unittest.TestCase):
    def test_default_run_waits_for_caption_review(self):
        out = tmpdir()
        code = pl.main(["--out", str(out)])
        self.assertEqual(code, 2)
        state = json.loads((out / "KB-1024" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "waiting_for_review:caption")

    def test_missing_product_file_returns_1(self):
        self.assertEqual(pl.main(["--product", "/nope.json", "--out", str(tmpdir())]), 1)


if __name__ == "__main__":
    unittest.main()
