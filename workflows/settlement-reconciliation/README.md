# 平台结算对账流水线

## 目标
把平台结算单（按笔到账明细）与内部订单记录逐笔比对，找出金额差异、漏结算、重复结算、退款不一致和币种错误，输出可直接交给财务的差异清单。

## 对账规则
- **期望到账** = 订单金额 − 平台佣金 − 退款金额（全部使用 `Decimal`）
- **实际到账** = 结算单 `net_amount`
- 容差默认 0.01，可通过 `--tolerance` 调整

| 差异类型 | 含义 |
|---|---|
| `MISSING_SETTLEMENT` | 订单存在但结算单没有记录 |
| `UNKNOWN_ORDER` | 结算单中的订单不在订单表中 |
| `DUPLICATE_SETTLEMENT` | 同一订单有多条结算记录 |
| `CURRENCY_MISMATCH` | 结算币种与订单币种不同 |
| `AMOUNT_MISMATCH` | 实际与期望金额差额超过容差 |
| `REFUND_MISMATCH` | 退款金额不一致 |

## 目录结构
```
settlement-reconciliation/
├── reconcile.py          # 对账主程序（纯标准库）
├── test_reconcile.py     # 17 个单元测试
├── data/
│   ├── orders.csv        # 示例订单表
│   └── settlement.csv    # 示例结算单（含故意制造的各类差异）
└── reports/
    ├── discrepancies.csv # 差异明细
    └── report.md         # 汇总报告
```

## 运行说明
```bash
cd workflows/settlement-reconciliation
python reconcile.py                                   # 使用示例数据
python reconcile.py --orders 订单.csv --settlement 结算.csv --out 输出目录
python reconcile.py --strict                          # 有差异时退出码为 2，可接入定时任务告警
python -m unittest test_reconcile -v                  # 运行测试
```
输入文件的必需列：
- `orders.csv`：`order_id,order_date,currency,order_amount,platform_commission,refund_amount`
- `settlement.csv`：`settlement_id,order_id,settle_date,currency,net_amount,refund_amount`

## 示例输入输出
**输入**（节选）：订单 `SO1001` 金额 59.90、佣金 8.99、无退款 → 期望到账 50.91；结算单 `ST01` 实际到账 50.91 → 无差异。

**运行输出**：
```text
订单 7 笔，结算 8 行，差异 4 条
```

**差异清单**（`reports/discrepancies.csv`）：
| 类型 | 订单 | 说明 | 期望 | 实际 |
|---|---|---|---|---|
| DUPLICATE_SETTLEMENT | SO1006 | 同一订单有 2 条结算记录（ST06, ST06） | | |
| UNKNOWN_ORDER | SO9999 | 结算单中的订单不在订单表中 | | |
| AMOUNT_MISMATCH | SO1002 | 差额 +18.00 USD（容差 0.01） | -18.00 | 0.00 |
| MISSING_SETTLEMENT | SO1007 | 订单未出现在结算单中 | 16.99 | |

以上为实际运行结果。`SO1002` 的差异说明：全额退款后平台未回收佣金，财务应核实这 18.00 是否应由平台退回。

## 注意事项
- 平台结算单的字段名因平台而异，接入时只需在 `load_settlements` 中做字段映射。
- 汇率换算不在本示例范围内，跨币种结算需先按统一汇率折算后再比对。
- 差异只是线索，最终处理需财务人员核实。
