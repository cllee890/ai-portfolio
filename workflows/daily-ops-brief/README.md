# 每日运营简报

## 目标
每天汇总销售、广告、退款数据，计算环比与近 7 日均值，检查阈值告警，并核对库存可售天数是否短于补货周期，生成一页简报供运营晨会使用。

## 指标与规则
| 指标 | 计算方式 | 默认告警阈值 |
|---|---|---|
| 销售额环比 | 当日 vs 前一日 | — |
| 销售额较近 7 日均值 | 当日 vs 前 7 天（不含当日）平均 | 下降超过 20% |
| ROAS | 销售额 ÷ 广告费 | 低于 2.0 |
| 退款率 | 退款金额 ÷ 销售额 | 高于 10% |
| 库存可售天数 | 库存 ÷ 日均销量 | 短于补货周期 |

阈值可通过 `--sales-drop`、`--min-roas`、`--max-refund-rate` 调整。

## 目录结构
```
daily-ops-brief/
├── briefing.py          # 简报生成（纯标准库）
├── test_briefing.py     # 20 个单元测试
├── data/
│   ├── daily_metrics.csv  # 8 天的日指标
│   └── inventory.csv      # 4 个 SKU 的库存与补货周期
└── reports/
    └── briefing-2026-11-21.md
```

## 运行说明
```bash
cd workflows/daily-ops-brief
python briefing.py                                       # 生成当日简报
python briefing.py --metrics 指标.csv --inventory 库存.csv --out 输出目录
python briefing.py --sales-drop 0.5                      # 调整阈值
python -m unittest test_briefing -v
```
- `daily_metrics.csv` 列：`date,sales,orders,sessions,ad_spend,refund_amount`（至少 2 天）
- `inventory.csv` 列：`sku,product,stock,avg_daily_units,lead_time_days`

## 示例输入输出
**输入**：2026-11-21 销售额 812.00（前 7 天均值约 1218），广告费 190.00；键盘 KB-1024 库存 120，日均销量 6，补货周期 21 天。

**输出**（`reports/briefing-2026-11-21.md`，节选，实际运行结果）：
```markdown
# 每日运营简报 2026-11-21

| 指标 | 数值 | 对比 |
|---|---|---|
| 销售额 | 812.00 | 环比 -33.4%，较近 7 日均值 -33.3% |
| 订单数 | 16 | 较近 7 日均值 -9.0 |
| 广告回报率 (ROAS) | 4.27 | - |
| 退款率 | 1.2% | - |

## 告警
- ⚠️ 销售额较近 7 日均值下降 33.3%，超过 20% 阈值
- ⚠️ KB-1024（无线静音键盘）库存可售 20.0 天，短于补货周期 21 天，需立即下单
- ⚠️ MS-220（静音鼠标）库存可售 8.0 天，短于补货周期 14 天，需立即下单
- ⚠️ HB-01（蓝牙耳机）库存可售 6.0 天，短于补货周期 28 天，需立即下单
```

## 注意事项
- 近 7 日均值以当日之前的 7 天计算，不足 7 天时使用可用天数，报告中会显示实际窗口。
- 单日下跌可能与节假日或物流延迟有关，告警只提示需要关注，不代表原因。
- ROAS 只按广告平台上报的费用计算，未考虑佣金与物流成本。
