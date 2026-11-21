"""briefing.py 的单元测试。运行：python -m unittest test_briefing -v"""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

import briefing as bf


def row(day, sales="1000", orders=10, ad="100", refund="0"):
    return {"date": day, "sales": D(sales), "orders": orders, "ad_spend": D(ad), "refund_amount": D(refund)}


def series(sales_list, ad="100"):
    return [row(f"2026-11-{i + 1:02d}", s, ad=ad) for i, s in enumerate(sales_list)]


class KpiTests(unittest.TestCase):
    def test_dod_and_7day_average(self):
        rows = series(["1000"] * 7 + ["800"])
        k = bf.compute_kpis(rows)
        self.assertEqual(k["window_days"], 7)
        self.assertAlmostEqual(float(k["sales_dod_pct"]), -0.2)
        self.assertAlmostEqual(float(k["sales_vs_7d_pct"]), -0.2)

    def test_window_excludes_today(self):
        rows = series(["1000"] * 7 + ["5000"])
        self.assertEqual(bf.compute_kpis(rows)["sales_vs_7d_pct"], D(4))

    def test_short_history_uses_available_days(self):
        k = bf.compute_kpis(series(["1000", "1100"]))
        self.assertEqual(k["window_days"], 1)

    def test_roas_and_refund_rate(self):
        rows = series(["1000"] * 2)
        rows[-1] = row("2026-11-02", "1000", ad="250", refund="50")
        k = bf.compute_kpis(rows)
        self.assertEqual(k["roas"], D(4))
        self.assertEqual(k["refund_rate"], D("0.05"))

    def test_zero_ad_spend_gives_no_roas(self):
        rows = series(["1000"] * 2, ad="0")
        self.assertIsNone(bf.compute_kpis(rows)["roas"])

    def test_zero_sales_refund_rate_is_zero(self):
        rows = series(["1000"] * 2)
        rows[-1]["sales"] = D(0)
        self.assertEqual(bf.compute_kpis(rows)["refund_rate"], 0)


class AlertTests(unittest.TestCase):
    def base_kpi(self, **over):
        k = {"date": "2026-11-21", "window_days": 7, "sales_vs_7d_pct": D("0"),
             "roas": D("3"), "refund_rate": D("0.01")}
        k.update(over)
        return k

    def test_no_alerts_when_healthy(self):
        self.assertEqual(bf.build_alerts(self.base_kpi(), [], bf.Thresholds()), [])

    def test_sales_drop_alert(self):
        alerts = bf.build_alerts(self.base_kpi(sales_vs_7d_pct=D("-0.25")), [], bf.Thresholds())
        self.assertTrue(any("下降 25.0%" in a for a in alerts))

    def test_drop_exactly_at_threshold_is_not_alert(self):
        alerts = bf.build_alerts(self.base_kpi(sales_vs_7d_pct=D("-0.20")), [], bf.Thresholds())
        self.assertEqual(alerts, [])

    def test_low_roas_alert(self):
        alerts = bf.build_alerts(self.base_kpi(roas=D("1.5")), [], bf.Thresholds())
        self.assertTrue(any("广告回报率" in a for a in alerts))

    def test_none_roas_does_not_alert(self):
        self.assertEqual(bf.build_alerts(self.base_kpi(roas=None), [], bf.Thresholds()), [])

    def test_refund_rate_alert(self):
        alerts = bf.build_alerts(self.base_kpi(refund_rate=D("0.15")), [], bf.Thresholds())
        self.assertTrue(any("退款率" in a for a in alerts))

    def test_inventory_cover_below_lead_time(self):
        inv = [{"sku": "A", "product": "a", "stock": 20, "avg_daily_units": D(2), "lead_time_days": 14}]
        alerts = bf.build_alerts(self.base_kpi(), inv, bf.Thresholds())
        self.assertTrue(any("A" in a and "补货周期 14" in a for a in alerts))
        self.assertEqual(inv[0]["cover_days"], D(10))

    def test_inventory_cover_sufficient_no_alert(self):
        inv = [{"sku": "A", "product": "a", "stock": 100, "avg_daily_units": D(2), "lead_time_days": 14}]
        self.assertEqual(bf.build_alerts(self.base_kpi(), inv, bf.Thresholds()), [])


class LoadTests(unittest.TestCase):
    def tmp(self, text):
        p = Path(tempfile.mkdtemp()) / "x.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_single_day_rejected(self):
        p = self.tmp("date,sales,orders,sessions,ad_spend,refund_amount\n2026-11-01,1,1,1,1,0\n")
        with self.assertRaisesRegex(ValueError, "至少需要 2 天"):
            bf.load_metrics(p)

    def test_bad_number_reports_date(self):
        p = self.tmp("date,sales,orders,sessions,ad_spend,refund_amount\n"
                     "2026-11-01,1,1,1,1,0\n2026-11-02,xx,1,1,1,0\n")
        with self.assertRaisesRegex(ValueError, "2026-11-02: 字段 sales"):
            bf.load_metrics(p)

    def test_zero_daily_units_rejected(self):
        p = self.tmp("sku,product,stock,avg_daily_units,lead_time_days\nA,a,1,0,7\n")
        with self.assertRaisesRegex(ValueError, "必须大于 0"):
            bf.load_inventory(p)

    def test_metrics_sorted_by_date(self):
        p = self.tmp("date,sales,orders,sessions,ad_spend,refund_amount\n"
                     "2026-11-02,2,1,1,1,0\n2026-11-01,1,1,1,1,0\n")
        self.assertEqual([r["date"] for r in bf.load_metrics(p)], ["2026-11-01", "2026-11-02"])


class CliTests(unittest.TestCase):
    def test_bundled_run_writes_briefing(self):
        out = Path(tempfile.mkdtemp())
        self.assertEqual(bf.main(["--out", str(out)]), 0)
        text = (out / "briefing-2026-11-21.md").read_text(encoding="utf-8")
        self.assertIn("销售额较近 7 日均值下降 33.3%", text)
        self.assertIn("KB-1024", text)

    def test_threshold_override(self):
        out = Path(tempfile.mkdtemp())
        bf.main(["--out", str(out), "--sales-drop", "0.5"])
        text = (out / "briefing-2026-11-21.md").read_text(encoding="utf-8")
        self.assertNotIn("销售额较近", text)


if __name__ == "__main__":
    unittest.main()
