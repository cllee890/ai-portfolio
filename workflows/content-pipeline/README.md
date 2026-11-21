# 内容生产流水线

## 目标
从一个商品的卖点信息出发，依次生成选题、短视频脚本、配图提示词、发布文案和排期，并在关键节点设置人工审核闸口。

## 流程
```
商品信息 → 选题 ──(审核)──► 脚本 ──(合规检查)──► 配图提示词 → 文案 ──(审核 + 合规检查)──► 排期
```

- **断点续跑**：每个阶段的产物与输入哈希保存在 `reports/<sku>/`，输入未变则直接复用。
- **审核闸口**：选题、脚本、文案必须在 `review_approvals.json` 中获批，否则流水线停在该阶段。
- **合规阻断**：脚本与文案中出现"最好、第一、100%、永久、根治"等表述时立即阻断，并写明命中词，不会进入审核。
- **生成器**：默认是离线模板，便于复现。接入大模型时替换 `gen_*` 函数即可，闸口与缓存逻辑不需要改。

## 目录结构
```
content-pipeline/
├── pipeline.py          # 流水线主程序（纯标准库）
├── test_pipeline.py     # 14 个单元测试
├── data/
│   ├── product.json           # 商品卖点
│   └── review_approvals.json  # 审核记录（示例：选题与脚本已通过）
└── reports/KB-1024/           # 各阶段产物与 state.json
```

## 运行说明
```bash
cd workflows/content-pipeline
python pipeline.py                                  # 运行到文案审核处停止（退出码 2）
python pipeline.py --approvals 审核记录.json          # 审核通过后再次运行，复用已生成的阶段
python -m unittest test_pipeline -v
```
审核记录示例：`{"topic": true, "script": true, "caption": true}`。

## 示例输入输出
**输入**：`data/product.json`（无线静音键盘，3 条卖点，首发价 9 折）。

**第一次运行**（`data/review_approvals.json` 中只有选题与脚本已通过）：
```text
state.status = "waiting_for_review:caption"
topic: done | script: done | image_prompt: done | caption: awaiting_review
```

**审核通过后再次运行**（加入 `"caption": true`）：
```text
state.status = "complete"
topic: from_cache | script: from_cache | image_prompt: from_cache | caption: from_cache | schedule: new
```

**文案产物**（`reports/KB-1024/caption.json`，节选）：
```json
{"title": "居家办公和夜间写作的人为什么都在换无线静音键盘", "body": "无线静音键盘：静音按键，夜间打字不扰民；蓝牙 5.0 + 2.4G 双模连接；一次充电可用 60 天。首发价 9 折，活动至 11 月 30 日。", "hashtags": ["#键盘", "#居家办公", "#kb-1024"]}
```

**合规阻断示例**：若卖点写成"全网最好的键盘"，流水线输出 `compliance_block:script:最好`，不会生成后续阶段。

## 注意事项
- 离线模板生成的文案较机械，只用于演示流程。实际使用时应由文案人员改写，并保留审核记录。
- 合规词表只是示例，正式使用时应按目标平台与市场的规则扩充，并与 `platform-compliance-review` Skill 的检查清单对齐。
- 排期只给出日期，不负责发布，发布前仍需人工确认平台账号与素材。
