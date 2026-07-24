# Public API

이 페이지는 adapter가 의존해도 되는 public module과 entry point를 정리합니다.
문서에서 안정 계약이라고 명시하지 않은 internal helper import는 피하는 것이 좋습니다.

## Package Exports

```python
from graph_tool_call import ToolGraph, ToolSchema
```

## ToolGraph

```python
from graph_tool_call import ToolGraph

graph = ToolGraph.from_url(openapi_url)
tools = graph.retrieve("고객 주문 조회", top_k=8)
ranked = graph.retrieve_with_scores("고객 주문 조회", top_k=8)
report = graph.analyze()
```

## Tool Schema

```python
from graph_tool_call import ToolSchema
```

`ToolSchema`는 ingest, graph build, retrieval, planning, adapter가 함께 사용하는
정규화된 tool representation입니다.

## Graphify

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
    ingest_openapi_graphify,
    retrieve_graphify,
)
from graph_tool_call.graphify.contract_index import extract_openapi_contract_index
```

대형 OpenAPI spec에서 API collection을 build할 때 사용합니다.

## Planflow

```python
from graph_tool_call.plan import PathSynthesizer, PlanRunner
```

`PathSynthesizer`는 선택된 target과 contract로 실행 plan을 만들고,
`PlanRunner`는 구조화된 실행 event를 stream합니다.

## Learning

```python
from graph_tool_call.learning import (
    apply_learning_suggestions,
    build_trace_learning_record,
    derive_learning_suggestions,
    scrub_trace_payload,
)
```

Learning API는 scrub된 trace evidence와 승격 가능한 suggestion을 저장/적용합니다.
