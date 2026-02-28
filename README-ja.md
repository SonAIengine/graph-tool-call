<div align="center">

# graph-tool-call

**LLM Agentのためのツールライフサイクル管理**

収集、分析、組織化、検索。

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

**graph-tool-call** はツール間の関係をグラフとしてモデル化します：

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

各ツールを独立したベクトルとして扱う代わりに、graph-tool-callは理解します：
- **REQUIRES** — `getOrder` は `listOrders` のIDが必要
- **PRECEDES** — 注文一覧を照会してからでないとキャンセルできない
- **COMPLEMENTARY** — キャンセルと返金は一緒に使われる
- **SIMILAR_TO** — `getOrder` と `listOrders` は関連機能
- **CONFLICTS_WITH** — `updateOrder` と `deleteOrder` は同時実行不可

*「注文キャンセル」*を検索すると、`cancelOrder` だけでなく**完全なワークフロー**が返されます：一覧照会 → 詳細照会 → キャンセル → 返金。

## 仕組み

```
OpenAPI/MCP/コード → [収集] → [分析] → [組織化] → [検索] → Agent
                      (変換)  (関係発見) (グラフ)   (ハイブリッド)
```

**1. 収集（Ingest）** — Swagger仕様、MCPサーバー、Python関数を指定するだけ。ツールが統一スキーマに自動変換されます。

**2. 分析（Analyze）** — 関係が自動検出されます：パス階層、CRUDパターン、共有スキーマ、response-parameterチェーン、ステートマシン。

**3. 組織化（Organize）** — ツールがオントロジーグラフにグループ化されます。2つのモード：
  - **Auto** — 純粋なアルゴリズム（tag、path、CRUDパターン）。LLM不要。
  - **LLM-Auto** — LLM推論で強化（Ollama、vLLM、OpenAI）。より良い分類、より豊かな関係。

**4. 検索（Retrieve）** — キーワードマッチング、グラフ探索、（オプションの）エンベディングを組み合わせたハイブリッド検索。LLMなしでも十分動作。LLMがあればさらに向上。

## クイックスタート

```bash
pip install graph-tool-call
```

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# ツール登録（OpenAI / Anthropic / LangChain フォーマットを自動検出）
tg.add_tools(your_tools_list)

# 関係を定義
tg.add_relation("read_file", "write_file", "complementary")

# 検索 — グラフ展開が関連ツールを自動発見
tools = tg.retrieve("read a file and save changes", top_k=5)
# → [read_file, write_file, list_dir, ...]
#    write_fileはベクトル類似度ではなくCOMPLEMENTARY関係で発見
```

### Swagger / OpenAPIから自動生成

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()
tg.ingest_openapi("tests/fixtures/petstore_swagger2.json")
# 対応: Swagger 2.0, OpenAPI 3.0, OpenAPI 3.1
# 入力: ファイルパス (JSON/YAML), URL, または raw dict

# 自動処理: 5 endpoint → 5 tool → CRUD関係 → カテゴリ
# 依存関係、呼び出し順序、カテゴリグルーピング——すべて自動検出。

tools = tg.retrieve("create a new pet", top_k=5)
# → [createPet, getPet, updatePet, listPets, deletePet]
#    グラフ展開が完全なCRUDワークフローを取得
```

### Python関数から自動生成

```python
def read_file(path: str) -> str:
    """ファイルの内容を読む。"""

def write_file(path: str, content: str) -> None:
    """ファイルに内容を書く。"""

tg = ToolGraph()
tg.ingest_functions([read_file, write_file])
# type hintからパラメータを抽出、docstringから説明を抽出
```

## なぜベクトル検索だけでは足りないのか？

| シナリオ | ベクトルのみ | graph-tool-call |
|----------|-----------|-----------------|
| *「注文をキャンセルして」* | `cancelOrder` を返す | `listOrders → getOrder → cancelOrder → processRefund`（完全なワークフロー）|
| *「ファイルを読んで保存」* | `read_file` を返す | `read_file` + `write_file`（COMPLEMENTARY関係）|
| 複数Swagger仕様に重複ツール | 結果に重複を含む | クロスソース自動重複排除 |
| 1,200のAPIエンドポイント | 遅くノイズが多い | カテゴリに整理、正確なグラフ探索 |

## 3-Tier検索：持っているものを使う

graph-tool-callは**LLMなしでも動作**し、**あればさらに向上**するように設計されています：

| Tier | 必要なもの | 何をするか | 改善効果 |
|------|----------|-----------|---------|
| **0** | 何も不要 | BM25キーワード + グラフ展開 + RRF融合 | ベースライン |
| **1** | 小型LLM (1.5B~3B) | + クエリ拡張、同義語、翻訳 | Recall +15~25% |
| **2** | 大型LLM (7B+) | + 意図分解、反復改善 | Recall +30~40% |

Ollamaで動く小さなモデル（`qwen2.5:1.5b`）でも検索品質は有意に向上します。Tier 0はGPUすら不要です。

## 機能比較

| 機能 | ベクトルのみのソリューション | graph-tool-call |
|------|------------------------|-----------------|
| ツールソース | 手動登録 | Swagger/OpenAPI/MCPから自動収集 |
| 検索方式 | フラットなベクトル類似度 | グラフ+ベクトルハイブリッド (RRF)、3-Tier |
| ツール関係 | なし | 6種類の関係タイプ、自動検出 |
| 呼び出し順序 | なし | ステートマシン + CRUDワークフロー検出 |
| 重複排除 | なし | クロスソース重複検出 |
| オントロジー | なし | Auto / LLM-Auto モード |
| 可視化 | なし | グラフDashboard + 手動編集 |
| LLM依存 | 必須 | オプション（なくても動く、あればさらに良い）|

## ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| **0** | コアグラフエンジン + ハイブリッド検索 | ✅ 完了 (39 tests) |
| **1** | OpenAPI収集、BM25+RRF検索、依存関係検出 | ✅ 完了 (88 tests) |
| **2** | 重複排除、エンベディング、オントロジーモード（Auto/LLM-Auto）、検索Tier | 計画中 |
| **3** | MCP収集、Pyvis可視化、Neo4jエクスポート、CLI、PyPI公開 | 計画中 |
| **4** | インタラクティブDashboard（Dash Cytoscape）、手動編集、コミュニティ | 計画中 |

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
```

## ライセンス

[MIT](LICENSE)
