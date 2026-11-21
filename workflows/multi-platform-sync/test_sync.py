"""sync.py 的单元测试。运行：python -m unittest test_sync -v"""
import json
import shutil
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

import sync as sy

HERE = Path(__file__).resolve().parent


def e(price="10.00", stock=5):
    return {"price": price, "stock": stock}


def one(erp, plat, base=None):
    acts = sy.plan({"A": erp}, {"A": "PA"}, {"PA": plat}, {} if base is None else {"A": base})
    return next(a for a in acts if a["sku"] == "A")


class PlanTests(unittest.TestCase):
    def test_in_sync_is_noop(self):
        self.assertEqual(one(e(), e())["action"], "NOOP")

    def test_first_sync_pushes(self):
        self.assertEqual(one(e("12"), e("10")), {**one(e("12"), e("10")), "action": "PUSH", "reason": "首次同步"})

    def test_erp_only_change_pushes(self):
        a = one(e("12"), e("10"), base=e("10"))
        self.assertEqual(a["action"], "PUSH")

    def test_platform_only_change_overwrites_with_flag(self):
        a = one(e("10"), e("8"), base=e("10"))
        self.assertEqual(a["action"], "OVERWRITE_PLATFORM_EDIT")

    def test_both_changed_is_conflict(self):
        a = one(e("12"), e("8"), base=e("10"))
        self.assertEqual(a["action"], "CONFLICT")

    def test_string_vs_number_stock_is_not_false_change(self):
        # 回归测试：基线为数字 120，ERP 为字符串 "120"，不应判为 ERP 变化
        acts = sy.plan({"A": {"price": "10.00", "stock": "120"}}, {"A": "PA"},
                       {"PA": {"price": "10.00", "stock": "110"}},
                       {"A": {"price": "10.00", "stock": 120}})
        self.assertEqual(acts[0]["action"], "OVERWRITE_PLATFORM_EDIT")

    def test_price_equal_numerically_different_text_is_noop(self):
        acts = sy.plan({"A": {"price": "10", "stock": "5"}}, {"A": "PA"},
                       {"PA": {"price": "10.00", "stock": "5"}}, {})
        self.assertEqual(acts[0]["action"], "NOOP")

    def test_unmapped_and_orphan_are_reported_not_written(self):
        acts = sy.plan({"A": e()}, {}, {"PX": e()}, {})
        kinds = {a["action"] for a in acts}
        self.assertEqual(kinds, {"UNMAPPED_ERP_SKU", "ORPHAN_PLATFORM_LISTING"})


class ApplyTests(unittest.TestCase):
    class Recorder:
        def __init__(self, fail_on=()):
            self.calls, self.fail_on = [], set(fail_on)

        def update(self, psku, price, stock):
            if psku in self.fail_on:
                raise RuntimeError("平台限流")
            self.calls.append((psku, price, stock))

    def test_only_push_actions_are_written(self):
        acts = sy.plan({"A": e("12"), "B": e()}, {"A": "PA", "B": "PB"},
                       {"PA": e("10"), "PB": e("10")}, {"A": e("10"), "B": e("10")})
        rec = self.Recorder()
        sy.apply(acts, rec, {})
        self.assertEqual([c[0] for c in rec.calls], ["PA"])

    def test_conflict_is_never_written(self):
        acts = sy.plan({"A": e("12")}, {"A": "PA"}, {"PA": e("8")}, {"A": e("10")})
        rec = self.Recorder()
        sy.apply(acts, rec, {"A": e("10")})
        self.assertEqual(rec.calls, [])

    def test_failed_write_keeps_old_baseline(self):
        acts = sy.plan({"A": e("12")}, {"A": "PA"}, {"PA": e("10")}, {"A": e("10")})
        rec = self.Recorder(fail_on=["PA"])
        new_base, errors = sy.apply(acts, rec, {"A": e("10")})
        self.assertEqual(len(errors), 1)
        self.assertEqual(new_base["A"], e("10"))

    def test_successful_write_updates_baseline(self):
        acts = sy.plan({"A": e("12")}, {"A": "PA"}, {"PA": e("10")}, {"A": e("10")})
        new_base, errors = sy.apply(acts, self.Recorder(), {"A": e("10")})
        self.assertEqual(errors, [])
        self.assertEqual(new_base["A"]["price"], "12.00")

    def test_noop_refreshes_baseline(self):
        acts = sy.plan({"A": e("10")}, {"A": "PA"}, {"PA": e("10")}, {"A": e("9")})
        new_base, _ = sy.apply(acts, self.Recorder(), {"A": e("9")})
        self.assertEqual(new_base["A"]["price"], "10.00")


class CliTests(unittest.TestCase):
    def test_dry_run_does_not_touch_state(self):
        out = Path(tempfile.mkdtemp())
        state = out / "state.json"
        shutil.copy(HERE / "data" / "sync_state.json", state)
        before = state.read_text(encoding="utf-8")
        self.assertEqual(sy.main(["--state", str(state), "--out", str(out)]), 0)
        self.assertEqual(state.read_text(encoding="utf-8"), before)
        self.assertIn("dry-run", (out / "plan.md").read_text(encoding="utf-8"))

    def test_apply_writes_state_for_pushed_skus_only(self):
        out = Path(tempfile.mkdtemp())
        state = out / "state.json"
        shutil.copy(HERE / "data" / "sync_state.json", state)
        sy.main(["--state", str(state), "--out", str(out), "--apply"])
        new = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(new["CB-65W"]["price"], "89.00")   # 冲突项保持原基线
        self.assertEqual(new["KB-1024"]["price"], "129.00")  # 覆盖项已刷新

    def test_missing_input_returns_1(self):
        self.assertEqual(sy.main(["--erp", "/none.csv", "--out", tempfile.mkdtemp()]), 1)


if __name__ == "__main__":
    unittest.main()
