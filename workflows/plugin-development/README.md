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

## 运行说明
**环境要求**：Python 3.9+，单元测试使用标准库 `unittest` 或 `pytest`，无第三方依赖。

**目录结构**：
```text
currency_convert/
├── manifest.json
├── handler.py
└── test_handler.py
```

**本地调用**：
```bash
cd currency_convert
python -c "from handler import handler; print(handler(100, **{'from': 'USD', 'to': 'CNY'}))"
```

**单元测试示例**（`test_handler.py`）：
```python
import unittest
from handler import handler

class TestCurrencyConvert(unittest.TestCase):
    def test_supported_pair(self):
        self.assertEqual(handler(100, **{"from": "USD", "to": "CNY"}),
                         {"result": 720.0, "rate": 7.2})

    def test_unsupported_pair_returns_error(self):
        self.assertIn("error", handler(100, **{"from": "EUR", "to": "CNY"}))

if __name__ == "__main__":
    unittest.main()
```
运行：`python -m unittest test_handler -v`

## 示例输入输出
**输入 1**：`amount=100, from=USD, to=CNY`
```json
{"result": 720.0, "rate": 7.2}
```

**输入 2**：`amount=100, from=EUR, to=CNY`（未配置该币种对）
```json
{"error": "不支持的币种组合 EUR->CNY"}
```

以上输出已实际运行验证。
