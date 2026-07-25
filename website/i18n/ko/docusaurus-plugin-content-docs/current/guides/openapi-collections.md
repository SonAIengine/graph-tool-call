---
title: OpenAPI 컬렉션
description: 대형 OpenAPI surface를 검색, plan, 실행 가능한 tool graph artifact로 빌드하는 방법을 설명합니다.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# OpenAPI 컬렉션

OpenAPI collection은 하나 이상의 Swagger/OpenAPI source에서 만든 저장형 tool
catalog입니다. Agent가 큰 API surface를 검색, plan, 실행해야 하지만 모든 endpoint를
LLM에 그대로 넘기면 안 될 때 사용합니다.

Collection은 raw endpoint 목록이 아니라 build artifact로 다뤄야 합니다. 쓸모 있는
artifact에는 normalized tools, request/response contract, deterministic semantic
metadata, graph edges, readiness diagnostics, validation results, provenance가 함께
들어갑니다.

## Collection Lifecycle

```text
register source
  -> build artifact
  -> inspect readiness
  -> run search/plan quality cases
  -> enable execute
     when auth and safety are ready
  -> preserve manual metadata
     and learning metadata during rebuild
```

엔진은 product-neutral graph evidence를 책임집니다. 애플리케이션은 source storage, auth
profile, tenant policy, UI, execution, audit logging, operator approval을 책임집니다.

## 이 가이드를 써야 하는 경우

다음 상황에서는 이 가이드를 기준으로 collection을 설계합니다.

- 하나의 API source에 수백~수천 개 operation이 있음
- OpenAPI 문서가 Swagger UI, JSON, YAML, 여러 spec에서 들어옴
- operation name이 한국어/영어/RPC-style name/path module로 섞여 있음
- search quality가 field, response shape, auth, workflow order에 의존함
- product UI에서 사용자가 API call을 실행하기 전에 collection quality를 설명해야 함
- rebuild 중 manual metadata, Quality Lab case, promoted trace learning suggestion을
  보존해야 함

단일 quick search라면 [OpenAPI Ingestion](../build/openapi-ingestion.md)부터 보면 됩니다.
product-facing stored catalog라면 이 collection workflow를 사용합니다.

## 권장 Pipeline

| Stage | Engine Output | Product Decision |
| --- | --- | --- |
| Source registration | source manifest와 discovered spec URL | source를 어디에 저장하고 누가 refresh할 수 있는지 |
| Contract extraction | `api_contract.consumes`, `produces`, `links` | execute 전에 missing schema를 보정해야 하는지 |
| Semantic build | action/resource/module/result-shape metadata | alias나 manual curation이 필요한지 |
| Graph build | structural, contract, semantic, manual, trace edge | 어떤 edge를 UI에 보이고 ranking에 반영할지 |
| Readiness | score, status, issue code, recommendation | search, plan, execute를 열 수 있는지 |
| Validation | Quality Lab과 benchmark result | artifact를 promote할 수 있는지 |
| Rebuild | 새 source-derived fact와 보존된 product field | source 변경이 호환되는지 |

## Artifact Build

<Tabs>
  <TabItem value="cli" label="CLI" default>

```bash
graph-tool-call \
  build-openapi-collection \
  openapi.json \
  -o collection.json \
  --context-field tenantId,siteNo \
  --paging-field page,size \
  --search-filter-field keyword,searchText
```

  </TabItem>
  <TabItem value="python" label="Python">

```python
from graph_tool_call.graphify import (
    build_openapi_collection_artifact,
)

artifact = build_openapi_collection_artifact(
    "openapi.json",
    derive_semantic_metadata=True,
    promote_contract_signals=True,
    context_field_names={"tenantId", "siteNo"},
    paging_field_names={"page", "size"},
    search_filter_field_names={"keyword", "searchText"},
    metadata={"collection_id": "commerce-readonly"},
)

print(artifact["semantic_summary"])
print(artifact["readiness_report"]["summary"])
```

  </TabItem>
  <TabItem value="multiple" label="Multiple specs">

