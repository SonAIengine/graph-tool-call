<div align="center">

# graph-tool-call

**LLM Agentのためのグラフベースツール検索エンジン**

OpenAPI、MCP、Python関数からツールを収集し、
ツール間の関係をグラフで組織化した上で、**LLMに必要なツールだけを正確に検索して渡します**。

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · [한국어](README-ko.md) · [中文](README-zh_CN.md) · 日本語

</div>

---

## graph-tool-callとは？

LLM Agentが使えるツールは急速に増えています。
ECプラットフォームは**1,200以上のAPIエンドポイント**を、社内システムは複数のサービスにまたがる**500以上の関数**を持つことがあります。

問題はシンプルです。

> **すべてのツール定義を毎回コンテキストウィンドウに入れることはできません。**

一般的な解決策はベクトル検索です。
ツールの説明をエンベディングし、ユーザーリクエストに最も近いツールを見つける方式です。

しかし、実際のツール使用はドキュメント検索とは異なります。

- あるツールは**次のステップのツール**につながります。
- あるツールは**一緒に呼び出す必要**があります。
- あるツールは**read-only**で、あるツールは**destructive**です。
- あるツールは**以前に呼び出したツールの結果を前提**とします。

つまり、**ツールは独立したテキストの断片ではなく、ワークフローを構成する実行単位**です。

**graph-tool-call**はこの点に集中します。
ツールを単なるリストではなく**関係のあるグラフ**として扱い、マルチシグナルハイブリッド検索でLLMに必要なツールだけを渡します。

---

## なぜ必要か？

例えば、ユーザーがこう言ったとします。

> 注文をキャンセルして返金処理して

ベクトル検索は `cancelOrder` を見つけることができます。
しかし、実際の実行には通常以下のフローが必要です。

```text
listOrders → getOrder → cancelOrder → processRefund
````

つまり、重要なのは「似たツール1つ」ではなく、**今必要なツールと次に続くツールまで含めた実行フロー**です。

graph-tool-callはこのような関係をグラフでモデリングします。

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

## コアアイデア

graph-tool-callは以下のパイプラインで動作します。

```text
OpenAPI / MCP / コード → 収集 → 分析 → 組織化 → 検索 → Agent
```

検索段階では複数のシグナルを併用します。

* **BM25**: キーワードマッチング
* **Graph traversal**: 関係ベースの拡張
* **Embedding similarity**: セマンティック類似度
* **MCP annotations**: read-only / destructive / idempotent / open-world ヒント

これらのシグナルは **weighted Reciprocal Rank Fusion (wRRF)** で結合されます。

---

## 主な機能

* **OpenAPI / Swagger / MCP / Python関数**からツール自動収集
* **ツール関係グラフ**の生成と活用
* **BM25 + グラフ + エンベディング + annotation** ベースのハイブリッド検索
* **History-aware retrieval**
* **Cross-encoder reranking**
* **MMR diversity**
* **LLMベースのオントロジー強化**
* **重複ツール検出と統合**
* **HTML / GraphML / Cypher** エクスポート
* **ai-api-lint連携**でspec自動整備

---

## いつ使うべきか？

graph-tool-callは特に以下の状況で効果的です。

* ツール数が多く**すべてをコンテキストに入れることが困難な場合**
* 単純な類似度より**呼び出し順序 / 関係情報**が重要な場合
* **MCP annotation**を反映したretrievalが必要な場合
* 複数のAPI specまたは複数のサービスのツールを**1つの検索レイヤーに統合**する場合
* Agentが以前の呼び出し履歴をもとに**次のツールをより正確に見つけられるようにしたい場合**

---

## インストール

```bash
pip install graph-tool-call                    # core (BM25 + graph)
pip install graph-tool-call[embedding]         # + エンベディング、cross-encoder reranker
pip install graph-tool-call[openapi]           # + OpenAPI YAMLサポート
pip install graph-tool-call[mcp]              # + MCPサーバーモード
pip install graph-tool-call[all]               # すべて
```

<details>
<summary>すべてのextras</summary>

```bash
pip install graph-tool-call[lint]              # + ai-api-lint spec自動修正
pip install graph-tool-call[similarity]        # + rapidfuzz 重複検出
pip install graph-tool-call[visualization]     # + pyvis HTMLグラフエクスポート
pip install graph-tool-call[dashboard]         # + Dash Cytoscape ダッシュボード
pip install graph-tool-call[langchain]         # + LangChain toolアダプター
```

</details>

---

## クイックスタート

### 30秒で体験（インストール不要）

```bash
uvx graph-tool-call search "user authentication" \
  --source https://petstore.swagger.io/v2/swagger.json
