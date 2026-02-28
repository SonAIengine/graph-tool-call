# Deduplication Pipeline — 설계 문서

**WBS**: 2-1
**파일**: `analyze/similarity.py`
**학술 근거**: SynthTools (arXiv:2511.09572), SemDeDup (Meta), JSONGlue (SBBD 2020)

## 5-Stage Pipeline

```
Stage 1: Exact Hash         → SHA256(canonical(name + params))     O(n)
Stage 2: Name Fuzzy Match   → RapidFuzz Jaro-Winkler > 0.85       O(n²) but fast (C++)
Stage 3: Schema Structural  → Parameter key Jaccard + type compat  O(n² * params)
Stage 4: Semantic Desc      → Sentence embedding cosine > 0.85     O(n² * embed_dim)
Stage 5: Composite Score    → 0.2*name + 0.3*schema + 0.5*semantic
   → > 0.85: auto-merge
   → 0.70-0.85: flag for review
   → < 0.70: not duplicate
```

## Merge 전략

```python
class MergeStrategy(Enum):
    KEEP_FIRST = "keep_first"     # 먼저 등록된 것 유지
    KEEP_BEST = "keep_best"       # description 길이 + param docs 완성도 기준
    CREATE_ALIAS = "create_alias" # canonical + alias 관계 유지
```

## 라이브러리

**RapidFuzz** (MIT, C++ 구현):
- 2,500 pairs/sec
- Jaro-Winkler: 짧은 tool name에 최적 (prefix 유사 보너스)
- token_sort_ratio: 단어 순서 무관 비교
- `process.cdist()`: 대규모 batch 유사도 matrix

## 인터페이스

```python
@dataclass
class DuplicatePair:
    tool_a: str
    tool_b: str
    score: float
    stage: int        # 어느 stage에서 감지되었는지

def find_duplicates(
    tools: dict[str, ToolSchema],
    *,
    threshold: float = 0.85,
) -> list[DuplicatePair]:

def merge_duplicates(
    pairs: list[DuplicatePair],
    strategy: MergeStrategy = MergeStrategy.KEEP_BEST,
) -> dict[str, str]:  # merged_name → canonical_name
```
