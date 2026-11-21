# 多平台商品同步

## 目标
以 ERP 为主数据，把价格与库存同步到平台（如 Amazon、Shopee）。同步前先生成计划，识别"双方都改过"的冲突，并避免覆盖平台上的手工修改而不留痕。

## 同步规则
以上一次成功同步的**基线**（`sync_state.json`）判断哪一方改过了：

| 情况 | 动作 |
|---|---|
| 平台与 ERP 一致 | `NOOP`，并刷新基线 |
| 只有 ERP 变化，或首次同步 | `PUSH` |
| 平台被手工修改，ERP 未变 | `OVERWRITE_PLATFORM_EDIT`：以 ERP 覆盖，并标记复核 |
| 平台与 ERP 都变了，且不一致 | `CONFLICT`：**不写入**，转人工 |
| ERP 有 SKU 但平台无映射 | `UNMAPPED_ERP_SKU`：只报告 |
| 平台有商品但 ERP 无 SKU | `ORPHAN_PLATFORM_LISTING`：只报告，不删除 |

标题与文案不同步（平台可自定义）。默认 dry-run，只有加 `--apply` 才会调用写接口；**只有写入成功的 SKU 才更新基线**。

## 目录结构
```
multi-platform-sync/
├── sync.py            # 计划与执行（纯标准库）
├── test_sync.py       # 16 个单元测试
├── data/
│   ├── erp_products.csv     # ERP 主数据
│   ├── mapping_amazon.csv   # SKU ↔ 平台 SKU 映射
│   ├── platform_amazon.csv  # 平台当前状态（模拟）
│   └── sync_state.json      # 上次同步基线
└── reports/plan.md
```

## 运行说明
```bash
cd workflows/multi-platform-sync
python sync.py                   # 只生成计划（dry-run）
python sync.py --apply           # 执行写入并更新基线（会修改 data/sync_state.json）
python -m unittest test_sync -v
```
`--apply` 当前使用 `FilePlatform` 占位客户端，只记录写入内容。接入真实平台时实现 `update(platform_sku, price, stock)`，并替换 `main()` 中的客户端。

## 示例输入输出
**输入**：ERP 中 KB-1024 价格 129.00、库存 120；平台 B0KB1024XX 库存为 118；基线为 129.00 / 120。

**输出**（`reports/plan.md`，实际运行结果）：
| SKU | 平台SKU | 动作 | 价格 | 库存 | 原因 |
|---|---|---|---|---|---|
| CB-65W | B0CB65WXXX | CONFLICT | 95.00 | 300 | 平台与 ERP 同时变化，需人工确认 |
| HB-01 | B0HB01XXXX | UNMAPPED_ERP_SKU | - | - | 平台没有对应商品 |
| KB-1024 | B0KB1024XX | OVERWRITE_PLATFORM_EDIT | 129.00 | 120 | 平台被手工修改，以 ERP 覆盖（需复核） |
| MS-220 | B0MS220XXX | OVERWRITE_PLATFORM_EDIT | 59.00 | 40 | 平台被手工修改，以 ERP 覆盖（需复核） |
| - | B0XX999XXX | ORPHAN_PLATFORM_LISTING | - | - | 平台商品在 ERP 中没有对应 SKU |

CB-65W 两边都改了（ERP 89→95，平台 89→92），因此标记为冲突，不会自动覆盖。

## 开发中发现并修复的问题
- 基线中库存是数字、ERP 中是字符串，比较时被误判为"ERP 已变化"。现在统一归一化为字符串，并有回归测试。
- `"10"` 与 `"10.00"` 价格会被误判为不同。现在统一保留两位小数比较。

## 注意事项
- 平台 API 通常有限流与异步处理，真实接入时需要批量接口、重试与幂等键。
- 覆盖平台手工修改前，应先让运营确认，`OVERWRITE_PLATFORM_EDIT` 正是为此保留的复核记录。
