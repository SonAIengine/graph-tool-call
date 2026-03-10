<div align="center">

# graph-tool-call

**面向 LLM Agent 的基于图的工具检索引擎**

从 OpenAPI、MCP、Python 函数收集工具，将工具间关系组织为图，**只将 LLM 需要的工具精准检索并传递**。

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · [한국어](README-ko.md) · 中文 · [日本語](README-ja.md)

</div>

---

## 什么是 graph-tool-call？

LLM Agent 可使用的工具正在飞速增长。
一个电商平台可能有 **1,200 个以上的 API endpoint**，公司内部系统可能跨多个服务拥有 **500 个以上的函数**。

问题很简单。

> **不可能每次都把所有工具定义放进 context window。**

常见的解决方案是向量搜索。
将工具描述嵌入向量空间，找到与用户请求最接近的工具。

但实际的工具使用与文档检索不同。

- 有些工具需要与**下一步工具**串联。
- 有些工具必须**一起调用**。
- 有些工具是 **read-only** 的，有些工具是 **destructive** 的。
- 有些工具**以前一个工具的结果为前提**。

也就是说，**工具不是孤立的文本片段，而是构成工作流的执行单元**。

**graph-tool-call** 正是聚焦于此。
它不把工具视为简单的列表，而是当作**有关系的图**来处理，通过多信号混合检索只将 LLM 所需的工具传递给它。

---

## 为什么需要它？

举个例子，假设用户这样说。

> 取消订单并处理退款

向量搜索可以找到 `cancelOrder`。
但实际执行通常需要以下流程。

```text
listOrders → getOrder → cancelOrder → processRefund
````

也就是说，重要的不是"找到一个相似的工具"，而是**包含当前所需工具和后续工具的完整执行流程**。

graph-tool-call 将这些关系建模为图。

```text
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

---

## 核心思路

graph-tool-call 以如下流水线运行。

```text
OpenAPI / MCP / 代码 → 收集 → 分析 → 组织 → 检索 → Agent
```

检索阶段同时使用多个信号。

* **BM25**: 关键词匹配
* **Graph traversal**: 基于关系扩展
* **Embedding similarity**: 语义相似度
* **MCP annotations**: read-only / destructive / idempotent / open-world 提示

这些信号通过 **weighted Reciprocal Rank Fusion (wRRF)** 融合。

---

## 主要功能

* 从 **OpenAPI / Swagger / MCP / Python 函数** 自动收集工具
* 生成并利用**工具关系图**
* 基于 **BM25 + 图 + 嵌入 + annotation** 的混合检索
* **History-aware retrieval**
* **Cross-encoder reranking**
* **MMR diversity**
* **LLM 增强本体**
* **重复工具检测与合并**
* **HTML / GraphML / Cypher** 导出
* 与 **ai-api-lint 集成**自动清理 spec

---

## 适用场景

graph-tool-call 在以下场景中尤其有效。

* 工具数量多，**难以将全部放入 context** 时
* 相比简单相似度，**调用顺序 / 关系信息**更重要时
* 需要反映 **MCP annotation** 的 retrieval 时
* 需要将多个 API spec 或多个服务的工具**统一为一个检索层**时
* 希望 Agent 根据之前的调用历史**更好地找到下一个工具**时

---

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

---

## 快速开始

### 30 秒示例

```python
from graph_tool_call import ToolGraph

# 从官方 Petstore API 生成 tool graph
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# 工具检索
tools = tg.retrieve("注册新宠物", top_k=5)
for t in tools:
    print(f"{t.name}: {t.description}")
```

预期结果：

```text
addPet: Add a new pet to the store.
updatePet: Update an existing pet.
getPetById: Find pet by ID.
...
```

该规范下 `top_k=5` 基准，**Recall@5 98.3%**。

---

## 基准测试

graph-tool-call 验证两件事。

1. 只把检索到的部分工具给 LLM，性能能否保持或提升？
2. 检索器本身能否将正确工具排进前 K 名？

评价在相同的用户请求集上对比了以下配置。

