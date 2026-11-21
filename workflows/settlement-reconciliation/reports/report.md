# 结算对账报告

## 汇总

- 订单数：7
- 结算明细行数：8
- 无差异订单数：4
- 差异条数：4

## 差异类型分布

| 类型 | 条数 |
|---|---|
| AMOUNT_MISMATCH | 1 |
| DUPLICATE_SETTLEMENT | 1 |
| MISSING_SETTLEMENT | 1 |
| UNKNOWN_ORDER | 1 |

## 差异明细

| 类型 | 订单 | 说明 | 期望 | 实际 |
|---|---|---|---|---|
| DUPLICATE_SETTLEMENT | SO1006 | 同一订单有 2 条结算记录（ST06, ST06） |  |  |
| UNKNOWN_ORDER | SO9999 | 结算单中的订单不在订单表中 |  |  |
| AMOUNT_MISMATCH | SO1002 | 差额 +18.00 USD（容差 0.01） | -18.00 | 0.00 |
| MISSING_SETTLEMENT | SO1007 | 订单未出现在结算单中 | 16.99 |  |