```

```text
Query: "user authentication"
Source: https://petstore.swagger.io/v2/swagger.json (19 tools)
Results (5):

  1. getUserByName
     Get user by user name
  2. deleteUser
     Delete user
  3. createUser
     Create user
  4. loginUser
     Logs user into the system
  5. updateUser
     Updated user
```

### Python API

```python
from graph_tool_call import ToolGraph

# 公式Petstore APIからtool graphを生成
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# ツール検索
tools = tg.retrieve("create a new pet", top_k=5)
for t in tools:
    print(f"{t.name}: {t.description}")
```

この仕様では `top_k=5` 基準で **Recall@5 98.3%** を記録しました。

### MCPサーバー（Claude Code、Cursor、Windsurf など）

MCPサーバーとして起動すれば、MCP対応の任意のAgentが設定エントリだけでツール検索を利用できます:

```jsonc
// .mcp.json
{
  "mcpServers": {
    "tool-search": {
      "command": "uvx",
      "args": ["graph-tool-call[mcp]", "serve",
               "--source", "https://api.example.com/openapi.json"]
    }
  }
}
```

サーバーは5つのツールを公開します: `search_tools`、`get_tool_schema`、`list_categories`、`graph_info`、`load_source`。

### SDKミドルウェア（OpenAI / Anthropic）

LLMに送信される前にツールを自動フィルタ — **1行追加、コード変更不要**:

```python
from graph_tool_call import ToolGraph
from graph_tool_call.middleware import patch_openai

tg = ToolGraph.from_url("https://api.example.com/openapi.json")
client = OpenAI()

patch_openai(client, graph=tg, top_k=5)  # ← この1行を追加

