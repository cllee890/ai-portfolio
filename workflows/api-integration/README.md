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

## 运行说明
**环境要求**：Python 3.9+，依赖 `requests`（`pip install requests`）。

**环境变量**（不要写入代码或仓库）：
```bash
export SHOP_API_BASE="https://api.example-shop.com/v1"   # 店铺 API 根地址
export SHOP_API_TOKEN="你的访问令牌"
```

**运行方式**：示例代码中的 `sync_orders(since)` 只负责拉取与筛选，不包含写入表格和推送通知，需在调用处自行接入。
```python
from sync import sync_orders   # 将上方示例保存为 sync.py
rows, abnormal = sync_orders("2026-11-20T00:00:00+08:00")
print(len(rows), [o["order_id"] for o in abnormal])
```

## 示例输入输出
**输入**：`sync_orders("2026-11-20T00:00:00+08:00")`，接口分两页返回（每页 2 条）：

| 页 | 返回 `items` | `next_cursor` |
|---|---|---|
| 第 1 页 | A1001（paid）、A1002（refund） | `"2"` |
| 第 2 页 | A1003（shipped）、A1004（chargeback） | `null` |

**输出**（已用本地 mock 接口验证）：
```text
total: 4
abnormal: ['A1002', 'A1004']
```

**异常输入**：若 `SHOP_API_TOKEN` 无效，接口返回 401，`get()` 不会重试而是直接抛出：
```text
HTTPError 401 Client Error: Unauthorized for url: .../orders?...
```
