<div align="center">

# graph-tool-call

**LLM Agent 工具生命周期管理**

采集、分析、组织、检索。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · [한국어](README-ko.md) · 中文 · [日本語](README-ja.md)

</div>

---

## 问题

LLM Agent 可以使用的工具越来越多。一个电商平台可能有 **1,200+ 个 API endpoint**，一个公司内部系统可能有跨多个服务的 **500+ 个函数**。

但有一个硬性限制：**不可能把所有工具都放进上下文窗口。**

常见的解决方案是向量搜索——将工具描述嵌入向量空间，找到最相似的匹配。虽然可行，但遗漏了重要信息：

> **工具不是孤立存在的，它们之间有关系。**

当用户说 *"取消我的订单并处理退款"*，向量搜索可能找到 `cancelOrder`。但它不知道你需要先调用 `listOrders`（获取订单 ID），之后还需要调用 `processRefund`。这些不仅仅是相似的工具——它们构成了一个**工作流**。

## 解决方案

**graph-tool-call** 将工具间的关系建模为图：

```
                    ┌──────────┐
          PRECEDES  │listOrders│  PRECEDES
         ┌─────────┤          ├──────────┐
         ▼         └──────────┘          ▼
   ┌──────────┐                    ┌───────────┐
   │ getOrder │                    │cancelOrder│
   └──────────┘                    └─────┬─────┘
                                         │ COMPLEMENTARY
                                         ▼
                                  ┌──────────────┐
                                  │processRefund │
                                  └──────────────┘
```

不再将每个工具视为独立的向量，graph-tool-call 能够理解：
- **REQUIRES** — `getOrder` 需要来自 `listOrders` 的 ID
- **PRECEDES** — 必须先查询订单列表才能取消订单
- **COMPLEMENTARY** — 取消和退款经常一起使用
- **SIMILAR_TO** — `getOrder` 和 `listOrders` 功能相关
- **CONFLICTS_WITH** — `updateOrder` 和 `deleteOrder` 不应同时执行

搜索 *"取消订单"* 时，不只是返回 `cancelOrder`，而是返回**完整工作流**：列表查询 → 详情查询 → 取消 → 退款。

## 工作原理

```
OpenAPI/MCP/代码 → [采集] → [分析] → [组织] → [检索] → Agent
                    (转换)  (关系发现) (图)     (混合)
```

**1. 采集（Ingest）** — 指向 Swagger 规范、MCP 服务器或 Python 函数即可。工具自动转换为统一模式。

**2. 分析（Analyze）** — 自动检测关系：路径层级、CRUD 模式、共享 schema、response-parameter 链、状态机。

**3. 组织（Organize）** — 工具被组织成本体图。两种模式：
  - **Auto** — 纯算法（tag、path、CRUD 模式）。无需 LLM。
  - **LLM-Auto** — 通过 LLM 推理增强（Ollama、vLLM、OpenAI）。更好的分类，更丰富的关系。

**4. 检索（Retrieve）** — 结合关键词匹配、图遍历和（可选的）嵌入的混合搜索。无需 LLM 即可良好运行。有 LLM 效果更好。

## 快速开始

```bash
pip install graph-tool-call
```

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# 注册工具（自动检测 OpenAI / Anthropic / LangChain 格式）
tg.add_tools(your_tools_list)

# 定义关系
tg.add_relation("read_file", "write_file", "complementary")

# 检索 — 图扩展自动发现相关工具
tools = tg.retrieve("read a file and save changes", top_k=5)
# → [read_file, write_file, list_dir, ...]
#    write_file 通过 COMPLEMENTARY 关系发现，而非向量相似度
```

### 从 Swagger 自动生成（Phase 1）

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")

# 自动处理：20 个 endpoint → 20 个 tool → 34 个关系 → 3 个分类
# CRUD 依赖、调用顺序、分类分组——全部自动检测。

tools = tg.retrieve("register a new pet and upload photo", top_k=5)
# → [addPet, uploadFile, getPetById, updatePet, findPetsByStatus]
```

## 为什么仅靠向量搜索不够？

| 场景 | 仅向量 | graph-tool-call |
|------|--------|-----------------|
| *"取消我的订单"* | 返回 `cancelOrder` | 返回 `listOrders → getOrder → cancelOrder → processRefund`（完整工作流）|
| *"读取并保存文件"* | 返回 `read_file` | 返回 `read_file` + `write_file`（通过 COMPLEMENTARY 关系）|
| 多个 Swagger 规范中有重复工具 | 结果包含重复 | 跨源自动去重 |
| 1,200 个 API endpoint | 缓慢且噪声多 | 按分类组织，精确图遍历 |

## 3 层搜索：用你所有的

graph-tool-call 设计为**无需 LLM 即可工作**，**有 LLM 则效果更好**：

| 层级 | 需要什么 | 做什么 | 提升 |
|------|---------|--------|------|
| **0** | 什么都不需要 | BM25 关键词 + 图扩展 + RRF 融合 | 基线 |
| **1** | 小型 LLM (1.5B~3B) | + 查询扩展、同义词、翻译 | Recall +15~25% |
| **2** | 大型 LLM (7B+) | + 意图分解、迭代优化 | Recall +30~40% |

即使是在 Ollama 上运行的小模型（`qwen2.5:1.5b`）也能显著提升搜索质量。Tier 0 甚至不需要 GPU。

## 功能对比

| 功能 | 纯向量方案 | graph-tool-call |
|------|----------|-----------------|
| 工具来源 | 手动注册 | Swagger/OpenAPI/MCP 自动采集 |
| 搜索方式 | 平面向量相似度 | 图 + 向量混合 (RRF)，3 层架构 |
| 工具关系 | 无 | 6 种关系类型，自动检测 |
| 调用顺序 | 无 | 状态机 + CRUD 工作流检测 |
| 去重 | 无 | 跨源重复检测 |
| 本体 | 无 | Auto / LLM-Auto 模式 |
| 可视化 | 无 | 图 Dashboard + 手动编辑 |
| LLM 依赖 | 必需 | 可选（无也可用，有则更好）|

## 路线图

| Phase | 内容 | 状态 |
|-------|------|------|
| **0** | 核心图引擎 + 混合检索 | ✅ 完成 (32 tests) |
| **1** | OpenAPI 采集、规范标准化、依赖和顺序检测 | 进行中 |
| **2** | 去重、嵌入、本体模式（Auto/LLM-Auto）、搜索层级 | 计划中 |
| **3** | MCP 采集、Pyvis 可视化、Neo4j 导出、CLI、PyPI 发布 | 计划中 |
| **4** | 交互式 Dashboard（Dash Cytoscape）、手动编辑、社区 | 计划中 |

## 文档

| 文档 | 描述 |
|------|------|
| [架构](docs/architecture/overview.md) | 系统概述、管道层、数据模型 |
| [WBS](docs/wbs/) | 工作分解结构 — Phase 0~4 进展 |
| [设计](docs/design/) | 算法设计 — 规范标准化、依赖检测、搜索模式、调用顺序、本体模式 |
| [研究](docs/research/) | 竞争分析、API 规模数据、电商模式 |
| [OpenAPI 指南](docs/design/openapi-guide.md) | 如何编写能生成更好工具图的 API 规范 |

## 贡献

欢迎贡献！

```bash
# 开发环境设置
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev

# 运行测试
poetry run pytest -v

# 代码检查
poetry run ruff check .
```

## 许可证

[MIT](LICENSE)