# 既存コードはそのまま — 248ツールが入力され、関連する5つだけが送信される
response = client.chat.completions.create(
    model="gpt-4o",
    tools=all_248_tools,
    messages=messages,
)
```

Anthropicでも同様に使用可能:

```python
from graph_tool_call.middleware import patch_anthropic
patch_anthropic(client, graph=tg, top_k=5)
```

---

## ベンチマーク

graph-tool-callは2つのことを検証します。

1. 検索された一部のツールだけをLLMに渡しても性能を維持または改善するか？
2. 検索器自体が正解ツールを上位K件以内に正しく見つけるか？

評価は同一のユーザーリクエストセットに対して以下の構成を比較しました。

* **baseline**: 全ツール定義をLLMにそのまま渡す
* **retrieve-k3 / k5 / k10**: 検索された上位K件のツールだけを渡す
* **+ embedding / + ontology**: retrieve-k5の上にセマンティック検索とLLMベースのオントロジー強化を追加

モデルは **qwen3:4b (4-bit, Ollama)** を使用しました。

### 評価指標

* **Accuracy**: LLMが最終的に正しいツールを選択したか
* **Recall@K**: 検索段階で正解ツールが上位K件以内に含まれたか
* **Avg tokens**: LLMに渡された平均トークン数
* **Token reduction**: baselineに対するトークン削減率

### 結果の概要

* **小規模API (19~50 tools)** ではbaselineもすでに強力です。
  この範囲でgraph-tool-callの主な価値は**精度をほぼ維持しながら64~91%のトークン削減**です。
* **大規模API (248 tools)** ではbaselineが**12%まで崩壊**します。
  一方でgraph-tool-callは**78~82%の精度**を維持します。この場合は最適化ではなく**必須の検索レイヤー**に近いです。

<details>
<summary>全パイプライン比較</summary>

> **指標の解釈**
>
> - **End-to-end Accuracy**: LLMが最終的に正しいツール選択または正解ワークフローの実行に成功したか
> - **Gold Tool Recall@K**: retrieval段階で**正解として指定したcanonical gold tool**が上位K件以内に含まれたか
> - 2つの指標は測定対象が異なるため、常に一致するわけではありません。
> - 特に**代替可能なツール**や**同等のワークフロー**も正解として認める評価では、`End-to-end Accuracy`が`Gold Tool Recall@K`と正確に一致しない場合があります。
> - **baseline**はretrieval段階がないため、`Gold Tool Recall@K`は該当しません。

| Dataset | ツール数 | Pipeline | End-to-end Accuracy | Gold Tool Recall@K | Avg tokens | Token reduction |
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

**この表の読み方**

- **baseline**はretrievalなしで全ツール定義をそのままLLMに入れた結果です。
- **retrieve-k** 系列は検索された一部のツールだけをLLMに渡すため、retrieval品質とLLM選択能力の両方が性能に影響します。
- したがってbaselineの精度が100%だからといって、retrieve-kの精度も100%でなければならないわけではありません。
- `Gold Tool Recall@K`はretrievalがcanonical gold toolをtop-k以内に含めたかを測定し、
  `End-to-end Accuracy`は最終的なタスク実行の成功を測定します。
- このため、代替可能なツールや同等のワークフローを許容する評価では、2つの値が正確に一致しない場合があります。

**核心的な解釈**

- **Petstore / GitHub / Mixed MCP**のようにツール数が少ないまたは中規模の場合、baselineもすでに強力です。
  この範囲でgraph-tool-callの主な価値は**精度を大きく損なわずにトークンを大幅に削減すること**です。
- **Kubernetes core/v1 (248 tools)**のようにツール数が多くなるとbaselineはコンテキスト過負荷で急激に崩壊します。
  一方でgraph-tool-callは検索で候補を絞り**12.0% → 78.0~82.0%**まで性能を回復します。
- 実務的には**retrieve-k5**が最も良いデフォルト値です。
  トークン効率と性能のバランスが良く、大きなデータセットではembedding / ontologyの追加で更なる改善も得られます。

</details>

### 検索器自体の性能: 正解ツールを上位K件以内に見つけるか？

以下の表は**LLMの前の段階**、つまりretrieval自体の品質だけを個別に測定した結果です。
ここでは**BM25 + グラフ探索のみ使用**し、エンベディングとオントロジーは含めていません。

> **指標の解釈**
>
> - **Gold Tool Recall@K**: retrieval段階で**正解として指定したcanonical gold tool**が上位K件以内に含まれたか
> - この表は**最終的なLLM選択精度**ではなく、**検索器が候補群をどれだけうまく構成するか**を示しています。
> - したがってこの表は上記の**End-to-end Accuracy**の表と合わせて読む必要があります。
> - retrievalがgold toolをtop-kに入れても、最終的なLLMが常に正解を選ぶとは限りません。
> - 逆にend-to-end評価で**代替可能なツール**や**同等のワークフロー**を正解として認める場合、最終精度とgold recallは正確に一致しないことがあります。

| Dataset | ツール数 | Gold Tool Recall@3 | Gold Tool Recall@5 | Gold Tool Recall@10 |
|---|---:|---:|---:|---:|
| Petstore | 19 | 93.3% | **98.3%** | 98.3% |
| GitHub | 50 | 87.5% | **87.5%** | 92.5% |
| Mixed MCP | 38 | 93.3% | **96.7%** | 100.0% |
| Kubernetes core/v1 | 248 | 82.0% | **91.0%** | 92.0% |

### この表の読み方

- **Gold Tool Recall@K**はretrievalが正解ツールを候補群に含める能力を示しています。
- 小さなデータセットでは `k=5` だけで高いrecallを確保できます。
- 大きなデータセットでは `k` を増やすほどrecallが上がりますが、その分LLMに渡されるトークンも増加します。
- したがって実際の運用ではrecallだけでなく、**トークンコスト**と**最終的なend-to-end accuracy**を合わせて見る必要があります。

### 核心的な解釈

- **Petstore / Mixed MCP**では `k=5` だけでほぼすべての正解ツールを候補群に含めます。
- **GitHub**では `k=5` と `k=10` の間にrecallの差があり、より高いrecallが必要なら `k=10` が有利な場合があります。
- **Kubernetes core/v1**のようにツール数が大きい場合でも `k=5` ですでに**91.0%**のgold recallを確保しています。
  つまり、検索段階だけでも候補群を大幅に圧縮しながら多くの正解ツールを維持できます。
- 全体的に**`retrieve-k5`が最も実用的なデフォルト値**です。
  `k=3`はより軽量ですが一部の正解を見逃し、`k=10`はrecall向上に対してトークンコストが大きくなる可能性があります。

### 最も難しいケース: エンベディングとオントロジーはいつ役立つか？

最大のデータセットである **Kubernetes core/v1 (248 tools)** で、`retrieve-k5` の上に追加シグナルを付けて比較しました。

| Pipeline | End-to-end Accuracy | Gold Tool Recall@5 | 解釈 |
|---|---:|---:|---|
| retrieve-k5 | 78.0% | 91.0% | BM25 + グラフだけでもstrong baseline |
| + embedding | 80.0% | 94.0% | 意味的に似ているが表現が異なるクエリをより正確に回収 |
| + ontology | **82.0%** | 96.0% | LLMが生成したキーワード/例示クエリが検索品質を大幅に改善 |
| + embedding + ontology | **82.0%** | **98.0%** | 精度は維持、gold recallは最高値 |

### まとめ

- **エンベディング**はBM25が見逃す**セマンティック類似性**を補完します。
- **オントロジー**はツール説明が短かったり非標準的な場合に**検索可能な表現自体を拡張**します。
- 両方を併用するとend-to-end accuracyの向上幅は限定的ですが、**正解ツールを候補群に含める能力は最も強くなります**。

### 自分で再現する

```bash
# 検索品質の測定（高速、LLM不要）
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# パイプラインベンチマーク（LLM比較）
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# ベースラインの保存と比較
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

