<div align="center">

# graph-tool-call

**基于图的 LLM Agent 工具检索引擎**

采集、分析、组织、检索。

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
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

**graph-tool-call** 将工具间的关系建模为图，并通过多信号混合管道进行检索：

```
OpenAPI/MCP/代码 → [采集] → [分析] → [组织] → [检索] → Agent
                    (转换)  (关系发现) (图)     (wRRF 混合)
```

**4-source wRRF 融合**: BM25 关键词匹配 + 图遍历 + 嵌入相似度 + MCP annotation 评分 — 通过 weighted Reciprocal Rank Fusion 组合。

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

## 基准测试

我们测试了 graph-tool-call 是否真的能帮助 LLM 选对工具。测试方式：

1. 给 LLM 一个用户请求（例如 *"列出 default 命名空间中的所有 pod"*）
2. 提供一组工具定义让它选择
3. 检查它是否选择了正确的工具

我们测量两个指标：

| 指标 | 测量什么 | 例子 |
|------|---------|------|
| **准确率 (Accuracy)** | LLM 选对了正确的工具吗？ | "列出 pod" → LLM 选了 `listCoreV1NamespacedPod` → 正确 |
| **Recall@K** | 正确的工具出现在候选列表中了吗？ | `listCoreV1NamespacedPod` 在前 5 个结果中 → 是的 |

> **为什么两个都重要**: 如果正确工具不在候选中（低 Recall），LLM 再聪明也选不出来。如果在候选中但 LLM 选错了（低 Accuracy），那是 LLM 选择的问题，不是检索的问题。

### 核心发现：工具太多时 LLM 会崩溃

| API | 工具数 | 工具提供方式 | 准确率 | Recall@5 |
|-----|:-----:|------------|:------:|:--------:|
| Petstore | 19 | 全部 19 个（不过滤） | 100% | — |
| GitHub | 50 | 全部 50 个（不过滤） | 100% | — |
| MCP Servers | 38 | 全部 38 个（不过滤） | 96.7% | — |
| **Kubernetes** | **248** | **全部 248 个（不过滤）** | **12%** | — |
| | | **graph-tool-call 筛选前 5 个** | **78%** | **91%** |
| | | **+ 嵌入** | **80%** | **94%** |
| | | **+ 本体** | **82%** | **96%** |
| | | **+ 两者** | **82%** | **98%** |

**Kubernetes 发生了什么？**
- **Baseline（传入全部 248 个工具）**: LLM 一次看到 248 个工具定义。信息过载导致混乱，88% 的情况选错 → **准确率 12%**。（Recall 技术上是 100%——正确答案确实*在*列表里，但 LLM 找不到它。）
- **使用 graph-tool-call**: 过滤到 5 个相关工具。LLM 正确率达到 **78–82%**。这不是优化——是**能用和不能用的区别**。

**50 个以下**: LLM 自己就能处理好。graph-tool-call 仍然能节省 **64–88% 的 token**（更快、更便宜）。

> 模型: qwen3:4b (4-bit 量化, Ollama)。每个数据集 50 个测试查询。所有规范公开——[自行复现](#自行复现)。

<details>
<summary>各数据集详细结果</summary>

**Petstore** (19 tools, 20 queries)

| Pipeline | 准确率 | Recall@K | 平均 Token | Token 节省 |
|----------|:------:|:--------:|:---------:|:---------:|
| baseline (全部工具) | 100.0% | 100.0% | 1,239 | — |
| retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |

**GitHub** (50 tools, 40 queries)

| Pipeline | 准确率 | Recall@K | 平均 Token | Token 节省 |
|----------|:------:|:--------:|:---------:|:---------:|
| baseline (全部工具) | 100.0% | 100.0% | 3,302 | — |
| retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |

**Mixed MCP** (38 tools, 30 queries)

| Pipeline | 准确率 | Recall@K | 平均 Token | Token 节省 |
|----------|:------:|:--------:|:---------:|:---------:|
| baseline (全部工具) | 96.7% | 100.0% | 2,741 | — |
| retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |

**Kubernetes core/v1** (248 tools, 50 queries)

| Pipeline | 准确率 | Recall@K | 平均 Token | Token 节省 |
|----------|:------:|:--------:|:---------:|:---------:|
| baseline (全部工具) | 12.0% | 100.0% | 8,192 | — |
| retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| + 嵌入 | 80.0% | 94.0% | 1,728 | 78.9% |
| + 本体 | **82.0%** | 96.0% | 1,699 | 79.3% |
| + 两者 | **82.0%** | **98.0%** | 1,924 | 76.5% |

</details>

### 嵌入 + 本体什么时候有帮助？

小规模 API（< 50 工具），BM25 + 图遍历就够了。大规模 API 中，嵌入和本体才能产生实质差异。在 Kubernetes（248 工具）上测试：

| Pipeline | 准确率 | Recall@5 | 增加的功能 |
|----------|:------:|:--------:|----------|
| BM25 + 图遍历 | 78% | 91% | 关键词匹配 + 图邻居遍历 |
| + 嵌入 | 80% | 94% | 语义相似度（捕获 BM25 遗漏的同义词） |
| + 本体 | **82%** | 96% | LLM 生成的关键词 + 示例查询 |
| **+ 两者** | **82%** | **98%** | 嵌入 + 本体互补 |

嵌入: OpenAI `text-embedding-3-small`。本体: `gpt-4o-mini`。

### 自行复现

```bash
# 检索质量测量（快速，无需 LLM）
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# 完整 Pipeline 基准（需要 Ollama）
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# 保存基线后对比变更
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

## 安装

```bash
pip install graph-tool-call                    # core (BM25 + graph)
pip install graph-tool-call[embedding]         # + 嵌入, cross-encoder reranker
pip install graph-tool-call[openapi]           # + OpenAPI YAML 支持
pip install graph-tool-call[all]               # 全部
```

<details>
<summary>所有 extras</summary>

```bash
pip install graph-tool-call[lint]              # + ai-api-lint spec 自动修复
pip install graph-tool-call[similarity]        # + rapidfuzz 重复检测
pip install graph-tool-call[visualization]     # + pyvis HTML 图导出
pip install graph-tool-call[langchain]         # + LangChain tool 适配器
```

</details>

## 快速开始

### 30 秒示例

```python
from graph_tool_call import ToolGraph

# 从官方 Petstore API 生成 tool graph
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",  # 本地保存 → 下次加载时即时使用
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# 工具检索 — 该规范下 Recall@5 98.3%
tools = tg.retrieve("注册新宠物", top_k=5)
for t in tools:
    print(f"  {t.name}: {t.description}")
# → addPet: Add a new pet to the store.
#   updatePet: Update an existing pet.
#   getPetById: Find pet by ID.
#   ...图扩展获取完整的 CRUD 工作流
```

### 从 Swagger / OpenAPI 生成

```python
from graph_tool_call import ToolGraph

# 从文件 (JSON/YAML)
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# 从 URL — 自动探索 Swagger UI 中的所有 spec 组
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# 缓存 — 一次构建，即时复用
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",  # 首次调用: fetch + build + save
)                          # 之后: 从文件加载 (无需网络)

