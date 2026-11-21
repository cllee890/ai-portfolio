"""extract.py 的单元测试。运行：python -m unittest test_extract -v"""
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import extract as ex

INVOICE = """电子发票
发票号码：123
开票日期：2026年11月03日
购买方名称：甲公司
销售方名称：乙公司
币种：CNY
金额合计：1,000.00
税额：130.00
价税合计：1,130.00
"""


class ParseTests(unittest.TestCase):
    def test_date_formats(self):
        self.assertEqual(ex._parse_date("2026年11月03日"), "2026-11-03")
        self.assertEqual(ex._parse_date("2026-1-5"), "2026-01-05")
        self.assertEqual(ex._parse_date("2026/11/3"), "2026-11-03")

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            ex._parse_date("2026年02月30日")

    def test_unrecognised_date_rejected(self):
        with self.assertRaisesRegex(ValueError, "无法识别"):
            ex._parse_date("下周三")

    def test_amount_with_thousand_separator_and_currency_words(self):
        self.assertEqual(ex._parse_amount("人民币 120,000.50 元"), Decimal("120000.50"))

    def test_invalid_amount_recorded_as_error(self):
        data, errors = ex.extract_fields("金额合计：abc\n")
        self.assertNotIn("subtotal", data)
        self.assertTrue(any("subtotal 解析失败" in e for e in errors))

    def test_label_must_start_line(self):
        # "价税合计" 不应被 "金额合计" 之类的标签误匹配
        self.assertIsNone(ex._find_value("备注 金额合计：5", ["金额合计"]))


class ExtractTests(unittest.TestCase):
    def test_invoice_fields_extracted(self):
        data, errors = ex.extract_fields(INVOICE)
        self.assertEqual(errors, [])
        self.assertEqual(data["invoice_date"], "2026-11-03")
        self.assertEqual(data["total_amount"], "1130.00")
        self.assertEqual(data["buyer_name"], "甲公司")

    def test_contract_label_aliases(self):
        data, _ = ex.extract_fields("合同编号：HT-1\n签订日期：2026年1月2日\n甲方（买方）：甲\n"
                                    "乙方（卖方）：乙\n合同金额：人民币 9.00 元\n")
        self.assertEqual(data["contract_no"], "HT-1")
        self.assertEqual(data["buyer_name"], "甲")
        self.assertEqual(data["total_amount"], "9.00")


class ValidateTests(unittest.TestCase):
    def full(self, **over):
        d = {"invoice_no": "1", "invoice_date": "2026-01-01", "buyer_name": "a", "seller_name": "b",
             "subtotal": "100.00", "tax_amount": "13.00", "total_amount": "113.00"}
        d.update(over)
        return d

    def test_valid_document_has_no_problems(self):
        self.assertEqual(ex.validate(self.full()), [])

    def test_missing_required_field(self):
        d = self.full()
        del d["buyer_name"]
        self.assertIn("缺少必填字段：buyer_name", ex.validate(d))

    def test_tax_arithmetic_within_tolerance_passes(self):
        self.assertEqual(ex.validate(self.full(total_amount="113.01")), [])

    def test_tax_arithmetic_mismatch_flagged(self):
        probs = ex.validate(self.full(total_amount="120.00"))
        self.assertTrue(any("金额勾稽失败" in p for p in probs))

    def test_contract_does_not_require_invoice_fields(self):
        probs = ex.validate({"contract_no": "C", "sign_date": "2026-01-01", "buyer_name": "a",
                             "seller_name": "b", "total_amount": "1.00"}, [], "contract")
        self.assertEqual(probs, [])

    def test_parse_errors_are_carried_into_problems(self):
        self.assertIn("boom", ex.validate(self.full(), ["boom"]))


class CliTests(unittest.TestCase):
    def test_process_routes_contract_and_invoice(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.txt").write_text(INVOICE, encoding="utf-8")
        (d / "b.txt").write_text("合同编号：C1\n签订日期：2026年1月1日\n甲方（买方）：甲\n乙方（卖方）：乙\n"
                                 "合同金额：1.00\n", encoding="utf-8")
        out = Path(tempfile.mkdtemp())
        self.assertEqual(ex.main(["--docs", str(d), "--out", str(out)]), 0)
        results = json.loads((out / "extracted.json").read_text(encoding="utf-8"))
        types = {r["file"]: r["doc_type"] for r in results}
        self.assertEqual(types, {"a.txt": "invoice", "b.txt": "contract"})
        self.assertEqual(json.loads((out / "review_queue.json").read_text(encoding="utf-8")), [])

    def test_empty_directory_returns_1(self):
        self.assertEqual(ex.main(["--docs", tempfile.mkdtemp(), "--out", tempfile.mkdtemp()]), 1)


if __name__ == "__main__":
    unittest.main()
