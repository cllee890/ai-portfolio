# 发票与合同信息抽取

## 目标
把 OCR 后的发票、合同文本转为结构化字段，经过必填项与金额勾稽校验后入库；校验失败的文档进入人工复核队列，**不会自动入库**。

## 处理流程
```
OCR 文本 → 标签规则抽取（标签：值） → 日期与金额规范化 → 校验 → 通过：extracted.json
                                                              └ 失败：review_queue.json（人工复核）
```

- **发票**必填：发票号码、开票日期、购买方、销售方、价税合计
- **合同**必填：合同编号、签订日期、甲乙方、合同金额
- **金额勾稽**：金额合计 + 税额 = 价税合计（容差 0.01）
- 日期统一为 `YYYY-MM-DD`，非法日期（如 2 月 30 日）会被拒绝

## 目录结构
```
invoice-extraction/
├── extract.py         # 抽取与校验（纯标准库）
├── test_extract.py    # 16 个单元测试
├── data/docs/         # 4 份示例文本（3 份发票、1 份合同）
└── reports/
    ├── extracted.json     # 全部文档的抽取结果与状态
    └── review_queue.json  # 需复核的文档
```

## 运行说明
```bash
cd workflows/invoice-extraction
python extract.py                             # 处理 data/docs 下所有 .txt
python extract.py --docs 目录 --out 输出目录
python -m unittest test_extract -v
```
本示例假设 OCR 已完成。接入 OCR（如 PaddleOCR、云厂商 OCR 接口）时，把识别结果按行写入 `.txt` 即可。

## 示例输入输出
**输入**（`inv_003.txt` 节选）：
```text
发票号码：25312000000555500001
开票日期：2026年11月07日
金额合计：800.00
税额：104.00
价税合计：950.00
```

**输出**（`reports/extracted.json` 中该文档，实际运行结果）：
```json
{"file": "inv_003.txt", "doc_type": "invoice", "status": "needs_review",
 "fields": {"invoice_no": "25312000000555500001", "invoice_date": "2026-11-07", "buyer_name": "北京测试商贸有限公司", "seller_name": "示例跨境科技有限公司", "currency": "CNY", "subtotal": "800.00", "tax_amount": "104.00", "total_amount": "950.00"},
 "problems": ["金额勾稽失败：金额合计 + 税额 与 价税合计 相差 -46.00"]}
```

**批处理结果**：处理 4 份文档，通过 3 份，待复核 1 份（`inv_003.txt`，金额勾稽失败，属于示例中故意放入的异常样本）。

## 开发中发现并修复的问题
- 合同最初被套用了发票的必填字段，报告了"缺少开票日期"。现在按文档类型使用不同的必填集合。

## 注意事项
- 规则抽取依赖版式稳定。版式变化较大时，应增加样例并补充标签别名，或改用版面分析模型。
- 税务与合同的法律效力判断不在本流程范围内，入库前需财务或法务确认。
