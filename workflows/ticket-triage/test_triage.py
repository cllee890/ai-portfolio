"""triage.py 的单元测试。运行：python -m unittest test_triage -v"""
import json
import tempfile
import unittest
from pathlib import Path

import triage as tg


def t(subject="", body="", **kw):
    d = {"id": "X", "channel": "email", "subject": subject, "body": body}
    d.update(kw)
    return d


class ClassifyTests(unittest.TestCase):
    def test_categories(self):
        cases = {
            "包裹没到": "物流查询",
            "发票抬头能改吗": "发票财务",
            "要求退款": "退款售后",
            "想换成黑色": "退款售后",
            "尺码适合吗": "售前咨询",
            "我们想谈合作": "合作咨询",
            "东西坏了": "质量投诉",
            "与描述不符要拒付": "拒付纠纷",
            "随便聊聊天气": "其他",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tg.classify(text), expected)

    def test_quality_rule_wins_over_refund(self):
        # 同时包含"冒烟"与"退款"时，质量投诉优先
        self.assertEqual(tg.classify("冒烟了，要退款"), "质量投诉")

    def test_matching_is_case_insensitive_for_kol(self):
        self.assertEqual(tg.classify("我们是 kol 经纪公司"), "合作咨询")


class PriorityTests(unittest.TestCase):
    def test_high_words_raise_priority(self):
        self.assertEqual(tg.priority("质量投诉", "冒烟了"), "高")

    def test_chargeback_category_always_high(self):
        self.assertEqual(tg.priority("拒付纠纷", "随便"), "高")

    def test_refund_is_medium_and_presale_low(self):
        self.assertEqual(tg.priority("退款售后", "退款"), "中")
        self.assertEqual(tg.priority("售前咨询", "尺码"), "低")


class PrivacyTests(unittest.TestCase):
    def test_phone_is_masked(self):
        self.assertEqual(tg.mask_pii("电话 13800138000 请联系"), "电话 138****8000 请联系")

    def test_email_local_part_is_masked(self):
        self.assertEqual(tg.mask_pii("mail a.b@shop.com"), "mail ***@shop.com")

    def test_masked_text_in_output_has_no_raw_contact(self):
        r = tg.triage_ticket(t(body="手机 13900001111 邮箱 x@y.com"))
        self.assertNotIn("13900001111", r["masked_text"])
        self.assertNotIn("x@y.com", r["masked_text"])


class TriageTicketTests(unittest.TestCase):
    def test_draft_contains_detected_order_id(self):
        r = tg.triage_ticket(t(body="订单 SO1003 没到"))
        self.assertEqual(r["order_ids"], ["SO1003"])
        self.assertIn("SO1003", r["draft_reply"])

    def test_missing_order_id_uses_placeholder(self):
        r = tg.triage_ticket(t(body="包裹没到"))
        self.assertIn("（未提供）", r["draft_reply"])

    def test_always_pending_review(self):
        self.assertEqual(tg.triage_ticket(t(body="退款"))["status"], "pending_review")

    def test_human_required_for_complaints(self):
        self.assertTrue(tg.triage_ticket(t(body="我要投诉"))["needs_human"])
        self.assertFalse(tg.triage_ticket(t(body="尺码多少"))["needs_human"])

    def test_empty_ticket_rejected(self):
        with self.assertRaises(ValueError):
            tg.triage_ticket({"id": "E1", "subject": "", "body": "  "})


class CliTests(unittest.TestCase):
    def test_invalid_json_line_reported(self):
        p = Path(tempfile.mkdtemp()) / "t.jsonl"
        p.write_text('{"id":"a","body":"ok"}\n{bad\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, ":2 不是合法 JSON"):
            tg.load_tickets(p)

    def test_bundled_run_writes_outputs(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(tg.main(["--out", str(out)]), 0)
        lines = (out / "triage.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 8)
        self.assertTrue(all(json.loads(l)["status"] == "pending_review" for l in lines))


if __name__ == "__main__":
    unittest.main()