* **baseline**: 将全部工具定义原样传给 LLM
* **retrieve-k3 / k5 / k10**: 只传递检索到的前 K 个工具
* **+ embedding / + ontology**: 在 retrieve-k5 基础上添加语义检索和 LLM 本体增强

模型使用 **qwen3:4b (4-bit, Ollama)**。

### 评价指标

* **Accuracy**: LLM 最终是否选择了正确的工具
* **Recall@K**: 检索阶段正确工具是否在前 K 名内
* **Avg tokens**: 传递给 LLM 的平均 token 数
* **Token reduction**: 相对 baseline 的 token 节省率

### 一目了然的结果

* **小规模 API (19~50 tools)** 中 baseline 本身就很强。
  在这个区间，graph-tool-call 的主要价值是**在保持接近原有精度的情况下节省 64~91% 的 token**。
* **大规模 API (248 tools)** 中 baseline **崩溃到 12%**。
  而 graph-tool-call 维持 **78~82% 精度**。此时它不是优化，而是**必需的检索层**。

<details>
<summary>全流水线对比</summary>

> **指标解读**
>
> - **End-to-end Accuracy**: LLM 最终是否成功选择了正确的工具或完成了正确的 workflow
> - **Gold Tool Recall@K**: 在 retrieval 阶段，**指定的 canonical gold tool** 是否在前 K 名内
> - 两个指标衡量的对象不同，因此不一定总是一致。
> - 特别是在允许**可替代工具**或**等效 workflow** 也算正确的评价中，`End-to-end Accuracy` 与 `Gold Tool Recall@K` 可能不完全一致。
> - **baseline** 没有 retrieval 阶段，因此 `Gold Tool Recall@K` 不适用。

| Dataset | Tool 数 | Pipeline | End-to-end Accuracy | Gold Tool Recall@K | Avg tokens | Token reduction |
|---|---:|---|---:|---:|---:|---:|
| Petstore | 19 | baseline | 100.0% | — | 1,239 | — |
| Petstore | 19 | retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| Petstore | 19 | retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| Petstore | 19 | retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |
| GitHub | 50 | baseline | 100.0% | — | 3,302 | — |
| GitHub | 50 | retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| GitHub | 50 | retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| GitHub | 50 | retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |
| Mixed MCP | 38 | baseline | 96.7% | — | 2,741 | — |
| Mixed MCP | 38 | retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| Mixed MCP | 38 | retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| Mixed MCP | 38 | retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |
| Kubernetes core/v1 | 248 | baseline | 12.0% | — | 8,192 | — |
| Kubernetes core/v1 | 248 | retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding | 80.0% | 94.0% | 1,728 | 78.9% |
| Kubernetes core/v1 | 248 | retrieve-k5 + ontology | **82.0%** | 96.0% | 1,699 | 79.3% |
| Kubernetes core/v1 | 248 | retrieve-k5 + embedding + ontology | **82.0%** | **98.0%** | 1,924 | 76.5% |

**如何解读此表**

- **baseline** 是不经 retrieval、将全部工具定义直接传给 LLM 的结果。
- **retrieve-k** 系列只将检索到的部分工具传给 LLM，因此 retrieval 质量和 LLM 选择能力共同影响性能。
- 所以 baseline 精度为 100% 并不意味着 retrieve-k 精度也必须是 100%。
- `Gold Tool Recall@K` 衡量的是 retrieval 是否将 canonical gold tool 放入 top-k，
  `End-to-end Accuracy` 衡量的是最终任务执行是否成功。
- 因此在允许可替代工具或等效 workflow 的评价中，两个数值可能不完全一致。

**核心解读**

- **Petstore / GitHub / Mixed MCP** 等工具数较少或中等规模时，baseline 本身就很强。
  在这个区间，graph-tool-call 的主要价值是**在不大幅损失精度的前提下大幅减少 token**。
- **Kubernetes core/v1 (248 tools)** 等工具数较多时，baseline 会因上下文过载而急剧崩溃。
  而 graph-tool-call 通过检索缩小候选范围，将性能从 **12.0% 恢复到 78.0~82.0%**。
