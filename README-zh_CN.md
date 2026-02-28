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

当 Agent 拥有数百甚至数千个工具时，将所有工具加载到上下文窗口会降低性能。现有解决方案仅使用向量相似度。**graph-tool-call** 将工具之间的**关系**（依赖、调用顺序、互补、冲突）建模为图，实现结构感知检索。

```
OpenAPI/MCP/代码 → [采集] → [分析] → [组织] → [检索] → Agent
                    (转换)  (关系发现) (图)     (混合)
```

## 为什么选择 graph-tool-call？

| 功能 | 纯向量方案 | graph-tool-call |
|------|----------|-----------------|
| 范围 | 仅工具检索 | 完整工具生命周期 |
| 工具来源 | 手动注册 | 从 Swagger/OpenAPI 自动采集 |
| 搜索 | 平面向量相似度 | 图 + 向量混合 (RRF)，3层架构 |
| 关系 | 无 | REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH |
| 去重 | 无 | 跨源重复检测 |
| 依赖 | 无 | 从 API 规范自动检测 |
| 调用顺序 | 无 | 状态机 + CRUD 工作流检测 |
| 本体 | 无 | Auto / LLM-Auto 模式 |

## 快速开始

### 安装

```bash
pip install graph-tool-call
```

### 基本用法

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# 注册工具（自动检测 OpenAI / Anthropic / LangChain 格式）
tg.add_tools(your_tools_list)

# 设置分类和关系
tg.add_category("file_ops", domain="io")
tg.assign_category("read_file", "file_ops")
tg.add_relation("read_file", "write_file", "complementary")

# 查询检索相关工具
tools = tg.retrieve("read a file and save changes", top_k=5)
```

### OpenAPI 采集（Phase 1）

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# 自动发现：CRUD 依赖、调用顺序、分类分组
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
```

## 核心功能

### 采集（Ingest）
将 OpenAPI/Swagger、MCP 服务器、Python 函数和 LangChain/OpenAI/Anthropic 格式的工具自动转换为统一模式。规范标准化层透明处理 Swagger 2.0、OpenAPI 3.0 和 3.1 的差异。

### 分析（Analyze）
自动检测工具间关系：
- **REQUIRES** — 数据依赖（response → parameter）
- **PRECEDES** — 调用顺序（列表查询 → 取消）
- **COMPLEMENTARY** — 配合使用更有效（read ↔ write）
- **SIMILAR_TO** — 功能重叠
- **CONFLICTS_WITH** — 互斥操作

### 组织（Organize）
两种模式构建本体图：
- **Auto** — 基于算法的分类（tag、path、CRUD 模式、embedding 聚类）。无需 LLM。
- **LLM-Auto** — Auto + LLM 增强的关系推理和分类建议（Ollama、vLLM、llama.cpp、OpenAI）。

任何模式的结果都可以在 Dashboard 中可视化和手动编辑。

### 检索（Retrieve）
3层混合搜索架构：
| 层级 | 是否需要 LLM | 方法 |
|------|------------|------|
| 0 | 不需要 | BM25 + 图扩展 + RRF |
| 1 | 小型 (1.5B~3B) | + 查询扩展 |
| 2 | 大型 (7B+) | + 意图分解 |

无需 LLM 即可工作。有 LLM 效果更好。

## 路线图

| Phase | 描述 | 状态 |
|-------|------|------|
| **0** | 核心图 + 检索 | ✅ 完成 (32 tests) |
| **1** | OpenAPI 采集 + 依赖/顺序检测 | 进行中 |
| **2** | 去重 + 嵌入 + 本体/搜索模式 | 计划中 |
| **3** | MCP 采集 + 可视化 + CLI + PyPI | 计划中 |
| **4** | 交互式 Dashboard + 社区 | 计划中 |

## 文档

- [WBS](docs/wbs/) — 工作分解结构
- [架构](docs/architecture/overview.md) — 系统概述和数据模型
- [设计](docs/design/) — 算法设计文档
- [研究](docs/research/) — 竞争分析、API 规模数据

## 贡献

欢迎贡献！贡献指南即将提供。

```bash
# 开发环境设置
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev
poetry run pytest -v
```

## 许可证

[MIT](LICENSE)
