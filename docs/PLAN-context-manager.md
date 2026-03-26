# graph-tool-call Context Manager — Implementation Plan

## Overview

graph-tool-call에 통합할 context window manager.
tool의 전체 생명주기를 하나의 라이브러리에서 관리한다:
- **검색**: `search` → 관련 tool 찾기 (기존)
- **실행**: `call` → API 호출 (기존)
- **결과 관리**: `compress` + `track` → tool result 압축 + 진행 이력 (신규)

기존 메모리 솔루션(MemGPT, Zep, Mem0)이 다루지 않는
**세션 내 tool result 폭발 문제**를 해결한다.

별도 프로젝트(context-window)로 시작했으나, graph-tool-call에 통합하는 것이
사용자 경험과 포지셔닝 면에서 더 적합하다고 판단.

## Background & Motivation

### 실제 문제 (XGEN AI CLI에서 발생)
```
사용자: "워크플로우 목록 보여줘" → "x2bee 에이전트 열어줘" → "실행해봐"
→ 3개 요청에 tool 호출 8번, 토큰 219,263개 → 200K 한도 초과 → 에러
```

### 기존 솔루션의 한계

| 솔루션 | 문제 |
|--------|------|
| MemGPT/Letta | Self-edit 오버헤드, 매 턴 메모리 관리에 토큰 소모 |
| Zep/Graphiti | Neo4j 의존, graph 구축에 LLM 호출 필요 |
| Mem0 | Vector DB 의존, 장기 기억 중심 (세션 내 관리 약함) |
| LangChain BufferWindow | tool_result 타입을 구분하지 않음, 단순 FIFO |
| 단순 truncate | 정보 손실, 잘린 JSON이 더 큰 혼란 유발 |

### Manus의 핵심 인사이트
- KV-cache hit rate가 프로덕션 agent의 가장 중요한 메트릭
- Anthropic cached: $0.30/MTok vs uncached: $3/MTok (10x)
- Append-only context, prefix 안정성, file system as memory

## Design Principles

1. **Zero-dependency core** — 외부 서비스 없이 동작
2. **Tool-use 특화** — tool result 타입별 지능형 압축
3. **KV-cache 친화** — append-only, prefix 안정, cache-aware
4. **Budget 기반** — 영역별 토큰 예산 분배
5. **Framework agnostic** — Anthropic, OpenAI, LangChain 어디든 통합
6. **직전 턴 중심** — agent는 현재 턴 + 직전 1~2턴만 참조하면 충분. 그 이전은 한 줄 요약으로 대체

## Core Insight: 직전 턴만 있으면 된다

실제 agent 대화에서 LLM이 필요로 하는 정보:

```
[필요 없음]  3턴 전 tool_result: 워크플로우 목록 JSON 50KB  → 버림
[필요 없음]  2턴 전 tool_result: 노드 상세 정보 30KB       → 버림
[필요]      직전 턴: assistant 응답 + tool_result           → 전체 유지
[필요]      현재 턴: user 질문 + tool_calls + tool_results  → 전체 유지
```

이전 턴의 **사실 관계**만 한 줄로 남기면 맥락이 유지됨:
- "워크플로우 목록을 조회함 (11개)"
- "x2bee 에이전트 워크플로우를 캔버스에 로드함 (노드 9개)"

이 방식으로 **턴이 아무리 쌓여도 토큰 사용량이 거의 일정**하게 유지됨:
```
system(500) + tools(3000) + 요약(~200 per past turn) + 직전턴(~5000) + 현재턴(~5000)
= ~15K tokens (100K budget 중 15%만 사용)
```

## Architecture

```
                    ┌─────────────────────┐
                    │   ContextManager    │
                    │                     │
                    │  max_tokens: 100K   │
                    │  format: anthropic  │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────┴────────┐ ┌────┴────┐ ┌─────────┴─────────┐
     │  MessageStore   │ │ Budget  │ │   Compressor      │
     │                 │ │ Manager │ │                   │
     │ append-only     │ │         │ │ JsonCompressor    │
     │                 │ │ system: │ │ HtmlCompressor    │
     │ [system]  고정  │ │  1000   │ │ ErrorCompressor   │
     │ [tools]   고정  │ │ tools:  │ │ TextCompressor    │
     │ [요약]    압축  │ │  3000   │ │ AutoDetect        │
     │ [직전턴]  전체  │ │ summary:│ └───────────────────┘
     │ [현재턴]  전체  │ │  1000   │
     └─────────────────┘ │ recent: │
                          │  rest   │
                          └─────────┘

build() 시 생성되는 메시지:
┌──────────────────────────────────────────────────────┐
│ system: "You are a helpful assistant."               │ ← 고정 (cached)
│ system: "Tools: search_tools, call_tool, ..."        │ ← 고정 (cached)
│ system: "이전 대화 요약:                              │ ← 턴마다 갱신
│   - 워크플로우 목록 조회함 (11개)                      │
│   - x2bee 에이전트를 캔버스에 로드함 (노드 9개)"       │
│ user: "실행해봐"                     ← 직전 턴       │
│ assistant: [tool_call: execute...]   ← 직전 턴       │
│ user: [tool_result: {...}]           ← 직전 턴       │
│ assistant: "실행 결과입니다..."       ← 직전 턴       │
│ user: "결과를 이메일로 보내줘"        ← 현재 턴       │
└──────────────────────────────────────────────────────┘
```

