# 插件开发示例：自定义工具插件（Function Calling）

## 插件规范
每个插件包含：`manifest.json`（元信息与参数）、`handler.py`（执行逻辑）、`test_handler.py`（单元测试）。

## manifest.json 示例
```json
{
  "name": "currency_convert",
  "version": "1.0.0",
  "description": "按当日汇率换算金额",
  "parameters": {
    "type": "object",
    "properties": {
      "amount": {"type": "number"},
      "from": {"type": "string", "example": "USD"},
      "to": {"type": "string", "example": "CNY"}
    },
    "required": ["amount", "from", "to"]
  },
  "timeout_seconds": 5
}
```

## handler.py 示例
```python
RATES = {("USD", "CNY"): 7.2}  # 示例数据，生产环境应调用汇率接口并缓存

def handler(amount: float, **kwargs) -> dict:
    src, dst = kwargs["from"], kwargs["to"]
    rate = RATES.get((src, dst))
    if rate is None:
        return {"error": f"不支持的币种组合 {src}->{dst}"}
    return {"result": round(amount * rate, 2), "rate": rate}
```

## 开发原则
- 插件输入输出严格遵循 JSON Schema。
- 失败时返回结构化错误，不抛出未捕获异常。
- 外部调用设置超时与缓存。
