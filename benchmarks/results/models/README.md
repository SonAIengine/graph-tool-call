# Model Benchmark Results

graph-tool-call의 도구 검색 + LLM tool calling end-to-end 벤치마크 결과.

## How to Run

```bash
# Retrieval-only (LLM 불필요)
python -m benchmarks.run_benchmark --mode retrieval -v

# E2E with Ollama
python -m benchmarks.run_benchmark --mode e2e -m qwen3:4b -v --save

# E2E with OpenAI-compatible server (llama.cpp, vLLM 등)
python -m benchmarks.run_benchmark --mode e2e -m "Bonsai-8B.gguf" \
  --ollama-url "http://localhost:8080/v1" -v --save
```

## Model Comparison

| Model | Size | Quant | Petstore (19t) | Mixed MCP (38t) | Retrieve Boost |
|-------|-----:|-------|-------:|--------:|------:|
| [Bonsai-8B](bonsai-8b-q1_0.md) | 1.1 GB | Q1_0 (1-bit) | BL 65% / RT 57% | BL 0% / RT 73% | **0% → 73%** |

> **BL** = Baseline (all tools), **RT** = Retrieve (top-5 filtered)

## Key Findings

1. **소형 모델일수록 graph-tool-call 효과가 크다** — 도구 수가 context 한계를 넘으면 baseline이 0%로 무너지지만, retrieval 필터링으로 복구 가능
2. **도구 20개 이하**에서는 baseline과 retrieve 차이가 작거나 역전될 수 있음
3. **도구 30개 이상**에서는 retrieve 파이프라인이 필수적

## Adding a New Model

1. 벤치마크 실행 후 JSON 결과 확인 (`benchmarks/results/`)
2. `models/` 디렉토리에 `{model-name}.md` 작성 (기존 문서 포맷 참고)
3. 이 README의 Model Comparison 테이블에 행 추가
