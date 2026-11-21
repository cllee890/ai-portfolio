"""monitor.py 的单元测试。运行：python -m unittest test_monitor -v"""
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

import monitor as mo


class FakeFetcher:
    """按调用顺序返回预设结果；元素为异常则抛出。"""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = {}

    def fetch(self, sku):
        self.calls[sku] = self.calls.get(sku, 0) + 1
        result = self.script[sku].pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def rec(price, available=True):
    return {"price": D(price), "currency": "USD", "available": available}


class RetryTests(unittest.TestCase):
    def test_transient_error_retried_then_succeeds(self):
        f = FakeFetcher({"A": [mo.TransientError("t"), mo.TransientError("t"), rec("10")]})
        sleeps = []
        out = mo.fetch_with_retry(f, "A", sleep=sleeps.append)
        self.assertEqual(out["price"], D("10"))
        self.assertEqual(f.calls["A"], 3)
        self.assertEqual(sleeps, [1.0, 2.0])   # 指数退避

    def test_retries_exhausted_becomes_permanent(self):
        f = FakeFetcher({"A": [mo.TransientError("x")] * 3})
        with self.assertRaisesRegex(mo.PermanentError, "重试 3 次"):
            mo.fetch_with_retry(f, "A", sleep=lambda s: None)

    def test_permanent_error_not_retried(self):
        f = FakeFetcher({"A": [mo.PermanentError("gone")]})
        with self.assertRaises(mo.PermanentError):
            mo.fetch_with_retry(f, "A", sleep=lambda s: None)
        self.assertEqual(f.calls["A"], 1)


class DetectTests(unittest.TestCase):
    def test_first_observation_is_baseline_only(self):
        self.assertEqual(mo.detect_changes("A", None, {"price": "10", "available": True}), [])

    def test_price_change_above_threshold(self):
        ch = mo.detect_changes("A", {"price": "100", "available": True}, {"price": "90", "available": True})
        self.assertEqual(ch[0]["kind"], "PRICE")
        self.assertEqual(ch[0]["change_pct"], "-10.0%")

    def test_price_change_below_threshold_ignored(self):
        self.assertEqual(mo.detect_changes("A", {"price": "100", "available": True},
                                           {"price": "102", "available": True}), [])

    def test_equal_decimal_different_string_is_not_change(self):
        self.assertEqual(mo.detect_changes("A", {"price": "39.9", "available": True},
                                           {"price": "39.90", "available": True}), [])

    def test_availability_change(self):
        ch = mo.detect_changes("A", {"price": "10", "available": True}, {"price": "10", "available": False})
        self.assertEqual([c["kind"] for c in ch], ["AVAILABILITY"])


class RunTests(unittest.TestCase):
    watch = [{"sku": "A", "competitor": "S", "product": "p"}]

    def test_alert_generated_on_second_run(self):
        f1 = FakeFetcher({"A": [rec("100")]})
        _, _, state = mo.run(self.watch, f1, {}, sleep=lambda s: None)
        f2 = FakeFetcher({"A": [rec("80")]})
        alerts, failures, new_state = mo.run(self.watch, f2, state, sleep=lambda s: None)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["competitor"], "S")
        self.assertEqual(new_state["A"]["price"], "80")

    def test_failure_keeps_previous_baseline(self):
        state = {"A": {"price": "100", "currency": "USD", "available": True}}
        f = FakeFetcher({"A": [mo.PermanentError("解析失败")]})
        alerts, failures, new_state = mo.run(self.watch, f, state, sleep=lambda s: None)
        self.assertEqual(alerts, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(new_state["A"]["price"], "100")

    def test_one_failure_does_not_stop_batch(self):
        watch = self.watch + [{"sku": "B", "competitor": "S", "product": "q"}]
        f = FakeFetcher({"A": [mo.PermanentError("x")], "B": [rec("5")]})
        _, failures, new_state = mo.run(watch, f, {}, sleep=lambda s: None)
        self.assertEqual([x["sku"] for x in failures], ["A"])
        self.assertIn("B", new_state)


class SnapshotAndCliTests(unittest.TestCase):
    def tmpfile(self, obj, name="s.json"):
        p = Path(tempfile.mkdtemp()) / name
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_snapshot_error_raises_transient(self):
        f = mo.SnapshotFetcher(self.tmpfile({"A": {"error": "timeout"}}))
        with self.assertRaises(mo.TransientError):
            f.fetch("A")

    def test_snapshot_unknown_sku_permanent(self):
        f = mo.SnapshotFetcher(self.tmpfile({}))
        with self.assertRaises(mo.PermanentError):
            f.fetch("Z")

    def test_bad_price_is_permanent(self):
        f = mo.SnapshotFetcher(self.tmpfile({"A": {"price": "abc"}}))
        with self.assertRaises(mo.PermanentError):
            f.fetch("A")

    def test_duplicate_sku_in_watchlist_rejected(self):
        p = Path(tempfile.mkdtemp()) / "w.csv"
        p.write_text("sku,competitor,product,url\nA,S,p,u\nA,S,p,u\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重复"):
            mo.load_watchlist(p)

    def test_cli_two_runs_produce_alert(self):
        out = Path(tempfile.mkdtemp())
        state = out / "state.json"
        snap1 = self.tmpfile({"CMP-001": {"price": "100"}}, "a.json")
        snap2 = self.tmpfile({"CMP-001": {"price": "80"}}, "b.json")
        wl = out / "w.csv"
        wl.write_text("sku,competitor,product,url\nCMP-001,S,p,u\n", encoding="utf-8")
        self.assertEqual(mo.main(["--watchlist", str(wl), "--snapshot", str(snap1),
                                  "--state", str(state), "--out", str(out)]), 0)
        self.assertEqual(mo.main(["--watchlist", str(wl), "--snapshot", str(snap2),
                                  "--state", str(state), "--out", str(out)]), 0)
        text = (out / "alerts-b.md").read_text(encoding="utf-8")
        self.assertIn("告警数：1", text)


if __name__ == "__main__":
    unittest.main()