- 实践中 **retrieve-k5** 是最佳默认值。
  token 效率与性能平衡良好，在大数据集上添加 embedding / ontology 时还可获得额外提升。

</details>

### 检索器本身性能：正确工具能否进入前 K 名？

下表是 **LLM 之前阶段**，即单独衡量 retrieval 本身质量的结果。
这里**仅使用 BM25 + 图遍历**，不包含嵌入和本体。

> **指标解读**
>
> - **Gold Tool Recall@K**: 在 retrieval 阶段，**指定的 canonical gold tool** 是否在前 K 名内
> - 此表展示的不是**最终 LLM 选择精度**，而是**检索器构建候选集的能力**。
> - 因此此表需要与上面的 **End-to-end Accuracy** 表一起阅读。
> - 即使 retrieval 将 gold tool 放入 top-k，最终 LLM 也不一定总能选对。
> - 反之，在 end-to-end 评价中允许**可替代工具**或**等效 workflow** 算正确的情况下，最终精度与 gold recall 可能不完全一致。

| Dataset | Tool 数 | Gold Tool Recall@3 | Gold Tool Recall@5 | Gold Tool Recall@10 |
|---|---:|---:|---:|---:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub | 50 | 87.5% | **87.5%** | 92.5% |
| Mixed MCP | 38 | 93.3% | **96.7%** | 100.0% |
| Kubernetes core/v1 | 248 | 82.0% | **91.0%** | 92.0% |

### 如何解读此表

- **Gold Tool Recall@K** 展示的是 retrieval 将正确工具包含在候选集中的能力。
- 小数据集中 `k=5` 就能获得很高的 recall。
- 大数据集中增加 `k` 可以提高 recall，但传给 LLM 的 token 也会相应增加。
- 因此实际运营中不仅要看 recall，还要综合考虑 **token 成本**和**最终 end-to-end accuracy**。

### 核心解读

- **Petstore / Mixed MCP** 中 `k=5` 就能将几乎所有正确工具包含在候选集中。
- **GitHub** 中 `k=5` 和 `k=10` 之间存在 recall 差异，如需更高 recall，`k=10` 可能更有利。
- **Kubernetes core/v1** 等工具数较多的情况下，`k=5` 就已获得 **91.0%** 的 gold recall。
  也就是说，仅靠检索阶段就能在大幅压缩候选集的同时保留大部分正确工具。
- 总体而言 **`retrieve-k5` 是最实用的默认值**。
  `k=3` 更轻量但可能遗漏部分正确工具，`k=10` 的 recall 收益相对于 token 成本可能偏大。

### 最难的情况：嵌入和本体何时有帮助？

在最大的数据集 **Kubernetes core/v1 (248 tools)** 上，在 `retrieve-k5` 基础上添加额外信号进行对比。

| Pipeline | End-to-end Accuracy | Gold Tool Recall@5 | 解读 |
|---|---:|---:|---|
| retrieve-k5 | 78.0% | 91.0% | 仅 BM25 + 图即为 strong baseline |
| + embedding | 80.0% | 94.0% | 更好地召回语义相似但表述不同的查询 |
| + ontology | **82.0%** | 96.0% | LLM 生成的关键词/示例查询大幅改善检索质量 |
| + embedding + ontology | **82.0%** | **98.0%** | 精度保持不变，gold recall 达到最高 |

### 总结

- **embedding** 弥补了 BM25 遗漏的**语义相似性**。
- **ontology** 在工具描述简短或不规范时**扩展可检索的表达本身**。
- 两者结合时 end-to-end accuracy 的提升幅度可能有限，但**将正确工具纳入候选集的能力达到最强**。

### 自行复现

```bash
# 检索质量测量（快速，无需 LLM）
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# 流水线基准（LLM 对比）
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# 保存基线并比较
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

---

## 基本用法

### 从 OpenAPI / Swagger 生成

```python
from graph_tool_call import ToolGraph

