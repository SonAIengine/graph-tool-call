"""Generate domain-neutral long-horizon OpenAPI and Arazzo fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowFamily:
    """One unseen-family workflow configuration."""

    id: str
    title: str
    query: str
    first_operation: str
    stage_operation_prefix: str
    target_operation: str
    certificate_field: str


FAMILIES: tuple[WorkflowFamily, ...] = (
    WorkflowFamily(
        id="supplier_onboarding",
        title="Supplier onboarding",
        query="공급업체 등록 절차를 모두 완료하고 활성화 인증서를 발급해줘",
        first_operation="resolveSupplierTenant",
        stage_operation_prefix="completeSupplierOnboardingStage",
        target_operation="issueSupplierActivationCertificate",
        certificate_field="activationCertificateId",
    ),
    WorkflowFamily(
        id="incident_recovery",
        title="Incident recovery",
        query="서비스 장애 복구 절차를 모두 수행하고 복구 검증 보고서를 발급해줘",
        first_operation="openIncidentInvestigation",
        stage_operation_prefix="completeIncidentRecoveryStage",
        target_operation="issueIncidentRecoveryReport",
        certificate_field="recoveryReportId",
    ),
    WorkflowFamily(
        id="publication_approval",
        title="Publication approval",
        query="콘텐츠 검토 절차를 모두 완료하고 게시 승인 증명서를 발급해줘",
        first_operation="openPublicationReview",
        stage_operation_prefix="completePublicationReviewStage",
        target_operation="issuePublicationApprovalCertificate",
        certificate_field="publicationCertificateId",
    ),
)


def build_fixture(
    family: WorkflowFamily,
    *,
    workflow_length: int,
    catalog_size: int,
) -> dict[str, Any]:
    """Return an OpenAPI catalog, Arazzo workflow, and evaluator-only gold."""

    if workflow_length < 2:
        raise ValueError("workflow_length must be at least 2")
    if catalog_size < workflow_length:
        raise ValueError("catalog_size must be >= workflow_length")

    operations = _operation_names(family, workflow_length)
    paths: dict[str, Any] = {}
    for index, operation in enumerate(operations, start=1):
        request_field = "workflowSeed" if index == 1 else f"handoffToken{index - 1:02d}"
        response_properties = (
            {
                family.certificate_field: {"type": "string"},
                "status": {"type": "string"},
            }
            if index == workflow_length
            else {f"stageEvidence{index:02d}": {"type": "string"}}
        )
        summary = (
            f"{family.title}: {family.query} - 절차 시작"
            if index == 1
            else (
                f"{family.title}: {family.query} - 최종 결과 발급"
                if index == workflow_length
                else f"{family.title}: {family.query} - 필수 단계 {index} 수행"
            )
        )
        paths[f"/{family.id}/stages/{index:02d}"] = {
            "post": {
                "operationId": operation,
                "summary": summary,
                "description": f"Step {index} of {workflow_length} for {family.title}.",
                "tags": [family.title],
                "parameters": [
                    {
                        "name": request_field,
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Successful stage result",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": response_properties,
                                    "required": list(response_properties),
                                }
                            }
                        },
                    }
                },
            }
        }

    distractor_count = catalog_size - workflow_length
    for index in range(1, distractor_count + 1):
        operation = f"lookupArchivedReference{index:04d}"
        paths[f"/archive/references/{index:04d}"] = {
            "get": {
                "operationId": operation,
                "summary": f"Read archived reference record {index}",
                "description": "Unrelated read-only catalog distractor.",
                "tags": ["Archive"],
                "responses": {
                    "200": {
                        "description": "Archived record",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"recordId": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        }

    openapi = {
        "openapi": "3.1.0",
        "info": {"title": f"{family.title} catalog", "version": "1.0.0"},
        "servers": [{"url": "https://example.invalid"}],
        "paths": paths,
    }
    steps: list[dict[str, Any]] = []
    for index, operation in enumerate(operations, start=1):
        step: dict[str, Any] = {
            "stepId": f"step{index:02d}",
            "operationId": operation,
        }
        if index < workflow_length:
            step["outputs"] = {f"stage{index:02d}": f"$response.body#/stageEvidence{index:02d}"}
        if index > 1:
            step["parameters"] = [
                {
                    "name": f"handoffToken{index - 1:02d}",
                    "in": "query",
                    "value": f"$steps.step{index - 1:02d}.outputs.stage{index - 1:02d}",
                }
            ]
        steps.append(step)

    arazzo = {
        "arazzo": "1.1.0",
        "info": {"title": f"{family.title} workflow", "version": "1.0.0"},
        "sourceDescriptions": [
            {
                "name": "catalog",
                "url": "https://example.invalid/openapi.json",
                "type": "openapi",
            }
        ],
        "workflows": [
            {
                "workflowId": f"{family.id}Flow",
                "summary": f"Complete {family.title}",
                "steps": steps,
            }
        ],
    }
    milestones = [
        {
            "id": f"stage_{index:02d}",
            "tools": [operation],
            "target": index == workflow_length,
        }
        for index, operation in enumerate(operations, start=1)
    ]
    scenario = {
        "id": f"{family.id}_{workflow_length}",
        "query": family.query,
        "milestones": milestones,
        "dependency_constraints": [
            {"before": f"stage_{index:02d}", "after": f"stage_{index + 1:02d}"}
            for index in range(1, workflow_length)
        ],
        "binding_constraints": [
            {
                "source_milestone": f"stage_{index:02d}",
                "source_path": f"stageEvidence{index:02d}",
                "target_milestone": f"stage_{index + 1:02d}",
                "target_arg": f"handoffToken{index:02d}",
            }
            for index in range(1, workflow_length)
        ],
        "final_state_assertions": [
            {
                "scope": "output",
                "path": family.certificate_field,
                "operator": "eq",
                "value": f"CERT-{family.id}",
            }
        ],
        "max_calls": workflow_length,
        "max_replans": 0,
        "timeout_sec": 30,
    }
    return {
        "family": family,
        "openapi": openapi,
        "arazzo": arazzo,
        "operations": operations,
        "scenario": scenario,
        "entities": {"workflowSeed": f"SEED-{family.id}"},
    }


def _operation_names(family: WorkflowFamily, workflow_length: int) -> list[str]:
    if workflow_length == 2:
        return [family.first_operation, family.target_operation]
    return [
        family.first_operation,
        *[f"{family.stage_operation_prefix}{index:02d}" for index in range(2, workflow_length)],
        family.target_operation,
    ]
