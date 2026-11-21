# 多平台同步计划（dry-run）

## 统计

- CONFLICT：1
- ORPHAN_PLATFORM_LISTING：1
- OVERWRITE_PLATFORM_EDIT：2
- UNMAPPED_ERP_SKU：1

## 明细

| SKU | 平台SKU | 动作 | 价格 | 库存 | 原因 |
|---|---|---|---|---|---|
| CB-65W | B0CB65WXXX | CONFLICT | 95.00 | 300 | 平台与 ERP 同时变化，需人工确认 |
| HB-01 | B0HB01XXXX | UNMAPPED_ERP_SKU | - | - | 平台没有对应商品 |
| KB-1024 | B0KB1024XX | OVERWRITE_PLATFORM_EDIT | 129.00 | 120 | 平台被手工修改，以 ERP 覆盖（需复核） |
| MS-220 | B0MS220XXX | OVERWRITE_PLATFORM_EDIT | 59.00 | 40 | 平台被手工修改，以 ERP 覆盖（需复核） |
| - | B0XX999XXX | ORPHAN_PLATFORM_LISTING | - | - | 平台商品在 ERP 中没有对应 SKU |