# 从文件（JSON / YAML）
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# 从 URL — 自动探索 Swagger UI 中的所有 spec 组
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# 缓存 — 一次构建，即时复用
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",
)

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

tools = tg.retrieve("删除临时文件", top_k=5)
```

MCP annotation (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) 被用作检索信号。
查询意图会自动分类：读取查询优先返回 read-only 工具，删除查询优先返回 destructive 工具。

### 从 Python 函数生成

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """读取文件内容。"""

def write_file(path: str, content: str) -> None:
    """写入文件内容。"""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
```

从 type hint 提取参数，从 docstring 提取描述。

### 手动工具注册

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

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

tg.add_relation("get_weather", "get_forecast", "complementary")
```

---

## 基于嵌入的混合检索

在 BM25 + 图遍历基础上可以添加基于嵌入的语义检索。
支持任何 OpenAI 兼容 endpoint。

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers（本地）
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / OpenAI 兼容服务器
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")

# 自定义 callable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

启用嵌入后权重会自动重新调整。也可以手动调优。

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

---

## 保存与加载

一次构建的图可以直接保存并复用。

```python
# 保存
tg.save("my_graph.json")

# 加载
tg = ToolGraph.load("my_graph.json")

# from_url() 中用 cache= 选项自动保存/加载
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

完整图结构（节点、边、关系类型、权重）全部保留。

---

## 高级功能

### Cross-Encoder 重排序

使用 cross-encoder 模型进行二次重排序。

```python
tg.enable_reranker()  # 默认: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("取消订单", top_k=5)
```

先用 wRRF 缩小候选范围，再将 `(query, tool_description)` 对联合编码进行更精确的排序调整。

### MMR 多样性

减少重复结果，获取更多样化的候选。

```python
tg.enable_diversity(lambda_=0.7)
```

### History-aware 检索

传入之前调用过的工具名称可以改善下一步检索。

```python
# 首次调用
tools = tg.retrieve("查找订单")
# → [listOrders, getOrder, ...]

# 第二次调用
tools = tg.retrieve("现在取消", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
```

已使用的工具会降权，图上处于下一步的工具会升权。

### wRRF 权重调优

可以调整各信号的贡献度。

```python
tg.set_weights(
    keyword=0.2,     # BM25 文本匹配
    graph=0.5,       # 图遍历
    embedding=0.3,   # 语义相似度
    annotation=0.2,  # MCP annotation 匹配
)
```

### LLM 增强本体

可以用 LLM 构建更丰富的工具本体。
适用于类别生成、关系推理、检索关键词扩展。

```python
tg.auto_organize(llm="ollama/qwen2.5:7b")
tg.auto_organize(llm=lambda p: my_llm(p))
tg.auto_organize(llm=openai.OpenAI())
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")
```

<details>
<summary>支持的 LLM 输入</summary>

| 输入                                   | 包装类型                         |
| ------------------------------------ | ----------------------------- |
| `OntologyLLM` 实例                   | 直接使用                        |
| `callable(str) -> str`               | `CallableOntologyLLM`         |
| OpenAI 客户端（含 `chat.completions`） | `OpenAIClientOntologyLLM`     |
| `"ollama/model"`                     | `OllamaOntologyLLM`           |
| `"openai/model"`                     | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"`                    | litellm.completion 包装器         |

</details>

### 重复检测

可以跨多个 API spec 检测并合并重复工具。

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### 导出与可视化

```python
# 交互式 HTML (vis.js)
tg.export_html("graph.html", progressive=True)

# GraphML (Gephi, yEd)
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint 集成

使用 [ai-api-lint](https://github.com/SonAIengine/ai-api-lint) 在收集前自动清理 OpenAPI spec。

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)
```

---

## 为什么仅靠向量搜索不够？