```python
artifact = build_openapi_collection_artifact(
    [
        "orders.openapi.json",
        "members.openapi.json",
        "payments.openapi.json",
    ],
    derive_semantic_metadata=True,
    promote_contract_signals=True,
)
```

  </TabItem>
</Tabs>

product naming convention은 option으로 전달합니다. customer-specific field dictionary를
library에 넣지 않습니다.

## Artifact Sections

| Section | 목적 |
| --- | --- |
| `graph` | `ToolGraph.load()`와 호환되는 serialized graph payload |
| `tools` | tool name 기준으로 저장된 normalized `ToolSchema` row |
| `metadata` | build option, source identity, version, summary copy |
| `semantic_summary` | action/resource/module/result-shape coverage |
| `edge_quality_summary` | graph edge의 evidence 분포 |
| `readiness_report` | deterministic OpenAPI readiness diagnostics |
| `source_snapshot_manifest` | source label, URL, hash, operation count |
| `ingest_summary` | duplicate 처리와 operation count |
| `quality_lab` | optional product-side search/plan/execute case |
| `learning` | optional scrubbed trace-learning attempt와 suggestion |

artifact 전체를 저장하는 것을 권장합니다. `graph`만 저장하면 readiness와 rebuild behavior를
설명하는 diagnostics를 잃게 됩니다.

## Contract Index

Adapter가 full graph build 전이나 외부에서 operation-level fact를 확인해야 한다면
`extract_openapi_contract_index()`를 사용합니다.

```python
from graph_tool_call.graphify import extract_openapi_contract_index

index = extract_openapi_contract_index("openapi.json")

for operation in index["operations"]:
    print(
        operation["method"],
        operation["path"],
        operation["operationId"],
        operation["content_types"],
        operation["security"],
    )
```

Contract index는 source preview, contract repair, migration check, UI diagnostics에
유용합니다. runtime credential은 이 object에 넣지 않습니다.

## Readiness Gate

Readiness는 build 직후와 source refresh 이후마다 실행합니다.

```python
summary = artifact["readiness_report"]["summary"]
issues = artifact["readiness_report"]["issues"]

if summary["status"] == "blocked":
    disable_execute()

print(summary["readiness_score"])
print(issues[:5])
```

안정 issue code는 다음과 같습니다.

| Code | 의미 | 대표 조치 |
| --- | --- | --- |
| `missing_request_schema` | request field가 보이지 않음 | source repair 또는 adapter metadata 추가 |
| `generic_request_body` | body가 너무 generic해서 안전하게 plan하기 어려움 | schema 구체화 또는 user input 요구 |
| `missing_response_schema` | result field를 produce할 수 없음 | response schema 또는 body view mapping 추가 |
| `duplicate_operation_id` | tool name이 충돌할 수 있음 | operation id 또는 source label 보정 |
| `missing_operation_id` | stable identity가 약함 | method/path 기반 name 파생 후 mapping 보존 |
| `auth_required` | execution에 adapter auth가 필요함 | auth profile과 session header resolution 설정 |
| `unsupported_content_type` | body type을 모델링하기 어려움 | execution adapter handling 추가 |
| `array_leaf_alignment_required` | nested array/body alignment가 불확실함 | body view extraction 검증 |
| `response_envelope_detected` | result가 envelope 아래에 감싸져 있음 | planning 전에 유효한 body view 선택 |
| `low_graph_connectivity` | producer expansion evidence가 약함 | contract와 edge quality 확인 |
| `no_contract_fields` | consumes/produces가 추출되지 않음 | plan/execute 전에 schema repair |

warning은 search를 허용할 수 있지만 blocker는 명시적 override 없이 execute를 막아야 합니다.

## Search And Target Selection

Artifact가 만들어지면 graph retrieval로 작은 candidate set을 만들고, target selection으로
LLM의 최종 target 선택을 guard합니다.

