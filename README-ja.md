<div align="center">

# graph-tool-call

**LLM Agentのためのグラフベースツール検索エンジン**

収集、分析、組織化、検索。

[![PyPI](https://img.shields.io/pypi/v/graph-tool-call.svg)](https://pypi.org/project/graph-tool-call/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml/badge.svg)](https://github.com/SonAIengine/graph-tool-call/actions/workflows/ci.yml)

[English](README.md) · [한국어](README-ko.md) · [中文](README-zh_CN.md) · 日本語

</div>

---

## 課題

LLM Agentが使えるツールはどんどん増えています。ECプラットフォームは**1,200以上のAPIエンドポイント**を持ち、社内システムは複数のサービスにまたがる**500以上の関数**を持つことがあります。

しかし限界があります：**すべてのツールをコンテキストウィンドウに入れることはできません。**

一般的な解決策はベクトル検索です——ツールの説明を埋め込み、最も近いマッチを見つけます。機能はしますが、重要なものを見逃しています：

> **ツールは孤立して存在しません。互いに関係があります。**

ユーザーが*「注文をキャンセルして返金処理して」*と言った時、ベクトル検索は `cancelOrder` を見つけるかもしれません。しかし、注文IDを取得するために先に `listOrders` を呼ぶ必要があること、その後に `processRefund` が来るべきことは分かりません。これらは単に似たツールではなく、**ワークフロー**を形成しています。

## ソリューション

**graph-tool-call** はツール間の関係をグラフとしてモデル化し、マルチシグナルハイブリッドパイプラインで検索します：

```
OpenAPI/MCP/コード → [収集] → [分析] → [組織化] → [検索] → Agent
                      (変換)  (関係発見) (グラフ)   (wRRF ハイブリッド)
```

**4-source wRRF 融合**: BM25キーワードマッチング + グラフ探索 + エンベディング類似度 + MCPアノテーションスコアリング — weighted Reciprocal Rank Fusionで結合。

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

## なぜベクトル検索だけでは足りないのか？

| シナリオ | ベクトルのみ | graph-tool-call |
|----------|-----------|-----------------|
| *「注文をキャンセルして」* | `cancelOrder` を返す | `listOrders → getOrder → cancelOrder → processRefund`（完全なワークフロー）|
| *「ファイルを読んで保存」* | `read_file` を返す | `read_file` + `write_file`（COMPLEMENTARY関係）|
| *「古いレコードを削除」* | "削除"にマッチする任意のツール | destructiveツールが上位ランク（annotation-aware）|
| *「次はキャンセルして」*（history） | コンテキストなし、同じ結果 | 使用済みツールをダウンランク、次のステップのツールをアップランク |
| 複数Swagger仕様に重複ツール | 結果に重複を含む | クロスソース自動重複排除 |
| 1,200のAPIエンドポイント | 遅くノイズが多い | カテゴリに整理、正確なグラフ探索 |

## インストール

```bash
pip install graph-tool-call                    # core (BM25 + graph)
pip install graph-tool-call[embedding]         # + エンベディング、cross-encoder reranker
pip install graph-tool-call[openapi]           # + OpenAPI YAMLサポート
pip install graph-tool-call[all]               # すべて
```

<details>
<summary>すべてのextras</summary>

```bash
pip install graph-tool-call[lint]              # + ai-api-lint spec自動修正
pip install graph-tool-call[similarity]        # + rapidfuzz 重複検出
pip install graph-tool-call[visualization]     # + pyvis HTMLグラフエクスポート
pip install graph-tool-call[langchain]         # + LangChain toolアダプター
```

</details>

## クイックスタート

### 30秒の例

```python
from graph_tool_call import ToolGraph

# 公式Petstore APIからtool graphを生成
tg = ToolGraph.from_url(
    "https://petstore3.swagger.io/api/v3/openapi.json",
    cache="petstore.json",  # ローカル保存 → 次回ロード時に即使用
)

print(tg)
# → ToolGraph(tools=19, nodes=22, edges=100)

# ツール検索 — この仕様でRecall@5 98.3%
tools = tg.retrieve("新しいペットを登録", top_k=5)
for t in tools:
    print(f"  {t.name}: {t.description}")
# → addPet: Add a new pet to the store.
#   updatePet: Update an existing pet.
#   getPetById: Find pet by ID.
#   ...グラフ展開が完全なCRUDワークフローを取得
```

### Swagger / OpenAPIから生成

```python
from graph_tool_call import ToolGraph

# ファイルから（JSON/YAML）
tg = ToolGraph()
tg.ingest_openapi("path/to/openapi.json")

# URLから — Swagger UIの全spec群を自動探索
tg = ToolGraph.from_url("https://api.example.com/swagger-ui/index.html")

# キャッシュ — 一度ビルド、即座に再利用
tg = ToolGraph.from_url(
    "https://api.example.com/swagger-ui/index.html",
    cache="my_api.json",  # 初回: fetch + build + save
)                          # 以降: ファイルからロード（ネットワーク不要）

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

# Annotation-aware: "ファイル削除" → destructiveツールが上位ランク
tools = tg.retrieve("一時ファイルを削除", top_k=5)
```

MCPアノテーション（`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`）が検索シグナルとして活用されます。クエリの意図が自動分類され、ツールのアノテーションとマッチング — 読み取りクエリはread-onlyツールを、削除クエリはdestructiveツールを優先します。

### Python関数から生成

```python
from graph_tool_call import ToolGraph

def read_file(path: str) -> str:
    """ファイルの内容を読む。"""

def write_file(path: str, content: str) -> None:
    """ファイルに内容を書く。"""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# type hintからパラメータ、docstringから説明を自動抽出
```

### 手動ツール登録

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# OpenAI function-callingフォーマット — 自動検出
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

# 関係を手動定義
tg.add_relation("get_weather", "get_forecast", "complementary")
```

## エンベディング（ハイブリッド検索）

BM25 + グラフの上にエンベディングベースのセマンティック検索を追加。OpenAI互換エンドポイントならどこでも使用可能。

```bash
pip install graph-tool-call[embedding]
```

```python
# Sentence-transformers（ローカル、APIキー不要）
tg.enable_embedding("sentence-transformers/all-MiniLM-L6-v2")

# OpenAI
tg.enable_embedding("openai/text-embedding-3-large")

# Ollama
tg.enable_embedding("ollama/nomic-embed-text")

# vLLM / llama.cpp / OpenAI互換サーバー
tg.enable_embedding("vllm/Qwen/Qwen3-Embedding-0.6B")
tg.enable_embedding("vllm/model@http://gpu-box:8000/v1")
tg.enable_embedding("llamacpp/model@http://192.168.1.10:8080/v1")
tg.enable_embedding("http://localhost:8000/v1@my-model")  # URL@modelフォーマット

# カスタムcallable
tg.enable_embedding(lambda texts: my_embed_fn(texts))
```

エンベディング有効化時にウェイトが自動再調整されます。手動チューニングも可能：

```python
tg.set_weights(keyword=0.1, graph=0.4, embedding=0.5)
```

## 保存 & ロード

一度ビルドすればどこでも再利用。グラフ構造全体（ノード、エッジ、関係タイプ、ウェイト）が保持されます。

```python
# 保存
tg.save("my_graph.json")

# ロード
tg = ToolGraph.load("my_graph.json")

# from_url()のcache=オプションで自動保存/ロード
tg = ToolGraph.from_url(url, cache="my_graph.json")
```

## 高度な機能

### Cross-Encoderリランキング

Cross-encoderモデルで二次リランキング。`(query, tool_description)` ペアを同時にエンコードし、独立エンベディング比較より正確なスコアリング。

```python
tg.enable_reranker()  # デフォルト: cross-encoder/ms-marco-MiniLM-L-6-v2
tools = tg.retrieve("注文キャンセル", top_k=5)
# wRRFで先にランキング → cross-encoderで再スコアリング
```

### MMR多様性

Maximal Marginal Relevanceリランキングで重複結果を削減。

```python
tg.enable_diversity(lambda_=0.7)  # 0.7 = 関連性重視 + わずかな多様性
```

### History-Aware検索

以前に呼び出したツール名を渡すとコンテキストが改善されます。使用済みツールはダウンランク、グラフ隣接ツールがシードとして展開。

```python
# 最初の呼び出し
tools = tg.retrieve("注文を探す")
# → [listOrders, getOrder, ...]

# 二回目の呼び出し — history-aware
tools = tg.retrieve("次はキャンセルして", history=["listOrders", "getOrder"])
# → [cancelOrder, processRefund, ...]
#    listOrders/getOrderダウンランク、cancelOrderがグラフ近接性でアップランク
```

### wRRFウェイトチューニング

各スコアリングソースのweighted Reciprocal Rank Fusionウェイト調整：

```python
tg.set_weights(
    keyword=0.2,     # BM25テキストマッチング
    graph=0.5,       # グラフ探索（関係ベース）
    embedding=0.3,   # セマンティック類似度
    annotation=0.2,  # MCPアノテーションマッチング
)
```

### LLM強化オントロジー

LLMでより豊かなツールオントロジーを構築。カテゴリ、関係推論、検索キーワード生成（非英語ツール説明に特に有用）。

```python
# 以下すべて使用可能 — wrap_llm()が自動検出
tg.auto_organize(llm="ollama/qwen2.5:7b")           # 文字列ショートハンド
tg.auto_organize(llm=lambda p: my_llm(p))            # callable
tg.auto_organize(llm=openai.OpenAI())                # OpenAIクライアント
tg.auto_organize(llm="litellm/claude-sonnet-4-20250514")    # litellm経由
```

<details>
<summary>サポートするLLM入力</summary>

| 入力 | ラッピングタイプ |
|------|----------|
| `OntologyLLM` インスタンス | そのまま使用 |
| `callable(str) -> str` | `CallableOntologyLLM` |
| OpenAIクライアント（`chat.completions` 保有） | `OpenAIClientOntologyLLM` |
| `"ollama/model"` | `OllamaOntologyLLM` |
| `"openai/model"` | `OpenAICompatibleOntologyLLM` |
| `"litellm/model"` | litellm.completionラッパー |

</details>

### 重複検出

複数のAPI仕様から重複ツールを検出して統合：

```python
duplicates = tg.find_duplicates(threshold=0.85)
merged = tg.merge_duplicates(duplicates)
# merged = {"getUser_1": "getUser", ...}
```

### エクスポート & 可視化

```python
# インタラクティブHTML（vis.js）
tg.export_html("graph.html", progressive=True)

# GraphML（Gephi, yEd用）
tg.export_graphml("graph.graphml")

# Neo4j Cypher
tg.export_cypher("graph.cypher")
```

### API Spec Lint統合

[ai-api-lint](https://github.com/SonAIengine/ai-api-lint)で収集前にOpenAPI仕様を自動修正：

```bash
pip install graph-tool-call[lint]
```

```python
tg = ToolGraph.from_url(url, lint=True)  # 収集中に自動修正
```

## ベンチマーク

graph-tool-callが実際にLLMのツール選択を助けるかテストしました。テスト方法：

1. LLMにユーザーリクエストを渡す（例：*「defaultネームスペースの全podを一覧表示」*）
2. 選択肢となるツール定義を提供
3. 正しいツールを選んだか確認

### 核心的発見：ツールが多すぎるとLLMが混乱する

> 精度 = 50のテストクエリでLLMが正しいツールを選んだ割合。

| API | ツール数 | graph-tool-call ✗ | graph-tool-call ✓ | トークン削減 |
|-----|:-----:|:-----------------:|:-----------------:|:----------:|
| Petstore | 19 | 100% | 95% | 64% |
| GitHub | 50 | 100% | 87.5% | 88% |
| MCP Servers | 38 | 96.7% | 90% | 83% |
| **Kubernetes** | **248** | **12%** | **82%** | **80%** |

- **graph-tool-call ✗** = 全ツールをそのままLLMに渡す
- **graph-tool-call ✓** = 関連ツールだけ検索して渡す
- **50件以下**: 全ツールを渡してもLLMは正しく選べる。graph-tool-callの価値 = **64–88%トークン削減**。
- **248ツール**: フィルタなしだと**12%に崩壊**。フィルタありで**82%** — 最適化ではなく**必須要件**。

<details>
<summary>Kubernetes詳細：エンベディング/オントロジーの追加効果</summary>

> **Recall@5** = 正解ツールが検索結果の上位5件に含まれた割合。Recallが低ければ、LLMがどんなに賢くても正解を選べない。

| Pipeline | 精度 | Recall@5 |
|----------|:----:|:--------:|
| graph-tool-callなし（全248件） | 12% | — |
| graph-tool-call使用（上位5件） | 78% | 91% |
| + エンベディング | 80% | 94% |
| + オントロジー | 82% | 96% |
| + 両方 | **82%** | **98%** |

</details>

> モデル: qwen3:4b (4-bit量子化, Ollama)。データセットあたり50テストクエリ。全仕様は公開 — [自分で再現可能](#自分で再現する)。

<details>
<summary>データセット別の詳細結果</summary>

**Petstore** (19 tools, 20 queries)

| Pipeline | 精度 | Recall@K | 平均トークン | トークン削減 |
|----------|:----:|:--------:|:----------:|:----------:|
| baseline (全ツール) | 100.0% | 100.0% | 1,239 | — |
| retrieve-k3 | 90.0% | 93.3% | 305 | 75.4% |
| retrieve-k5 | 95.0% | 98.3% | 440 | 64.4% |
| retrieve-k10 | 100.0% | 98.3% | 720 | 41.9% |

**GitHub** (50 tools, 40 queries)

| Pipeline | 精度 | Recall@K | 平均トークン | トークン削減 |
|----------|:----:|:--------:|:----------:|:----------:|
| baseline (全ツール) | 100.0% | 100.0% | 3,302 | — |
| retrieve-k3 | 85.0% | 87.5% | 289 | 91.3% |
| retrieve-k5 | 87.5% | 87.5% | 398 | 87.9% |
| retrieve-k10 | 90.0% | 92.5% | 662 | 79.9% |

**Mixed MCP** (38 tools, 30 queries)

| Pipeline | 精度 | Recall@K | 平均トークン | トークン削減 |
|----------|:----:|:--------:|:----------:|:----------:|
| baseline (全ツール) | 96.7% | 100.0% | 2,741 | — |
| retrieve-k3 | 86.7% | 93.3% | 328 | 88.0% |
| retrieve-k5 | 90.0% | 96.7% | 461 | 83.2% |
| retrieve-k10 | 96.7% | 100.0% | 826 | 69.9% |

**Kubernetes core/v1** (248 tools, 50 queries)

| Pipeline | 精度 | Recall@K | 平均トークン | トークン削減 |
|----------|:----:|:--------:|:----------:|:----------:|
| baseline (全ツール) | 12.0% | 100.0% | 8,192 | — |
| retrieve-k5 | 78.0% | 91.0% | 1,613 | 80.3% |
| + エンベディング | 80.0% | 94.0% | 1,728 | 78.9% |
| + オントロジー | **82.0%** | 96.0% | 1,699 | 79.3% |
| + 両方 | **82.0%** | **98.0%** | 1,924 | 76.5% |

</details>

### エンベディング + オントロジーはいつ役立つか？

小規模API（50件以下）では、BM25 + グラフ探索だけで十分です。大規模APIでは、エンベディングとオントロジーが実質的な差を生みます。Kubernetes（248 tools）でテスト：

| Pipeline | 精度 | Recall@5 | 追加される機能 |
|----------|:----:|:--------:|-------------|
| BM25 + グラフのみ | 78% | 91% | キーワードマッチング + グラフ隣接探索 |
| + エンベディング | 80% | 94% | 意味的類似度（BM25が見逃す同義語を捕捉） |
| + オントロジー | **82%** | 96% | LLM生成キーワード + example queries |
| **+ 両方** | **82%** | **98%** | エンベディング + オントロジーが相互補完 |

エンベディング: OpenAI `text-embedding-3-small`。オントロジー: `gpt-4o-mini`。

### 自分で再現する

```bash
# 検索品質の測定（高速、LLM不要）
python -m benchmarks.run_benchmark
python -m benchmarks.run_benchmark -d k8s -v

# フルPipelineベンチマーク（Ollama必要）
python -m benchmarks.run_benchmark --mode pipeline -m qwen3:4b
python -m benchmarks.run_benchmark --mode pipeline --pipelines baseline retrieve-k3 retrieve-k5 retrieve-k10

# ベースライン保存後に変更を比較
python -m benchmarks.run_benchmark --mode pipeline --save-baseline
python -m benchmarks.run_benchmark --mode pipeline --diff
```

## 機能比較

| 機能 | ベクトルのみのソリューション | graph-tool-call |
|------|------------------------|-----------------|
| ツールソース | 手動登録 | Swagger/OpenAPI/MCPから自動収集 |
| 検索方式 | 単純なベクトル類似度 | 多段階ハイブリッド (wRRF + rerank + MMR) |
| 行動的意味論 | なし | MCP annotation-aware retrieval |
| ツール関係 | なし | 6種類の関係タイプ、自動検出 |
| 呼び出し順序 | なし | ステートマシン + CRUD + response→requestデータフロー |
| 重複排除 | なし | クロスソース重複検出 |
| オントロジー | なし | Auto / LLM-Auto モード（任意のLLM） |
| History | なし | 使用済みツールダウンランク、次のステップアップランク |
| 仕様品質 | 良い仕様を前提 | ai-api-lint自動修正統合 |
| LLM依存 | 必須 | オプション（なくても動く、あればさらに良い） |

## 全APIリファレンス

<details>
<summary>ToolGraph メソッド</summary>

| メソッド | 説明 |
|--------|------|
| `add_tool(tool)` | 単一ツール追加（フォーマット自動検出） |
| `add_tools(tools)` | 複数ツール追加 |
| `ingest_openapi(source)` | OpenAPI/Swagger仕様から収集 |
| `ingest_mcp_tools(tools)` | MCPツールリストから収集 |
| `ingest_functions(fns)` | Python callableから収集 |
| `ingest_arazzo(source)` | Arazzo 1.0.0ワークフロー仕様収集 |
| `from_url(url, cache=...)` | Swagger UIまたはspec URLからビルド |
| `add_relation(src, tgt, type)` | 手動関係追加 |
| `auto_organize(llm=...)` | ツール自動分類 |
| `build_ontology(llm=...)` | 完全オントロジービルド |
| `retrieve(query, top_k=10)` | ツール検索 |
| `enable_embedding(provider)` | ハイブリッドエンベディング検索を有効化 |
| `enable_reranker(model)` | cross-encoderリランキングを有効化 |
| `enable_diversity(lambda_)` | MMR多様性を有効化 |
| `set_weights(...)` | wRRF融合ウェイトチューニング |
| `find_duplicates(threshold)` | 重複ツール検出 |
| `merge_duplicates(pairs)` | 検出された重複を統合 |
| `apply_conflicts()` | CONFLICTS_WITHエッジ検出/追加 |
| `save(path)` / `load(path)` | シリアライズ / デシリアライズ |
| `export_html(path)` | インタラクティブHTML可視化エクスポート |
| `export_graphml(path)` | GraphMLフォーマットエクスポート |
| `export_cypher(path)` | Neo4j Cypher文エクスポート |

</details>

## ドキュメント

| ドキュメント | 説明 |
|------------|------|
| [アーキテクチャ](docs/architecture/overview.md) | システム概要、パイプラインレイヤー、データモデル |
| [WBS](docs/wbs/) | 作業分解構造 — Phase 0~4 進捗 |
| [設計](docs/design/) | アルゴリズム設計 — 仕様正規化、依存関係検出、検索モード、呼び出し順序、オントロジーモード |
| [リサーチ](docs/research/) | 競合分析、APIスケールデータ、ECパターン |
| [OpenAPIガイド](docs/design/openapi-guide.md) | より良いツールグラフを生成するAPI仕様の書き方 |

## コントリビューション

コントリビューションを歓迎します！

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

## ライセンス

[MIT](LICENSE)