| 场景                     | 仅向量搜索             | graph-tool-call                                       |
| ------------------------ | ------------------ | ----------------------------------------------------- |
| *"取消我的订单"*              | 返回 `cancelOrder`   | `listOrders → getOrder → cancelOrder → processRefund` |
| *"读取并保存文件"*             | 返回 `read_file`     | `read_file` + `write_file`（COMPLEMENTARY 关系）         |
| *"删除旧记录"*           | 返回与"删除"匹配的任意工具 | destructive 工具优先排名                                |
| *"现在取消"*（history）    | 无上下文            | 已用工具降权，下一步工具升权                         |
| 多个 Swagger spec 中有重复工具 | 结果包含重复          | 跨源自动去重                                 |
| 1,200 个 API endpoint      | 慢且噪声多         | 按类别组织 + 图遍历精准检索                                |

---

## 完整 API 参考

<details>
<summary><code>ToolGraph</code> 方法</summary>

| 方法                            | 描述                          |
| ------------------------------ | --------------------------- |
| `add_tool(tool)`               | 添加单个工具（格式自动检测）       |
| `add_tools(tools)`             | 添加多个工具                  |
| `ingest_openapi(source)`       | 从 OpenAPI / Swagger spec 收集 |
| `ingest_mcp_tools(tools)`      | 从 MCP tool list 收集          |
| `ingest_functions(fns)`        | 从 Python callable 收集        |
| `ingest_arazzo(source)`        | 收集 Arazzo 1.0.0 工作流 spec  |
| `from_url(url, cache=...)`     | 从 Swagger UI 或 spec URL 构建 |
| `add_relation(src, tgt, type)` | 手动添加关系                    |
| `auto_organize(llm=...)`       | 工具自动分类                  |
| `build_ontology(llm=...)`      | 构建完整本体                  |
| `retrieve(query, top_k=10)`    | 工具检索                     |
| `enable_embedding(provider)`   | 启用混合嵌入检索            |
| `enable_reranker(model)`       | 启用 cross-encoder 重排序       |
| `enable_diversity(lambda_)`    | 启用 MMR 多样性                 |
| `set_weights(...)`             | 调优 wRRF 融合权重              |
| `find_duplicates(threshold)`   | 检测重复工具                  |
| `merge_duplicates(pairs)`      | 合并已检测的重复工具                   |
| `apply_conflicts()`            | 检测/添加 CONFLICTS_WITH 边     |
| `save(path)` / `load(path)`    | 序列化 / 反序列化                  |
| `export_html(path)`            | 导出交互式 HTML 可视化         |
| `export_graphml(path)`         | 导出 GraphML 格式             |
| `export_cypher(path)`          | 导出 Neo4j Cypher 语句        |

</details>

---

## 功能对比

| 功能      | 纯向量方案 | graph-tool-call                         |
| ------- | ------------ | --------------------------------------- |
| 工具来源 | 手动注册        | Swagger / OpenAPI / MCP 自动收集           |
| 检索方式   | 简单向量相似度    | 多阶段混合（wRRF + rerank + MMR）         |
| 行为语义  | 无           | MCP annotation-aware retrieval          |
| 工具关系 | 无           | 6 种关系类型，自动检测                        |
| 调用顺序   | 无           | 状态机 + CRUD + response→request 数据流 |
| 去重   | 无           | 跨源重复检测                      |
| 本体    | 无           | Auto / LLM-Auto 模式                      |
| History | 无           | 已用工具降权，下一步升权                   |
| Spec 质量 | 假设 spec 质量好   | ai-api-lint 自动修复集成                    |
| LLM 依赖 | 必需           | 可选（无也可用，有则更好）                   |

---

## 文档

| 文档                                          | 描述                                                |
| ------------------------------------------- | ------------------------------------------------- |
| [架构](docs/architecture/overview.md)       | 系统概述、流水线层、数据模型                         |
| [WBS](docs/wbs/)                            | 工作分解结构 — Phase 0~4 进展        |
| [设计](docs/design/)                          | 算法设计 — spec 标准化、依赖检测、检索模式、调用顺序、本体模式 |
| [研究](docs/research/)                       | 竞争分析、API 规模数据、电商模式                         |
| [OpenAPI 指南](docs/design/openapi-guide.md) | 如何编写能生成更好工具图的 API 规范                 |

---

## 贡献

欢迎贡献。

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

---

## 许可证

[MIT](LICENSE)