# 支持: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
```

### 从 MCP 服务器工具生成

```python
from graph_tool_call import ToolGraph

mcp_tools = [
    {
        "name": "read_file",
        "description": "读取文件",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "delete_file",
        "description": "永久删除文件",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]

tg = ToolGraph()
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

# Annotation-aware: "删除文件" → 破坏性工具排名更高
tools = tg.retrieve("删除临时文件", top_k=5)
```

MCP annotation (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) 被用作检索信号。查询意图自动分类并与工具 annotation 匹配——读取查询优先返回 read-only 工具，删除查询优先返回 destructive 工具。

### 从 Python 函数生成

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """读取文件内容。"""

def write_file(path: str, content: str) -> None:
    """写入文件内容。"""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# 从 type hint 提取参数，从 docstring 提取描述
```

### 手动注册工具

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# OpenAI function-calling 格式 — 自动检测
tg.add_tools([
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询城市当前天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    },
])

# 手动定义关系
tg.add_relation("get_weather", "get_forecast", "complementary")
```

## 嵌入 (混合检索)

在 BM25 + 图遍历基础上添加基于嵌入的语义检索。支持任何 OpenAI 兼容 endpoint。

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers (本地, 无需 API key)
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / OpenAI 兼容服务器
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")  # URL@model 格式

# 自定义 callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

启用嵌入后权重会自动重新调整。也可以手动调优:

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

## 保存 & 加载

一次构建，随处复用。完整图结构（节点、边、关系类型、权重）全部保留。

```python
# 保存
tg.save("my_graph.json")

# 加载
tg = ToolGraph.load("my_graph.json")

# from_url() 中用 cache= 选项自动保存/加载
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

## 高级功能

### Cross-Encoder 重排序

使用 cross-encoder 模型进行二次重排序。将 `(query, tool_description)` 对联合编码，比独立嵌入比较更精确。

```python
tg.enable_reranker()  # 默认: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("取消订单", top_k=5)
# wRRF 先排序 → cross-encoder 重新评分
```

### MMR 多样性

Maximal Marginal Relevance 重排序减少重复结果。

```python
tg.enable_diversity(lambda_=0.7)  # 0.7 = 以相关性为主 + 适度多样性
```

### History-Aware 检索

传入之前调用过的工具名称可改善上下文。已使用的工具会降权，图邻居作为种子扩展。

```python
# 首次调用
tools = tg.retrieve("查找订单")
# → [listOrders, getOrder, ...]

# 第二次调用 — history-aware
tools = tg.retrieve("现在取消", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
#    listOrders/getOrder 降权, cancelOrder 因图邻近性上升
```

### wRRF 权重调优

调整各评分来源的 weighted Reciprocal Rank Fusion 权重:

```python
tg.set_weights(
    keyword=0.2,     # BM25 文本匹配
    graph=0.5,       # 图遍历 (基于关系)
    embedding=0.3,   # 语义相似度
    annotation=0.2,  # MCP annotation 匹配
)
```

### LLM 增强本体

