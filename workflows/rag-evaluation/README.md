# RAG 评测流水线：检索质量与转人工策略的自动化评测

## 目标
智能客服的 RAG 系统上线前后，需要回答三个问题：**相关文档能否被找到？** **找到的依据能否支撑回答？** **无依据的问题是否正确转人工？** 本流水线把这三件事写成可重复运行的评测，输出指标报告，并可作为 CI 门禁。

## 流程
```
知识库文档 ──► 按标题切分 ──► 建立检索索引 ──┐
                                            ├─► 逐条检索 ─► 阈值判断（命中 / 转人工）─► 指标计算 ─► report.md / report.json
测试集 JSONL ──► 校验字段与 id ─────────────┘                                         │
                                                                    可选：与基线对比 / 阈值扫描 / 门禁
```

## 指标定义
| 指标 | 含义 | 计算范围 |
|---|---|---|
| Hit@k | 前 k 个结果中是否包含相关文档 | 可回答样本 |
| Hit@1 | 第 1 个结果是否为相关文档 | 可回答样本 |
| MRR | 第一个相关结果排名的倒数均值 | 可回答样本 |
| 依据关键词覆盖率 | 期望关键词在"通过阈值的上下文"中出现的比例，作为生成前的依据质量代理 | 未转人工的可回答样本 |
| 转人工准确率 | 实际转人工与期望是否一致 | 全部样本 |
| 误转人工率 | 可回答却转人工的比例（体验损失） | 可回答样本 |
| 漏转人工率 | 应转人工却直接回答的比例（风险） | 应转人工样本 |

转人工规则：**所有检索结果的得分都低于阈值时转人工**，与 `customer-service-bot/knowledge_base.py` 的逻辑一致。

## 目录结构
```
rag-evaluation/
├── eval_rag.py            # 评测主程序（纯标准库）
├── test_eval_rag.py       # 单元测试与端到端测试
├── data/
│   ├── docs/              # 示例知识库：退款、物流、保修、发票、换货政策
│   └── testset.jsonl      # 测试集：16 条可回答 + 4 条应转人工
└── reports/
    ├── report.md          # 示例输出：Markdown 报告
    └── report.json        # 示例输出：机器可读结果，可作为下次对比的基线
```

## 运行说明
**环境要求**：Python 3.10+，默认检索器无第三方依赖，不需要 API Key。

```bash
cd workflows/rag-evaluation

# 1. 运行评测（报告写入 reports/）
python eval_rag.py

# 2. 扫描多个阈值，观察误转与漏转的取舍
python eval_rag.py --sweep 0.1,0.15,0.2,0.25

# 3. 与历史基线对比（基线为上一次的 report.json）
cp reports/report.json reports/baseline.json
python eval_rag.py --threshold 0.2 --baseline reports/baseline.json

# 4. 作为 CI 门禁：指标不达标时退出码为 2
python eval_rag.py --min-hit-rate 0.9 --min-transfer-accuracy 0.85

# 5. 单元测试
python -m unittest test_eval_rag -v
```

常用参数：`--docs`、`--testset`、`--out-dir`、`--top-k`（默认 4）、`--threshold`（默认 0.15）。

## 示例输入输出
**输入样本**（`data/testset.jsonl` 中的两行）：
```json
{"id": "q05", "question": "国内订单多久能送到？", "relevant_sources": ["shipping.md"], "keywords": ["国内仓", "3-7 个工作日"], "should_transfer": false}
{"id": "q17", "question": "今天北京的天气怎么样？", "relevant_sources": [], "keywords": [], "should_transfer": true}
```

**运行输出**（`python eval_rag.py`，已实际运行）：
```json
{
  "total": 20,
  "answerable": 16,
  "should_transfer": 4,
  "hit_rate": 1.0,
  "hit_at_1": 0.9375,
  "mrr": 0.9688,
  "keyword_recall": 0.9375,
  "transfer_accuracy": 0.9,
  "false_transfer_rate": 0.0,
  "missed_transfer_rate": 0.5
}
```

**报告摘录**（完整内容见 `reports/report.md`）：
| 指标 | 数值 |
|---|---|
| 检索命中率 (Hit@k) | 100.00% |
| Top-1 命中率 (Hit@1) | 93.75% |
| 转人工判断准确率 | 90.00% |
| 误转人工率 | 0.00% |
| 漏转人工率 | 50.00% |

**阈值扫描**（`--sweep 0.1,0.15,0.2,0.25`）：
| 阈值 | 转人工准确率 | 误转率 | 漏转率 | Hit@k |
|---|---|---|---|---|
| 0.10 | 90.00% | 0.00% | 50.00% | 100.00% |
| 0.15 | 90.00% | 0.00% | 50.00% | 100.00% |
| 0.20 | 100.00% | 0.00% | 0.00% | 100.00% |
| 0.25 | 95.00% | 6.25% | 0.00% | 100.00% |

## 结果解读
- **检索表现良好，但排序仍有问题**：Hit@k 为 100%，但 Top-1 为 93.75%。q05（"国内订单多久能送到？"）的正确文档排在第 2，且它的分数低于阈值，因此依据关键词覆盖为 0%。这是典型的"找到了但没用上"问题，应优先优化分块或改用语义检索。
- **漏转人工是主要风险**：q19（写诗）、q20（火星仓库）得分约 0.17–0.19，超过了 0.15 的阈值，被错误地回答。字符级检索会因为"你们""吗"等常见字命中无关文档，说明阈值机制本身需要改进（例如停用词过滤或语义检索）。
- **阈值存在取舍**：0.20 在本测试集上转人工准确率为 100%，但**这是在同一批数据上挑出的阈值，存在过拟合风险**。正式使用前应划分开发集与验证集，或收集更多样本后再定阈值。报告中的默认值 0.15 未做调参，保留了真实的问题。
- **测试集规模有限**：20 条样本仅用于演示流程，真实评测建议至少 200 条，并覆盖投诉、多轮追问等场景。

## 接入真实 RAG 系统
流水线只依赖一个接口：`search(query, top_k) -> list[(Chunk, score)]`。以 `customer-service-bot/knowledge_base.py` 为例，可写一个适配器：
```python
import eval_rag as ev
from knowledge_base import KnowledgeBase   # 需要 OPENAI_API_KEY，且会调用 embedding 接口

class KBAdapter:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def search(self, query: str, top_k: int):
        hits = self.kb.search(query, top_k=top_k, threshold=0.0)   # 阈值交由评测流水线统一判断
        return [(ev.Chunk(c.text, c.source), s) for c, s in hits]
```
然后在 `run()` 中把 `LexicalRetriever(chunks)` 替换为 `KBAdapter(kb)` 即可。该接入方式在本仓库中未实际调用 OpenAI 接口运行。

## 局限性
- 默认检索器是字符级 TF-IDF，用于离线复现，并不代表生产环境的语义检索效果。
- 关键词覆盖率只是生成前的依据质量代理，不能替代对最终回答的人工或 LLM 评审。
- 本流水线评测的是"检索 + 阈值转人工"规则，不评测投诉识别、工单路由等能力。
- 测试集为人工构造的演示数据，指标数值仅说明流程可用，不代表真实业务表现。