### Core Components

#### 1. TokenBudget
```python
class TokenBudget:
    def __init__(self, max_tokens, regions):
        # regions: {name: fixed_tokens or "rest"}
        # "rest" = max_tokens - sum(fixed regions)

    def allocate(self, region, tokens) -> bool
    def available(self, region) -> int
    def total_used() -> int
```

#### 2. MessageStore
```python
class MessageStore:
    # Append-only storage
    # 각 메시지에 token count 캐싱
    # role: system | user | assistant | tool_result

    def append(self, message: Message)
    def get_recent(self, max_tokens: int) -> list[Message]
    def get_summary_candidates(self) -> list[Message]  # summarize 대상
```

#### 3. Compressor
```python
class Compressor:
    def compress(self, content: str, content_type: str, max_tokens: int) -> str

class JsonCompressor(Compressor):
    # list → count + first N items + schema
    # object → top-level keys + truncated values
    # nested → flatten to key paths

class HtmlCompressor(Compressor):
    # strip tags → plain text → truncate

class ErrorCompressor(Compressor):
    # extract error message + status code only

class TextCompressor(Compressor):
    # head + tail with "[... N chars omitted ...]"
```

#### 4. Summarizer
```python
class Summarizer:
    def summarize(self, messages: list[Message]) -> str

class RuleSummarizer(Summarizer):
    # LLM 호출 없이 규칙 기반 요약
    # user 메시지만 추출 → "사용자가 X를 요청 → Y 결과"
    # tool_result는 성공/실패 + tool 이름만

class LLMSummarizer(Summarizer):
    # LLM에 "다음 대화를 3문장으로 요약해줘" 요청
    # 비용 발생하지만 품질 높음
```

## API Design

### Core API
```python
from context_window import ContextManager

# 초기화
cm = ContextManager(
    max_tokens=100_000,
    token_counter="estimate",  # or "tiktoken"
    summarizer="rule",         # or "llm"
)

# System prompt (fixed, always at front)
cm.set_system("You are a helpful assistant.")

# Tool definitions (fixed, always after system)
cm.set_tools([{...}, {...}])

# 대화 추가 (append-only)
cm.add_user("list workflows")
cm.add_assistant("Searching...", tool_calls=[{"id": "t1", "name": "search"}])
cm.add_tool_result("t1", huge_json, content_type="json")  # auto-compressed
cm.add_assistant("Here are the results...")

# LLM API용 메시지 빌드
messages = cm.build()                    # default format
messages = cm.build(format="anthropic")  # Anthropic API format
messages = cm.build(format="openai")     # OpenAI API format

# 상태 확인
cm.stats()
# → {total_tokens: 45000, budget: {system: 800, tools: 2500, summary: 600, recent: 41100},
#    messages: 12, compressed: 4, summarized_turns: 3}
```

### Convenience: auto-manage from raw API response
```python
# Anthropic response 자동 파싱
cm.add_raw(anthropic_response)
# → assistant message + tool_calls 자동 추출 & 추가

# tool_result도 자동 타입 감지
cm.add_tool_result("t1", result)  # content_type 자동 판별
```

### LangChain Integration
```python
from context_window.langchain import ContextWindowMemory

memory = ContextWindowMemory(
    max_tokens=100_000,
    compress_tool_results=True,
)
```

## Implementation Phases

### Phase 1: Core (MVP)
**목표**: 기본 동작 — budget 관리 + tool result 압축