使用 LLM 构建更丰富的工具本体。类别、关系推理、检索关键词生成 (对非英语工具描述特别有用)。

```python
# 以下均可使用 — wrap_llm() 自动检测
tg.auto_organize(llm="ollama/qwen2.5:7b")           # 字符串简写
tg.auto_organize(llm=lambda p: my_llm(p))            # callable
tg.auto_organize(llm=openai.OpenAI())                # OpenAI 客户端
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")    # 经由 litellm
```

<details>
<summary>支持的 LLM 输入</summary>

| 输入 | 包装类型 |
|------|----------|
| `OntologyLLM` 实例 | 直接使用 |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAI 客户端 (含 `chat.completions`) | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completion 包装器 |

</details>

### 重复检测

跨多个 API spec 检测并合并重复工具:

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### 导出 & 可视化

```python
# 交互式 HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (Gephi, yEd 用)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint 集成

使用 [ai-api-lint](https://github.com/SonAIengine/ai-api-lint) 在采集前自动修复 OpenAPI spec:

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)  # 采集时自动修复
```

## 为什么仅靠向量搜索不够？

| 场景 | 仅向量 | graph-tool-call |
|------|--------|-----------------|
| *"取消我的订单"* | 返回 `cancelOrder` | `listOrders → getOrder → cancelOrder → processRefund` (完整工作流) |
| *"读取并保存文件"* | 返回 `read_file` | `read_file` + `write_file` (COMPLEMENTARY 关系) |
| *"删除旧记录"* | 返回与"删除"匹配的任意工具 | 破坏性工具优先排名 (annotation-aware) |
| *"现在取消"* (history) | 无上下文，返回相同结果 | 已用工具降权，下一步工具上升 |
| 多个 Swagger spec 中有重复工具 | 结果包含重复 | 跨源自动去重 |
| 1,200 个 API endpoint | 缓慢且噪声多 | 按类别组织，精确图遍历 |

## 完整 API 参考

<details>
<summary>ToolGraph 方法</summary>

| 方法 | 描述 |
|------|------|
| `add_tool(tool)` | 添加单个工具 (格式自动检测) |
| `add_tools(tools)` | 添加多个工具 |
| `ingest_openapi(source)` | 从 OpenAPI/Swagger spec 采集 |
| `ingest_mcp_tools(tools)` | 从 MCP tool list 采集 |
| `ingest_functions(fns)` | 从 Python callable 采集 |
| `ingest_arazzo(source)` | 采集 Arazzo 1.0.0 工作流 spec |
| `from_url(url, cache=...)` | 从 Swagger UI 或 spec URL 构建 |
| `add_relation(src, tgt, type)` | 手动添加关系 |
| `auto_organize(llm=...)` | 工具自动分类 |
| `build_ontology(llm=...)` | 构建完整本体 |
| `retrieve(query, top_k=10)` | 工具检索 |
| `enable_embedding(provider)` | 启用混合嵌入检索 |
| `enable_reranker(model)` | 启用 cross-encoder 重排序 |
| `enable_diversity(lambda_)` | 启用 MMR 多样性 |
| `set_weights(...)` | 调优 wRRF 融合权重 |
| `find_duplicates(threshold)` | 检测重复工具 |
| `merge_duplicates(pairs)` | 合并已检测的重复工具 |
| `apply_conflicts()` | 检测/添加 CONFLICTS_WITH 边 |
| `save(path)` / `load(path)` | 序列化 / 反序列化 |
| `export_html(path)` | 导出交互式 HTML 可视化 |
| `export_graphml(path)` | 导出 GraphML 格式 |
| `export_cypher(path)` | 导出 Neo4j Cypher 语句 |

</details>

## 功能对比

| 功能 | 纯向量方案 | graph-tool-call |
|------|----------|-----------------|
| 工具来源 | 手动注册 | Swagger/OpenAPI/MCP 自动采集 |
| 检索方式 | 简单向量相似度 | 多阶段混合 (wRRF + rerank + MMR) |
| 行为语义 | 无 | MCP annotation-aware retrieval |
| 工具关系 | 无 | 6 种关系类型，自动检测 |
| 调用顺序 | 无 | 状态机 + CRUD + response→request 数据流 |
| 去重 | 无 | 跨源重复检测 |
| 本体 | 无 | Auto / LLM-Auto 模式 (任意 LLM) |
| History | 无 | 已用工具降权，下一步上升 |
| Spec 质量 | 假设 spec 质量好 | ai-api-lint 自动修复集成 |
| LLM 依赖 | 必需 | 可选 (无也可用，有则更好) |

## 文档

| 文档 | 描述 |
|------|------|
| [架构](docs/architecture/overview.md) | 系统概述、管道层、数据模型 |
| [WBS](docs/wbs/) | 工作分解结构 — Phase 0~4 进展 |
| [设计](docs/design/) | 算法设计 — 规范标准化、依赖检测、检索模式、调用顺序、本体模式 |
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
poetry run ruff format --check .

# 运行基准测试
python -m benchmarks.run_benchmark -v
```

## 许可证

[MIT](LICENSE)