---

## 基本的な使い方

### OpenAPI / Swaggerから生成

```python
from graph_tool_call import ToolGraph

# ファイルから（JSON / YAML）
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# URLから — Swagger UIの全spec群を自動探索
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# キャッシュ — 一度ビルド、即座に再利用
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",
)

# 対応: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
```

### MCPサーバーツールから生成

```python
from graph_tool_call import ToolGraph

mcp_tools = [
    {
        "name": "read_file",
        "description": "ファイルを読む",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "delete_file",
        "description": "ファイルを永久削除",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]

tg = ToolGraph()
tg.ingest_mcp_tools(mcp_tools, server_name="filesystem")

tools = tg.retrieve("一時ファイルを削除", top_k=5)
```

MCPアノテーション（`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`）は検索シグナルとして活用されます。
参照クエリはread-onlyツールを、削除クエリはdestructiveツールをより優先的にランク付けできます。

### MCPサーバーURLから直接収集

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# Public MCP endpoint
tg.ingest_mcp_server("https://mcp.example.com/mcp")

# ローカル/プライベートMCP endpointは明示的な許可が必要
tg.ingest_mcp_server(
    "http://127.0.0.1:3000/mcp",
    allow_private_hosts=True,
)
```

`ingest_mcp_server()` は HTTP JSON-RPC `tools/list` を呼び出してツール一覧を取得し、
MCPアノテーションを保持したまま graph に登録します。

リモート収集の既定セーフティ:
- private / localhost host は既定でブロック
- リモート応答サイズを制限
- redirect 回数を制限
- 想定外の content-type を拒否

### Python関数から生成

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """ファイルの内容を読む。"""

def write_file(path: str, content: str) -> None:
    """ファイルに内容を書く。"""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
```

type hintからパラメータを、docstringから説明を自動抽出します。

### 手動ツール登録

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