파일 구조:
```
context_window/
├── __init__.py          # ContextManager export
├── manager.py           # ContextManager 메인 클래스
├── budget.py            # TokenBudget
├── store.py             # MessageStore
├── counter.py           # TokenCounter (estimate + tiktoken)
├── compressor/
│   ├── __init__.py
│   ├── base.py          # Compressor base class
│   ├── json_comp.py     # JSON 압축
│   ├── html_comp.py     # HTML 압축
│   ├── text_comp.py     # 텍스트 압축
│   └── auto.py          # 자동 타입 감지 + 압축
└── types.py             # Message, Role 등 타입 정의
```

구현 순서:
1. `types.py` — Message, Role dataclass
2. `counter.py` — 토큰 카운터 (char estimate: len/4)
3. `budget.py` — 영역별 예산 관리
4. `compressor/` — JSON, HTML, Text, Auto 압축기
5. `store.py` — append-only 메시지 저장소
6. `manager.py` — ContextManager (통합)
7. `__init__.py` — public API export
8. Tests

### Phase 2: Summarizer
**목표**: 오래된 대화를 요약으로 압축

추가 파일:
```
context_window/
├── summarizer/
│   ├── __init__.py
│   ├── base.py          # Summarizer interface
│   ├── rule.py          # 규칙 기반 요약 (LLM 불필요)
│   └── llm.py           # LLM 기반 요약 (optional)
```

### Phase 3: Format adapters
**목표**: Anthropic, OpenAI, LangChain 포맷 지원

추가 파일:
```
context_window/
├── formats/
│   ├── anthropic.py     # Anthropic Messages API
│   ├── openai.py        # OpenAI Chat Completions
│   └── raw.py           # 범용 dict 포맷
├── langchain/
│   ├── __init__.py
│   └── memory.py        # ContextWindowMemory
```

### Phase 4: Persistence & Advanced
- SQLite 기반 세션 저장/복원
- Cross-session memory (Mem0 스타일, optional)
- Streaming support (token-by-token budget tracking)
- graph-tool-call 네이티브 통합

## Token Counting Strategy

### Estimate (default, zero-dep)
```python
def estimate_tokens(text: str) -> int:
    # English: ~4 chars/token, Korean: ~2-3 chars/token
    # Conservative estimate for mixed content
    return max(len(text) // 3, 1)
```

### Exact (optional, tiktoken)
```python
def count_tokens_tiktoken(text: str, model: str) -> int:
    import tiktoken
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))
```

## Compression Examples

### JSON List Compression
```
Input (5000 tokens):
[{"id": "wf_001", "name": "HR Routing", "status": "active", "nodes": [...], "edges": [...], ...},
 {"id": "wf_002", "name": "Customer Bot", ...},
 ... 47 more items ...]

Output (500 tokens):
{"_compressed": true, "type": "array", "count": 50, "schema": {"id": "string", "name": "string", "status": "string"},
 "samples": [{"id": "wf_001", "name": "HR Routing", "status": "active"},
             {"id": "wf_002", "name": "Customer Bot", "status": "active"},
             {"id": "wf_003", "name": "Data Pipeline", "status": "draft"}],
 "note": "47 more items omitted"}
```

### HTML Compression
```
Input (10000 tokens):
<!DOCTYPE html><html><head>...</head><body><div class="app">...</div></body></html>

Output (200 tokens):
[HTML page content] 404: This page could not be found.
```

### Error Compression
```
Input (2000 tokens):
{"status": 401, "error": "Unauthorized", "body": {"detail": "사용자 인증이 필요합니다"}, "headers": {...}}

Output (50 tokens):
HTTP 401: 사용자 인증이 필요합니다
```

## Benchmarks (Target)

| Metric | Without context-window | With context-window |
|--------|----------------------|-------------------|
| Token usage per session | 200K+ (overflow) | <80K (within budget) |
| API cost (Anthropic) | $0.60+ per session | <$0.10 (cache hits) |
| Context overflow errors | Frequent | Zero |
| Information loss | N/A (crashes) | Minimal (smart compression) |

## Related Work

- [MemGPT/Letta](https://github.com/letta-ai/letta) — OS-inspired virtual memory for LLMs
- [Zep/Graphiti](https://github.com/getzep/graphiti) — Temporal knowledge graph memory
- [Mem0](https://github.com/mem0ai/mem0) — Universal memory layer
- [graph-tool-call](https://github.com/SonAIengine/graph-tool-call) — Graph-structured tool retrieval (companion project)
- [Manus Context Engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) — KV-cache optimization insights
- [CoALA](https://arxiv.org/abs/2309.02427) — Cognitive Architectures for Language Agents
- [Generative Agents](https://arxiv.org/abs/2304.03442) — Memory stream + reflection architecture