```python
from graph_tool_call.graphify import (
    retrieve_graphify,
    select_target_candidate,
)

retrieval = retrieve_graphify(
    artifact["graph"],
    "환불 가능한 주문을 찾아줘",
    top_k=8,
    include_evidence=True,
)

selection = select_target_candidate(
    query="환불 가능한 주문을 찾아줘",
    candidates=[row["tool_name"] for row in retrieval["results"]],
    tools=artifact["tools"],
    retrieval_results=retrieval["results"],
    llm_target=llm_intent.target,
)

print(selection["selected_target"])
print(selection["candidate_evidence"])
```

product는 나쁜 결과를 디버깅할 수 있도록 충분한 evidence를 저장해야 합니다.

- query text 또는 query fingerprint
- retrieval Top-K와 score breakdown
- LLM target
- selector target
- override flag와 reason code
- selected tool contract summary

## Plan And Execute Gate

Search와 plan quality가 확인된 뒤에만 execution을 열어야 합니다.

필수 조건은 다음과 같습니다.

- readiness report에 blocker issue가 없음
- 대표 search case가 Top-K target을 통과함
- target selector diagnostics가 보임
- 대표 plan case가 예상 step으로 synthesize됨
- auth readiness가 runtime header를 만들 수 있음
- write tool에는 mutation safety와 cleanup policy가 있음

read-only case는 더 일찍 사용할 수 있습니다. mutating case는 explicit allowlist,
confirmation, cleanup step, assertion을 요구해야 합니다.

## Rebuild Policy

Source refresh가 product-owned metadata를 삭제하면 안 됩니다.

보존해야 하는 항목:

- manually curated `ai_metadata`
- `context_defaults`
- `enum_mappings`
- manual edge와 promoted trace edge
- Quality Lab case와 last summary
- `suggested`, `promotable`, `promoted`, `rejected` 상태의 learning suggestion
- auth profile reference와 execution policy

다시 계산해야 하는 항목:

- source-derived tool과 schema
- manual override가 없는 deterministic semantic metadata
- contract field
- readiness report
- weak structural/name-based edge
- edge quality summary

새 source에서 promoted target이 사라졌다면 preserved evidence를 조용히 적용하지 말고 stale로
표시합니다.

## UI Checklist

Product UI는 실행 전에 collection quality를 분명하게 보여줘야 합니다.

- source URL, source count, tool count, graph version
- readiness score와 top blocker/warning issue
- semantic coverage와 unknown sample
- edge quality summary
- auth readiness state
- Quality Lab last run result
- 실패 case의 target selector evidence
- 대형 catalog용 map view와 선택 module/tool용 scoped graph
- rebuild history와 보존된 manual change

대형 collection에서는 모든 edge를 기본 렌더링하지 않습니다. map summary에서 시작하고,
사용자가 module, resource, target, workflow path로 scope를 좁힌 뒤 detailed graph edge를
렌더링합니다.

## Adapter 책임

엔진은 product-neutral evidence를 만듭니다. 애플리케이션은 다음을 책임집니다.

- DB row와 collection lifecycle
- source access permission과 tenant policy
- auth profile과 runtime session header
- model/provider routing
- readiness, graph, Quality Lab, learning result UI
- safe execution policy와 audit logging
- manual operator override
- rebuild 중 product field 보존

raw token, cookie, API key, session id, user identifier는 graph artifact, learning record,
public diagnostics에 저장하지 않습니다.

## 관련 문서

- [OpenAPI Ingestion](../build/openapi-ingestion.md)
- [Collection Artifacts](../build/collection-artifacts.md)
- [Readiness Diagnostics](../build/readiness-diagnostics.md)
- [Tool Graph](../concepts/tool-graph.md)
- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Target Selection](../search/target-selection.md)
- [Quality Lab](../validation/quality-lab.md)
- [Trace Learning](../concepts/trace-learning.md)
