# 跨境电商问答机器人（RAG + 工具调用）

## 角色设定
- 身份：{{店铺名}} 智能客服
- 语气：专业、耐心、简洁；不确定时明确转人工
- 边界：不承诺退款金额、不编造物流时效

## 任务逻辑
```
用户问题
  ├─ 意图识别：物流 / 退换货 / 商品咨询 / 投诉 / 其他
  ├─ 需要实时数据？ → 调用工具（订单查询 API）
  ├─ 政策类问题？   → RAG 检索知识库（Top-K=4，相似度<0.6 则转人工）
  ├─ 投诉/高风险   → 直接转人工并生成工单摘要
  └─ 生成回复 → 附引用来源 → 记录日志
```

## 工具定义（Function Calling）
```json
{
  "name": "query_order",
  "description": "根据订单号查询物流状态",
  "parameters": {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"]
  }
}
```

## 知识库构建
1. 文档切分：按标题层级切分，单块 300–500 字，保留 overlap 50 字
2. 向量化：text-embedding 模型；元数据记录来源、更新时间、市场
3. 检索：向量检索 + 关键词混合检索，结果重排序
4. 更新：政策变更后增量重建对应文档

## 评测指标
- 回答准确率（人工抽检 100 条）
- 检索命中率（Top-4 包含正确段落的比例）
- 转人工率与误转率

## 运行说明
本目录包含两部分：本 README 为智能体设计说明，`knowledge_base.py` 为 RAG 核心示例代码。

**环境要求**：Python 3.10+（代码使用 `X | None` 类型语法）。
```bash
pip install openai numpy
export OPENAI_API_KEY="你的 API Key"    # 不要写入代码或仓库
```

**知识库构建与问答**（示例脚本 `run_demo.py`，与 `knowledge_base.py` 放在同一目录）：
```python
from knowledge_base import KnowledgeBase, answer

kb = KnowledgeBase()
kb.add_documents({
    "refund-policy.md": "退款政策：签收后7天内可申请退款，退款原路返回。",
    "shipping.md": "物流说明：一般3-7个工作日送达，可在订单页查询物流。",
})
for q in ["我想申请退款", "今天天气怎么样"]:
    print(q, "->", answer(kb, q))
```
运行：`python run_demo.py`

**接入注意**：
- 返回值 `TRANSFER_TO_HUMAN` 表示无可靠依据，应由业务层转人工，而不是直接展示给用户。
- `threshold`（默认 0.6）与 `top_k`（默认 4）可在 `search` 中调整。
- 订单查询等实时工具调用不在 `knowledge_base.py` 中，需按上方"工具定义"另行实现。

## 示例输入输出
**切分与检索示例**（使用本地桩向量函数验证，不调用 OpenAI）：

输入知识库：2 篇文档，切分后得到 2 个文本块（`refund-policy.md` 36 字，`shipping.md` 27 字）。

| 用户问题 | 检索结果 | 处理方式 |
|---|---|---|
| 我想申请退款 | `refund-policy.md`（相似度 1.0） | 基于该片段生成回复并标注来源 |
| 物流多久到 | `shipping.md`（相似度 1.0） | 基于该片段生成回复并标注来源 |
| 今天天气怎么样 | 无片段达到阈值 | 返回 `TRANSFER_TO_HUMAN` |

**真实模型输出示例**（示意，实际文字随模型版本变化）：
```text
我想申请退款 -> 根据退款政策，签收后7天内可申请退款，退款将原路返回。[来源:refund-policy.md]
今天天气怎么样 -> TRANSFER_TO_HUMAN
```
