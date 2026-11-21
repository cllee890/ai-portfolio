"""order_tools.py 的单元测试：订单查询及工具调用分发。

全部通过 mock 替换 HTTP 请求，不访问真实店铺接口。
运行：python -m unittest test_order_tools -v   （或 pytest）
"""
import json
import unittest
from unittest import mock

import requests

import order_tools as ot

ENV = {"SHOP_API_BASE": "https://api.example-shop.com/v1", "SHOP_API_TOKEN": "test-token"}


def fake_response(status=200, body=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    return resp


ORDER_BODY = {
    "order_id": "A1001",
    "status": "paid",
    "logistics_status": "in_transit",
    "updated_at": "2026-11-20T10:00:00+08:00",
}


class ToolSchemaTests(unittest.TestCase):
    def test_schema_matches_readme_definition(self):
        self.assertEqual(ot.TOOL_SCHEMA["name"], "query_order")
        self.assertEqual(ot.TOOL_SCHEMA["parameters"]["required"], ["order_id"])
        self.assertEqual(ot.TOOL_SCHEMA["parameters"]["properties"]["order_id"]["type"], "string")


class QueryOrderTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict("os.environ", ENV, clear=False)
        self.env.start()
        self.get = mock.patch.object(ot.requests, "get").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_success_returns_selected_fields_and_calls_endpoint(self):
        self.get.return_value = fake_response(200, {**ORDER_BODY, "extra": "ignored"})
        result = ot.query_order("A1001")
        self.assertEqual(result, ORDER_BODY)
        args, kwargs = self.get.call_args
        self.assertEqual(args[0], "https://api.example-shop.com/v1/orders/A1001")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer test-token"})
        self.assertEqual(kwargs["timeout"], ot.TIMEOUT_SECONDS)

    def test_order_id_is_stripped_before_request(self):
        self.get.return_value = fake_response(200, ORDER_BODY)
        ot.query_order("  A1001 ")
        self.assertIn("/orders/A1001", self.get.call_args[0][0])

    def test_not_found_returns_structured_error(self):
        self.get.return_value = fake_response(404)
        result = ot.query_order("A9999")
        self.assertEqual(result["code"], "NOT_FOUND")
        self.assertIn("A9999", result["error"])

    def test_invalid_order_id_does_not_hit_network(self):
        for bad in ["", "   ", "A1001; DROP", "x" * 33, None, 123]:
            with self.subTest(order_id=bad):
                result = ot.query_order(bad)
                self.assertEqual(result["code"], "INVALID_ORDER_ID")
        self.get.assert_not_called()

    def test_auth_failure_raises_service_error(self):
        self.get.return_value = fake_response(401)
        with self.assertRaises(ot.OrderServiceError):
            ot.query_order("A1001")

    def test_rate_limit_and_server_error_raise_service_error(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                self.get.return_value = fake_response(status)
                with self.assertRaises(ot.OrderServiceError):
                    ot.query_order("A1001")

    def test_network_exception_is_wrapped(self):
        self.get.side_effect = requests.Timeout("timed out")
        with self.assertRaises(ot.OrderServiceError):
            ot.query_order("A1001")

    def test_missing_config_raises_without_request(self):
        with mock.patch.dict("os.environ", {"SHOP_API_BASE": "", "SHOP_API_TOKEN": ""}):
            with self.assertRaises(ot.OrderServiceError):
                ot.query_order("A1001")
        self.get.assert_not_called()


class DispatchToolCallTests(unittest.TestCase):
    def setUp(self):
        mock.patch.dict("os.environ", ENV).start()
        self.get = mock.patch.object(ot.requests, "get").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_json_string_arguments_success(self):
        self.get.return_value = fake_response(200, ORDER_BODY)
        out = json.loads(ot.dispatch_tool_call("query_order", '{"order_id": "A1001"}'))
        self.assertEqual(out, ORDER_BODY)

    def test_dict_arguments_are_accepted(self):
        self.get.return_value = fake_response(200, ORDER_BODY)
        out = json.loads(ot.dispatch_tool_call("query_order", {"order_id": "A1001"}))
        self.assertEqual(out["order_id"], "A1001")

    def test_unknown_tool_name(self):
        out = json.loads(ot.dispatch_tool_call("refund_order", '{"order_id": "A1001"}'))
        self.assertEqual(out["code"], "UNKNOWN_TOOL")
        self.get.assert_not_called()

    def test_malformed_json_arguments(self):
        out = json.loads(ot.dispatch_tool_call("query_order", "{not json"))
        self.assertEqual(out["code"], "BAD_ARGUMENTS")
        self.get.assert_not_called()

    def test_missing_required_parameter(self):
        out = json.loads(ot.dispatch_tool_call("query_order", "{}"))
        self.assertEqual(out["code"], "BAD_ARGUMENTS")
        self.get.assert_not_called()

    def test_non_object_arguments(self):
        out = json.loads(ot.dispatch_tool_call("query_order", '["A1001"]'))
        self.assertEqual(out["code"], "BAD_ARGUMENTS")

    def test_service_failure_returns_handoff_message_without_internal_leak(self):
        self.get.return_value = fake_response(503)
        out = json.loads(ot.dispatch_tool_call("query_order", '{"order_id": "A1001"}'))
        self.assertEqual(out["code"], "SERVICE_UNAVAILABLE")
        self.assertIn("转人工", out["error"])
        self.assertIn("detail", out)  # 详情仅供日志，模型侧应只使用 error 字段

    def test_not_found_passes_through_as_tool_result(self):
        self.get.return_value = fake_response(404)
        out = json.loads(ot.dispatch_tool_call("query_order", '{"order_id": "A9999"}'))
        self.assertEqual(out["code"], "NOT_FOUND")

    def test_result_is_valid_json_string_with_chinese_text(self):
        self.get.return_value = fake_response(404)
        raw = ot.dispatch_tool_call("query_order", '{"order_id": "A9999"}')
        self.assertIsInstance(raw, str)
        self.assertIn("未找到订单", raw)  # ensure_ascii=False，中文不转义


if __name__ == "__main__":
    unittest.main()
