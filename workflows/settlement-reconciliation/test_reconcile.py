"""reconcile.py 的单元测试。运行：python -m unittest test_reconcile -v"""
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import reconcile as rc

D = Decimal


def order(oid="O1", cur="USD", amount="100.00", commission="10.00", refund="0.00"):
    return {oid: {"currency": cur, "order_amount": D(amount), "platform_commission": D(commission),
                  "refund_amount": D(refund), "expected_net": D(amount) - D(commission) - D(refund)}}


def line(oid="O1", sid="S1", cur="USD", net="90.00", refund="0.00"):
    return {"settlement_id": sid, "order_id": oid, "currency": cur,
            "net_amount": D(net), "refund_amount": D(refund)}


class ReconcileTests(unittest.TestCase):
    def kinds(self, orders, settlements, tol=D("0.01")):
        disc, _ = rc.reconcile(orders, settlements, tol)
        return [d["type"] for d in disc], disc

    def test_clean_match_has_no_discrepancy(self):
        kinds, _ = self.kinds(order(), [line()])
        self.assertEqual(kinds, [])

    def test_missing_settlement(self):
        kinds, disc = self.kinds(order(), [])
        self.assertEqual(kinds, ["MISSING_SETTLEMENT"])
        self.assertEqual(disc[0]["expected"], "90.00")

    def test_unknown_order_in_settlement(self):
        kinds, _ = self.kinds(order(), [line(), line(oid="X9", sid="S2")])
        self.assertIn("UNKNOWN_ORDER", kinds)

    def test_duplicate_settlement(self):
        kinds, _ = self.kinds(order(), [line(sid="S1"), line(sid="S2")])
        self.assertIn("DUPLICATE_SETTLEMENT", kinds)

    def test_currency_mismatch_skips_amount_check(self):
        kinds, _ = self.kinds(order(cur="USD"), [line(cur="SGD", net="0.00")])
        self.assertEqual(kinds, ["CURRENCY_MISMATCH"])

    def test_amount_within_tolerance_is_clean(self):
        kinds, _ = self.kinds(order(), [line(net="90.01")])
        self.assertEqual(kinds, [])

    def test_amount_beyond_tolerance_is_flagged(self):
        kinds, disc = self.kinds(order(), [line(net="89.98")])
        self.assertEqual(kinds, ["AMOUNT_MISMATCH"])
        self.assertIn("-0.02", disc[0]["detail"])

    def test_custom_tolerance(self):
        kinds, _ = self.kinds(order(), [line(net="89.00")], tol=D("1.00"))
        self.assertEqual(kinds, [])

    def test_refund_mismatch(self):
        kinds, _ = self.kinds(order(refund="20.00"), [line(net="70.00", refund="0.00")])
        self.assertEqual(kinds, ["REFUND_MISMATCH"])

    def test_decimal_precision_no_float_drift(self):
        # 0.1 + 0.2 类问题：必须按 Decimal 精确比较
        kinds, _ = self.kinds(order(amount="0.30", commission="0.10"), [line(net="0.20")])
        self.assertEqual(kinds, [])

    def test_summary_counts(self):
        orders = {**order("A"), **order("B")}
        disc, summary = rc.reconcile(orders, [line("A", "S1")], D("0.01"))
        self.assertEqual(summary["orders"], 2)
        self.assertEqual(summary["matched_clean"], 1)
        self.assertEqual(summary["by_type"], {"MISSING_SETTLEMENT": 1})


class LoadTests(unittest.TestCase):
    def tmp(self, text):
        p = Path(tempfile.mkdtemp()) / "f.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_invalid_amount_reports_order(self):
        p = self.tmp("order_id,order_date,currency,order_amount,platform_commission,refund_amount\n"
                     "O1,2026-11-01,USD,abc,1.00,0.00\n")
        with self.assertRaisesRegex(ValueError, "O1: 字段 order_amount"):
            rc.load_orders(p)

    def test_duplicate_order_id_in_orders_rejected(self):
        header = "order_id,order_date,currency,order_amount,platform_commission,refund_amount\n"
        p = self.tmp(header + "O1,d,USD,1,0,0\nO1,d,USD,1,0,0\n")
        with self.assertRaisesRegex(ValueError, "重复"):
            rc.load_orders(p)

    def test_load_settlements_parses_decimals(self):
        p = self.tmp("settlement_id,order_id,settle_date,currency,net_amount,refund_amount\n"
                     "S1,O1,d,USD,50.91,0.00\n")
        rows = rc.load_settlements(p)
        self.assertEqual(rows[0]["net_amount"], D("50.91"))


class CliTests(unittest.TestCase):
    def test_bundled_data_produces_expected_discrepancies(self):
        out = Path(tempfile.mkdtemp())
        code = rc.main(["--out", str(out)])
        self.assertEqual(code, 0)
        csv_text = (out / "discrepancies.csv").read_text(encoding="utf-8")
        for kind in ["MISSING_SETTLEMENT", "UNKNOWN_ORDER", "DUPLICATE_SETTLEMENT", "AMOUNT_MISMATCH"]:
            self.assertIn(kind, csv_text)

    def test_strict_mode_returns_2_when_discrepancies(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(rc.main(["--out", str(out), "--strict"]), 2)

    def test_missing_file_returns_1(self):
        self.assertEqual(rc.main(["--orders", "/nonexistent.csv", "--out", tempfile.mkdtemp()]), 1)


if __name__ == "__main__":
    unittest.main()
