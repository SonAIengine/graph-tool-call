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

Agentが数百〜数千のツールを持つ場合、すべてのツールをコンテキストウィンドウに読み込むとパフォーマンスが低下します。既存のソリューションはベクトル類似度のみを使用しています。**graph-tool-call**はツール間の**関係**（依存関係、呼び出し順序、補完、競合）をグラフとしてモデル化し、構造認識型の検索を実現します。

```
OpenAPI/MCP/コード → [収集] → [分析] → [組織化] → [検索] → Agent
                      (変換)  (関係発見) (グラフ)   (ハイブリッド)
```

## なぜ graph-tool-call か？

| 機能 | ベクトルのみのソリューション | graph-tool-call |
|------|------------------------|-----------------|
| 範囲 | ツール検索のみ | 完全なツールライフサイクル |
| ツールソース | 手動登録 | Swagger/OpenAPIから自動収集 |
| 検索 | フラットなベクトル類似度 | グラフ + ベクトルハイブリッド (RRF)、3-Tier |
| 関係 | なし | REQUIRES, PRECEDES, COMPLEMENTARY, SIMILAR_TO, CONFLICTS_WITH |
| 重複排除 | なし | クロスソース重複検出 |
| 依存関係 | なし | API仕様から自動検出 |
| 呼び出し順序 | なし | ステートマシン + CRUDワークフロー検出 |
| オントロジー | なし | Auto / LLM-Auto モード |

## クイックスタート

### インストール

```bash
pip install graph-tool-call
```

### 基本的な使い方

```python
from graph_tool_call import ToolGraph

tg = ToolGraph()

# ツールを登録（OpenAI / Anthropic / LangChain フォーマットを自動検出）
tg.add_tools(your_tools_list)

# カテゴリと関係を設定
tg.add_category("file_ops", domain="io")
tg.assign_category("read_file", "file_ops")
tg.add_relation("read_file", "write_file", "complementary")

# クエリで関連ツールを検索
tools = tg.retrieve("read a file and save changes", top_k=5)
```

### OpenAPI 収集（Phase 1）

```python
tg = ToolGraph()
tg.ingest_openapi("https://petstore.swagger.io/v2/swagger.json")
# 自動発見: CRUD依存関係、呼び出し順序、カテゴリグルーピング
tools = tg.retrieve("register a new pet and upload photo", top_k=5)
```

## 主要機能

### 収集（Ingest）
OpenAPI/Swagger、MCPサーバー、Python関数、LangChain/OpenAI/Anthropicフォーマットのツールを統一スキーマに自動変換します。Spec正規化レイヤーがSwagger 2.0、OpenAPI 3.0、3.1の差異を透過的に処理します。

### 分析（Analyze）
ツール間の関係を自動検出します：
- **REQUIRES** — データ依存（response → parameter）
- **PRECEDES** — 呼び出し順序（一覧照会 → キャンセル）
- **COMPLEMENTARY** — 一緒に使うと効果的（read ↔ write）
- **SIMILAR_TO** — 機能が重複
- **CONFLICTS_WITH** — 相互排他的な操作

### 組織化（Organize）
2つのモードでオントロジーグラフを構築します：
- **Auto** — アルゴリズムベースの分類（tag、path、CRUDパターン、embeddingクラスタリング）。LLM不要。
- **LLM-Auto** — Auto + LLMによる関係推論とカテゴリ提案の強化（Ollama、vLLM、llama.cpp、OpenAI）。

どちらのモードでも、結果をDashboardで可視化・手動編集できます。

### 検索（Retrieve）
3-Tierハイブリッド検索アーキテクチャ：
| Tier | LLM要否 | 方法 |
|------|--------|------|
| 0 | 不要 | BM25 + グラフ展開 + RRF |
| 1 | 小型 (1.5B~3B) | + クエリ拡張 |
| 2 | 大型 (7B+) | + 意図分解 |

LLMなしでも動作します。LLMがあればさらに高品質に。

## ロードマップ

| Phase | 説明 | 状態 |
|-------|------|------|
| **0** | コアグラフ + 検索 | ✅ 完了 (32 tests) |
| **1** | OpenAPI収集 + 依存関係/順序検出 | 進行中 |
| **2** | 重複排除 + embedding + オントロジー/検索モード | 計画中 |
| **3** | MCP収集 + 可視化 + CLI + PyPI | 計画中 |
| **4** | インタラクティブDashboard + コミュニティ | 計画中 |

## ドキュメント

- [WBS](docs/wbs/) — 作業分解構造
- [アーキテクチャ](docs/architecture/overview.md) — システム概要とデータモデル
- [設計](docs/design/) — アルゴリズム設計ドキュメント
- [リサーチ](docs/research/) — 競合分析、APIスケールデータ

## コントリビューション

コントリビューションを歓迎します！ガイドラインは近日公開予定です。

```bash
# 開発環境のセットアップ
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry
poetry install --with dev
poetry run pytest -v
```

## ライセンス

[MIT](LICENSE)
