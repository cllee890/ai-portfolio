"""订单查询工具（Function Calling）示例实现。

与 README 中的 query_order 工具定义保持一致。
配置通过环境变量读取：SHOP_API_BASE、SHOP_API_TOKEN（不写入代码）。
接口约定（示意）：GET {SHOP_API_BASE}/orders/{order_id}
    返回 JSON：{"order_id": str, "status": str, "logistics_status": str, "updated_at": str}
"""
import json
import os
import re

import requests

TOOL_SCHEMA = {
    "name": "query_order",
    "description": "根据订单号查询物流状态",
    "parameters": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
}

TIMEOUT_SECONDS = 5
_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9\-]{1,32}$")


class OrderServiceError(Exception):
    """订单服务调用失败（网络、鉴权、限流或服务端错误）。"""


def _validate_order_id(order_id) -> str | None:
    if not isinstance(order_id, str) or not _ORDER_ID_RE.match(order_id.strip()):
        return "订单号格式不正确"
    return None


def query_order(order_id: str) -> dict:
    """查询订单物流状态。

    成功：返回订单信息字典。
    可预期的失败（格式错误、订单不存在）：返回 {"error": ..., "code": ...}，不抛异常。
    服务不可用：抛出 OrderServiceError，由调用方决定转人工或重试。
    """
    err = _validate_order_id(order_id)
    if err:
        return {"error": err, "code": "INVALID_ORDER_ID"}
    order_id = order_id.strip()

    base = os.environ.get("SHOP_API_BASE", "")
    token = os.environ.get("SHOP_API_TOKEN", "")
    if not base or not token:
        raise OrderServiceError("缺少 SHOP_API_BASE 或 SHOP_API_TOKEN 配置")

    try:
        resp = requests.get(
            f"{base}/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise OrderServiceError(f"订单服务请求失败：{exc}") from exc

    if resp.status_code == 404:
        return {"error": f"未找到订单 {order_id}", "code": "NOT_FOUND"}
    if resp.status_code in (401, 403):
        raise OrderServiceError("订单服务鉴权失败")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise OrderServiceError(f"订单服务暂不可用（HTTP {resp.status_code}）")
    if resp.status_code != 200:
        raise OrderServiceError(f"订单服务返回异常状态码 {resp.status_code}")

    data = resp.json()
    return {
        "order_id": data.get("order_id", order_id),
        "status": data.get("status"),
        "logistics_status": data.get("logistics_status"),
        "updated_at": data.get("updated_at"),
    }


def dispatch_tool_call(name: str, arguments) -> str:
    """执行模型发起的工具调用，返回 JSON 字符串供回填给模型。

    arguments 可以是 JSON 字符串（模型原始输出）或已解析的 dict。
    """
    if name != TOOL_SCHEMA["name"]:
        return json.dumps({"error": f"未知工具 {name}", "code": "UNKNOWN_TOOL"}, ensure_ascii=False)

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "工具参数不是合法 JSON", "code": "BAD_ARGUMENTS"}, ensure_ascii=False)
    if not isinstance(arguments, dict) or "order_id" not in arguments:
        return json.dumps({"error": "缺少必填参数 order_id", "code": "BAD_ARGUMENTS"}, ensure_ascii=False)

    try:
        result = query_order(arguments["order_id"])
    except OrderServiceError as exc:
        # 服务故障不向模型暴露内部细节，统一提示转人工
        return json.dumps({"error": "订单服务暂时不可用，请转人工处理", "code": "SERVICE_UNAVAILABLE",
                           "detail": str(exc)}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)
