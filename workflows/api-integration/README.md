# API 对接示例：订单同步到表格并触发通知

## 场景
将店铺订单 API 同步到飞书/Google Sheets，并在异常订单时推送通知。

## 设计要点
- **鉴权**：OAuth2 / API Key 存储于环境变量；刷新 token 自动处理。
- **分页**：使用游标分页，避免一次拉取过多数据。
- **限流**：指数退避重试（429/5xx），最多 5 次。
- **幂等**：以订单号为唯一键，重复写入时更新而非新增。
- **增量同步**：记录上次同步时间戳。

## 示例代码
```python
import os, time, requests

BASE = os.environ["SHOP_API_BASE"]
TOKEN = os.environ["SHOP_API_TOKEN"]

def get(path, params=None, retries=5):
    for i in range(retries):
        r = requests.get(f"{BASE}{path}", params=params,
                         headers={"Authorization": f"Bearer {TOKEN}"}, timeout=15)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** i); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("API 重试次数耗尽")

def sync_orders(since: str):
    cursor, rows = None, []
    while True:
        data = get("/orders", {"updated_after": since, "cursor": cursor})
        rows += data["items"]
        cursor = data.get("next_cursor")
        if not cursor:
            break
    abnormal = [o for o in rows if o["status"] in ("refund", "chargeback")]
    return rows, abnormal
```