tg.add_tools([
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "都市の現在の天気を取得",
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

## エンベディングベースのハイブリッド検索

BM25 + グラフの上にエンベディングベースのセマンティック検索を追加できます。
OpenAI互換エンドポイントであればほとんど接続可能です。

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers（ローカル）
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / OpenAI互換サーバー
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")

# カスタムcallable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

エンベディング有効化時にウェイトが自動再調整されます。手動チューニングも可能です。

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

---

## 保存とロード

一度ビルドしたグラフはそのまま保存して再利用できます。

```python
# 保存
tg.save("my_graph.json")

# ロード
tg = ToolGraph.load("my_graph.json")

# from_url()のcache=オプションで自動保存/ロード
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

グラフ構造全体（ノード、エッジ、関係タイプ、ウェイト）が保持されます。

エンベディング検索を有効化した状態で保存すると、次も一緒に保持されます。
- embedding vector
- 復元可能な embedding provider 設定
- retrieval weights
- diversity 設定

つまり `ToolGraph.load()` 後に embedding を再構築しなくても、
hybrid retrieval 状態をそのまま復元できます。

---

## 高度な機能

### Cross-Encoderリランキング

Cross-encoderモデルで二次リランキングを実行します。

```python
tg.enable_reranker()  # デフォルト: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("注文キャンセル", top_k=5)
```

wRRFでまず候補を絞った後、`(query, tool_description)` ペアを同時にエンコードしてより精密に順位を調整します。

### MMR多様性

重複する結果を減らし、より多様な候補を確保します。

```python
tg.enable_diversity(lambda_=0.7)
```

### History-aware検索

以前に呼び出したツール名を渡すと、次のステップの検索が改善されます。

```python
# 最初の呼び出し
tools = tg.retrieve("注文を探す")
# → [listOrders, getOrder, ...]

# 二回目の呼び出し
tools = tg.retrieve("次はキャンセルして", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
```

使用済みのツールはダウンランクされ、グラフ上で次のステップに近いツールはアップランクされます。

### wRRFウェイトチューニング

各シグナルの寄与度を調整できます。

```python
tg.set_weights(
    keyword=0.2,     # BM25テキストマッチング
    graph=0.5,       # グラフ探索
    embedding=0.3,   # セマンティック類似度
    annotation=0.2,  # MCPアノテーションマッチング
)
```

### LLM強化オントロジー

LLMでより豊かなツールオントロジーを構築できます。
カテゴリ生成、関係推論、検索キーワード拡張に有用です。

```python
tg.auto_organize(llm="ollama/qwen2.5:7b")
tg.auto_organize(llm=lambda p: my_llm(p))
tg.auto_organize(llm=openai.OpenAI())
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")
```

<details>
<summary>サポートするLLM入力</summary>

| 入力                                   | ラッピングタイプ                      |
| ------------------------------------ | ----------------------------- |
| `OntologyLLM` インスタンス                   | そのまま使用                        |
| `callable(str) -> str`               | `CallableOntologyLLM`         |
| OpenAIクライアント（`chat.completions` 保有） | `OpenAIClientOntologyLLM`     |
| `"ollama/model"`                     | `OllamaOntologyLLM`           |
| `"openai/model"`                     | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"`                    | litellm.completionラッパー         |

</details>

### 重複検出

複数のAPI spec間の重複ツールを検出して統合できます。

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### エクスポートと可視化

```python
# インタラクティブHTML（vis.js）
tg.export_html("graph.html", progressive=True)

# GraphML（Gephi, yEd）
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint統合

[ai-api-lint](https://github.com/SonAIengine/ai-api-lint)でOpenAPI specを収集前に自動整備できます。

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)
```

---

## なぜベクトル検索だけでは足りないのか？

| シナリオ                     | ベクトルのみ             | graph-tool-call                                       |
| ------------------------ | ------------------ | ----------------------------------------------------- |
| *「注文をキャンセルして」*              | `cancelOrder` を返す   | `listOrders → getOrder → cancelOrder → processRefund` |
| *「ファイルを読んで保存」*             | `read_file` を返す     | `read_file` + `write_file` (COMPLEMENTARY関係)         |
| *「古いレコードを削除」*           | "削除"にマッチする任意のツール | destructiveツールを優先ランク                                |
| *「次はキャンセルして」* (history)    | コンテキストなし            | 使用済みツールをダウンランク、次のステップのツールをアップランク                         |
| 複数Swagger specに重複ツール | 結果に重複を含む          | クロスソース自動重複排除                                 |
| 1,200のAPIエンドポイント      | 遅くノイズが多い         | カテゴリ化 + グラフ探索で精密検索                                |

---

## CLIリファレンス

```bash
# ワンライナー検索（収集 + 検索を一度に）
graph-tool-call search "cancel order" --source https://api.example.com/openapi.json
graph-tool-call search "delete user" --source ./openapi.json --scores --json

# MCPサーバー
graph-tool-call serve --source https://api.example.com/openapi.json
graph-tool-call serve --graph prebuilt.json
graph-tool-call serve -s https://api1.com/spec.json -s https://api2.com/spec.json

# グラフのビルドと保存
graph-tool-call ingest https://api.example.com/openapi.json -o graph.json
graph-tool-call ingest ./spec.yaml --embedding --organize

# ビルド済みグラフから検索
graph-tool-call retrieve "query" -g graph.json -k 10

# 分析、可視化、ダッシュボード
graph-tool-call analyze graph.json --duplicates --conflicts
graph-tool-call visualize graph.json -f html
graph-tool-call info graph.json
graph-tool-call dashboard graph.json --port 8050
```

---

## 全APIリファレンス

<details>
<summary><code>ToolGraph</code> メソッド</summary>

| メソッド                            | 説明                          |
| ------------------------------ | --------------------------- |
| `add_tool(tool)`               | 単一ツール追加（フォーマット自動検出）       |
| `add_tools(tools)`             | 複数ツール追加                  |
| `ingest_openapi(source)`       | OpenAPI / Swagger specから収集 |
| `ingest_mcp_tools(tools)`      | MCPツールリストから収集          |
| `ingest_mcp_server(url)`       | MCP HTTPサーバーから直接収集       |
| `ingest_functions(fns)`        | Python callableから収集        |
| `ingest_arazzo(source)`        | Arazzo 1.0.0ワークフロー spec収集  |
| `from_url(url, cache=...)`     | Swagger UIまたはspec URLからビルド |
| `add_relation(src, tgt, type)` | 手動関係追加                    |
| `auto_organize(llm=...)`       | ツール自動分類                  |
| `build_ontology(llm=...)`      | 完全オントロジービルド                  |
| `retrieve(query, top_k=10)`    | ツール検索                     |
| `validate_tool_call(call)`     | ツール呼び出しの検証と自動補正        |
| `assess_tool_call(call)`       | 実行ポリシーに基づく `allow/confirm/deny` 判定 |
| `enable_embedding(provider)`   | ハイブリッドエンベディング検索を有効化            |
| `enable_reranker(model)`       | cross-encoderリランキングを有効化       |
| `enable_diversity(lambda_)`    | MMR多様性を有効化                 |
| `set_weights(...)`             | wRRF融合ウェイトチューニング              |
| `find_duplicates(threshold)`   | 重複ツール検出                  |
| `merge_duplicates(pairs)`      | 検出された重複を統合                   |
| `apply_conflicts()`            | CONFLICTS_WITHエッジ検出/追加     |
| `analyze()`                    | 運用分析レポートを生成                |
| `save(path)` / `load(path)`    | シリアライズ / デシリアライズ                  |
| `export_html(path)`            | インタラクティブHTML可視化エクスポート         |
| `export_graphml(path)`         | GraphMLフォーマットエクスポート             |
| `export_cypher(path)`          | Neo4j Cypher文エクスポート        |
| `dashboard_app()` / `dashboard()` | ダッシュボードを生成 / 起動         |
| `suggest_next(tool, history=...)` | グラフに基づいて次のツールを提案 |

</details>

---

## 機能比較

| 機能      | ベクトルのみのソリューション | graph-tool-call                         |
| ------- | ------------ | --------------------------------------- |
| ツールソース | 手動登録        | Swagger / OpenAPI / MCPから自動収集           |
| 検索方式   | 単純なベクトル類似度    | 多段階ハイブリッド (wRRF + rerank + MMR)         |
| 行動的意味論  | なし           | MCP annotation-aware retrieval          |
| ツール関係 | なし           | 6種類の関係タイプ、自動検出                        |
| 呼び出し順序   | なし           | ステートマシン + CRUD + response→requestデータフロー |
| 重複排除   | なし           | クロスソース重複検出                      |
| オントロジー    | なし           | Auto / LLM-Autoモード                      |
| History | なし           | 使用済みツールダウンランク、次のステップアップランク                   |
| Spec品質 | 良いspecを前提   | ai-api-lint自動修正統合                    |
| LLM依存性 | 必須           | オプション（なくても動く、あればさらに良い）                   |

---

## ドキュメント

| ドキュメント                                          | 説明                                                |
| ------------------------------------------- | ------------------------------------------------- |
| [アーキテクチャ](docs/architecture/overview.md)       | システム概要、パイプラインレイヤー、データモデル                         |
| [WBS](docs/wbs/)                            | 作業分解構造 — Phase 0~4 進捗                        |
| [設計](docs/design/)                          | アルゴリズム設計 — spec正規化、依存関係検出、検索モード、呼び出し順序、オントロジーモード |
| [リサーチ](docs/research/)                       | 競合分析、APIスケールデータ、ECパターン                         |
| [OpenAPIガイド](docs/design/openapi-guide.md) | より良いツールグラフを生成するAPI spec作成法                 |

---

## コントリビューション

コントリビューションを歓迎します。

```bash
# 開発環境セットアップ
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev

# テスト実行
poetry run pytest -v

# リント
poetry run ruff check .
poetry run ruff format --check .

# ベンチマーク実行
python -m benchmarks.run_benchmark -v
```

---

## ライセンス

[MIT](LICENSE)
