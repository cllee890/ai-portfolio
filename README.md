# AI Portfolio｜AI 工作流 · 提示词工程 · 智能体 · 跨境电商 Skills

> 一个面向 AI 应用开发与跨境电商运营的作品集：包含复杂工作流、Prompt 工程、智能体搭建，以及一人公司可直接复用的电商 Agent Skills。

## 目录

- [项目亮点](#项目亮点)
- [能力矩阵](#能力矩阵)
- [仓库结构](#仓库结构)
- [快速浏览](#快速浏览)
- [Skills 列表](#skills-列表)
- [技术栈](#技术栈)
- [使用方式](#使用方式)
- [联系方式](#联系方式)

## 项目亮点

- **端到端工作流**：从数据输入、竞品参考、文案生成、合规检查、人工审批到 API 发布，多节点串联并保留失败处理与幂等设计。
- **行业化 Prompt 体系**：按角色、背景、任务、约束、输出格式五段式组织，附输出格式规范与上线前校验清单。
- **可落地的智能体**：包含角色设定、任务路由、Function Calling 工具定义，以及带相似度阈值与转人工机制的 RAG 知识库。
- **覆盖一人跨境电商全流程的 Skills**：网站审计、Google Play 搜索优化、竞品研究、店铺助手、SEO 内容策划、营销分析、广告投放与效果分析。
- **强调可验证性**：Skills 中要求结论附证据、数据注明口径与来源，避免臆造数据与夸大宣传。

## 能力矩阵

| 能力方向 | 具体内容 | 目录 |
|---|---|---|
| 复杂工作流 | 多节点串联、图像流处理、插件开发、API 对接 | [`workflows/`](workflows/README.md) |
| Prompt 工程 | 行业定制提示词、输出格式规范优化 | [`prompts/`](prompts/) |
| 智能体搭建 | 角色设定、任务逻辑、工具调用、问答机器人、通用 RAG 知识库 | [`agents/`](agents/customer-service-bot/README.md) |
| 跨境电商 Skills | 网站审计、搜索优化、竞品研究、店铺助手、内容策划、营销与广告 | [`skills/`](skills/) |

## 仓库结构

```
.
├── README.md                  # 项目首页（本文件）
├── workflows/                 # 复杂工作流示例
│   ├── multi-node-pipeline/   # 多节点串联：选品 → 文案 → 质检 → 发布
│   ├── image-pipeline/        # 图像流：商品图批量处理
│   ├── api-integration/       # API 对接：分页、限流重试、增量同步
│   └── plugin-development/    # 插件开发：manifest + handler 规范
├── prompts/                   # Prompt 工程
│   ├── industry-prompt-templates.md   # 行业提示词模板
│   └── output-format-spec.md          # 输出格式规范与校验清单
├── agents/                    # 智能体
│   └── customer-service-bot/  # 问答机器人 + RAG 知识库 + 工具调用
└── skills/                    # 跨境电商 Agent Skills（每个目录含 SKILL.md）
```

## 快速浏览

| 想看什么 | 建议阅读 |
|---|---|
| 工作流怎么串联、失败怎么处理 | [`workflows/multi-node-pipeline/README.md`](workflows/multi-node-pipeline/README.md) |
| 图像处理的批量代码示例 | [`workflows/image-pipeline/README.md`](workflows/image-pipeline/README.md) |
| 提示词如何按行业定制 | [`prompts/industry-prompt-templates.md`](prompts/industry-prompt-templates.md) |
| 输出格式如何规范化 | [`prompts/output-format-spec.md`](prompts/output-format-spec.md) |
| 智能体的设计与 RAG 实现 | [`agents/customer-service-bot/README.md`](agents/customer-service-bot/README.md) |
| 跨境电商 Skill 的写法 | [`skills/website-audit/SKILL.md`](skills/website-audit/SKILL.md) |

## Skills 列表

| Skill | 用途 |
|---|---|
| [website-audit](skills/website-audit/SKILL.md) | 独立站审计：技术、性能、SEO 结构、转化路径、合规 |
| [google-play-search-optimization](skills/google-play-search-optimization/SKILL.md) | Google Play 应用搜索优化（ASO）：关键词、文案与 A/B 测试 |
| [competitor-research](skills/competitor-research/SKILL.md) | 竞品研究：定位、价格、流量、评价与差异化机会 |
| [store-assistant](skills/store-assistant/SKILL.md) | 店铺运营助手：商品文案、客服话术、差评回复、日常检查 |
| [seo-content-planning](skills/seo-content-planning/SKILL.md) | SEO 内容策划：主题簇、内容日历、文章大纲与内链 |
| [marketing-analysis](skills/marketing-analysis/SKILL.md) | 营销数据分析：指标拆解、渠道对比、增长诊断 |
| [ad-campaign-planning](skills/ad-campaign-planning/SKILL.md) | 广告投放方案：盈亏平衡 ROAS、预算分配、测试计划 |
| [ad-performance-analysis](skills/ad-performance-analysis/SKILL.md) | 广告效果分析：漏斗诊断、扩量/优化/停投决策规则 |

## 技术栈

- **工作流与自动化**：多节点编排、REST API、Webhook、幂等与重试设计
- **大模型应用**：Prompt 工程、Function Calling、结构化输出（JSON）
- **检索增强（RAG）**：文档切分、向量检索、相似度阈值、转人工机制
- **编程语言**：Python（Pillow、requests、numpy、OpenAI SDK）
- **电商领域**：独立站运营、Google Play 商店、SEO、广告投放与数据分析

## 使用方式

1. 浏览对应目录下的 README 或 SKILL.md 了解设计思路。
2. Skills 可按 Agent Skills 规范直接放入支持该格式的智能体平台中使用，并替换其中的 `{{变量}}` 占位内容。
3. 代码示例仅用于演示设计思路，使用前请补充真实的密钥、接口地址与业务规则，并自行做安全审查。

> 所有示例中的数据、账号与密钥均已脱敏，不代表任何真实店铺或平台的数据。

## 联系方式

如需交流合作或查看更多项目细节，欢迎通过 GitHub Issues 或个人主页联系。
